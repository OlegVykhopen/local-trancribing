"""Sequential job worker with cooperative cancellation.

A single daemon thread pulls job ids off a FIFO queue and runs them one
at a time through a registered handler. The API thread (or tests) submit
job ids and may request cancellation; cancellation is cooperative — a
running job only stops when its handler calls `ctx.check_cancelled()`.

The worker thread owns exactly one sqlite connection, opened in-thread,
because sqlite3 connections are not safe to share across threads. Any
other thread (the API, or `Worker.cancel`) that needs to touch the DB
opens its own short-lived connection via `app.db.connect`.
"""

import queue
import sys
import threading
import time
import traceback
from typing import Callable

from app import db
from transcribe import JobCancelled


_STOP = object()


class JobContext:
    """Per-job handle passed to handlers for logging, progress, and cancellation."""

    def __init__(self, conn, bus, job_id: int, cancel_event: threading.Event) -> None:
        self.job_id = job_id
        self.cancel_event = cancel_event
        self._conn = conn
        self._bus = bus
        self._last_write_time: float | None = None
        self._last_write_percent: float | None = None

    def log(self, line: str) -> None:
        db.append_log(self._conn, self.job_id, line)
        self._bus.publish({"type": "job_log", "job_id": self.job_id, "line": line})

    def progress(self, percent: float, stage: str, detail: str = "") -> None:
        # Clamp here, at the single entry point, so the 0-100 invariant holds
        # everywhere downstream (DB column, SSE payloads, JobResponse's
        # ge/le validation) regardless of what a handler reports.
        percent = min(100.0, max(0.0, percent))
        now = time.monotonic()
        # percent >= 100 always forces a write: without this, a final call that
        # lands within the throttle window (<1s, <2% delta) would be dropped and
        # the job would persist a stale progress value forever after finishing.
        stale = (
            percent >= 100
            or self._last_write_time is None
            or now - self._last_write_time >= 1.0
            or self._last_write_percent is None
            or abs(percent - self._last_write_percent) >= 2
        )
        if stale:
            db.set_progress(self._conn, self.job_id, int(round(percent)), stage)
            self._last_write_time = now
            self._last_write_percent = percent

        self._bus.publish(
            {
                "type": "job_progress",
                "job_id": self.job_id,
                "stage": stage,
                "percent": percent,
                "detail": detail,
            }
        )

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise JobCancelled()


class Worker:
    """Single daemon worker thread draining a FIFO queue of job ids."""

    def __init__(self, db_path: str, bus) -> None:
        self.db_path = db_path
        self.bus = bus
        self._handlers: dict[str, Callable[[dict, JobContext], dict]] = {}
        self._queue: "queue.Queue" = queue.Queue()
        self._pending_lock = threading.Lock()
        self._pending_ids: list[int] = []
        self._events_lock = threading.Lock()
        self._cancel_events: dict[int, threading.Event] = {}
        self._thread: threading.Thread | None = None
        # Guards every read-then-write status transition (pickup, terminal
        # write, cancel) so cancel() and the run loop can never race on the
        # same job's status column — see _try_pickup / _write_terminal / cancel.
        self._status_lock = threading.Lock()

    def register(self, kind: str, handler: Callable[[dict, JobContext], dict]) -> None:
        self._handlers[kind] = handler

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Shutdown teardown (lifespan exit and tests): ask the loop to exit
        and wait briefly for it. A running job is not interrupted; it is
        marked interrupted on the next startup via db.mark_interrupted."""
        self._queue.put(_STOP)
        if self._thread is not None:
            self._thread.join(timeout=2)

    def submit(self, job_id: int) -> None:
        with self._events_lock:
            self._cancel_events[job_id] = threading.Event()
        with self._pending_lock:
            self._pending_ids.append(job_id)
        self._queue.put(job_id)
        self._publish_queue()

    def cancel(self, job_id: int) -> str | None:
        with self._events_lock:
            event = self._cancel_events.get(job_id)
        if event is None:
            return None

        conn = db.connect(self.db_path)
        try:
            # The read-and-decide-and-write below shares _status_lock with
            # _try_pickup and _write_terminal, so it can never observe a
            # status value that the run loop is concurrently about to
            # overwrite (and vice versa) — see those methods for the two
            # races this closes.
            with self._status_lock:
                job = db.get_job(conn, job_id)
                if job is None:
                    return None

                if job["status"] == "queued":
                    db.set_status(conn, job_id, "cancelled")
                    outcome = "cancelled"
                elif job["status"] == "running":
                    db.set_status(conn, job_id, "cancelling")
                    event.set()
                    outcome = "cancelling"
                else:
                    return None

            if outcome == "cancelled":
                with self._pending_lock:
                    if job_id in self._pending_ids:
                        self._pending_ids.remove(job_id)
                with self._events_lock:
                    self._cancel_events.pop(job_id, None)
                self.bus.publish({"type": "job_status", "job_id": job_id, "status": "cancelled"})
                self._publish_queue()
            else:
                self.bus.publish({"type": "job_status", "job_id": job_id, "status": "cancelling"})

            return outcome
        finally:
            conn.close()

    def queue_snapshot(self) -> list[int]:
        with self._pending_lock:
            return list(self._pending_ids)

    def _publish_queue(self) -> None:
        self.bus.publish({"type": "queue", "queue": self.queue_snapshot()})

    def _try_pickup(self, conn, job_id: int) -> dict | None:
        """Atomically claim a queued job by flipping it to 'running'.

        Shares _status_lock with cancel(): if cancel() is mid-transition on
        this job id, this call blocks until it finishes and then re-reads
        the up-to-date status, so a job cancel() just marked 'cancelled'
        can never be picked up and run, and a job this just claimed as
        'running' can never be reported as 'cancelled' by a concurrent
        cancel() call.
        """
        with self._status_lock:
            job = db.get_job(conn, job_id)
            if job is not None and job["status"] == "queued":
                db.set_status(conn, job_id, "running")
                return job
            return None

    def _write_terminal(self, conn, job_id: int, status: str, error: str | None = None, result: dict | None = None) -> None:
        """Atomically write a terminal status.

        Shares _status_lock with cancel(): if cancel() is mid-transition on
        this job id (reading 'running' to decide whether to write
        'cancelling'), this call blocks until cancel() finishes, and
        cancel()'s own lock usage ensures it never overwrites a terminal
        status written here with 'cancelling' after the fact.
        """
        with self._status_lock:
            db.set_status(conn, job_id, status, error=error, result=result)

    def _run(self) -> None:
        conn = db.connect(self.db_path)
        try:
            while True:
                job_id = self._queue.get()
                if job_id is _STOP:
                    break

                try:
                    self._run_one(conn, job_id)
                except Exception:  # noqa: BLE001
                    # Infrastructure failure (e.g. sqlite "database is
                    # locked" during a status write). Losing this job's
                    # bookkeeping is bad; silently killing the daemon thread
                    # — leaving every future job queued forever — is worse.
                    print(
                        f"worker: unexpected error processing job {job_id}:\n{traceback.format_exc()}",
                        file=sys.stderr,
                    )
        finally:
            conn.close()

    def _run_one(self, conn, job_id: int) -> None:
        with self._pending_lock:
            if job_id in self._pending_ids:
                self._pending_ids.remove(job_id)
        self._publish_queue()

        job = self._try_pickup(conn, job_id)
        if job is None:
            # Cancelled while queued (or otherwise no longer runnable).
            with self._events_lock:
                self._cancel_events.pop(job_id, None)
            return

        self.bus.publish({"type": "job_status", "job_id": job_id, "status": "running"})

        with self._events_lock:
            cancel_event = self._cancel_events.get(job_id, threading.Event())
        ctx = JobContext(conn, self.bus, job_id, cancel_event)
        handler = self._handlers.get(job["kind"])

        try:
            if handler is None:
                raise ValueError(f"no handler for kind {job['kind']!r}")
            result = handler(job, ctx)
        except JobCancelled:
            self._write_terminal(conn, job_id, "cancelled")
            self.bus.publish({"type": "job_status", "job_id": job_id, "status": "cancelled"})
        except Exception as exc:  # noqa: BLE001 - handler errors become job errors
            # str(exc) can be empty (bare exceptions); fall back to the type
            # name so the job never shows status "error" with no message, and
            # put the full traceback in the job log for debuggability.
            error_text = str(exc) or type(exc).__name__
            db.append_log(conn, job_id, traceback.format_exc())
            self._write_terminal(conn, job_id, "error", error=error_text)
            self.bus.publish({"type": "job_status", "job_id": job_id, "status": "error", "error": error_text})
        else:
            self._write_terminal(conn, job_id, "done", result=result)
            self.bus.publish({"type": "job_status", "job_id": job_id, "status": "done", "result": result})
        finally:
            with self._events_lock:
                self._cancel_events.pop(job_id, None)
            self._publish_queue()
