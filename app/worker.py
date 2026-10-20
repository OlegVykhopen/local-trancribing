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
import threading
import time
from typing import Callable

from app import db

try:
    from transcribe import JobCancelled
except ImportError:  # pragma: no cover - transcribe.py defines this in a later task
    class JobCancelled(Exception):
        pass


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
        now = time.monotonic()
        stale = (
            self._last_write_time is None
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

    def register(self, kind: str, handler: Callable[[dict, JobContext], dict]) -> None:
        self._handlers[kind] = handler

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Test-only teardown: ask the loop to exit and wait briefly for it."""
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
            job = db.get_job(conn, job_id)
            if job is None:
                return None

            if job["status"] == "queued":
                db.set_status(conn, job_id, "cancelled")
                with self._pending_lock:
                    if job_id in self._pending_ids:
                        self._pending_ids.remove(job_id)
                with self._events_lock:
                    self._cancel_events.pop(job_id, None)
                self.bus.publish({"type": "job_status", "job_id": job_id, "status": "cancelled"})
                self._publish_queue()
                return "cancelled"

            if job["status"] == "running":
                db.set_status(conn, job_id, "cancelling")
                event.set()
                self.bus.publish({"type": "job_status", "job_id": job_id, "status": "cancelling"})
                return "cancelling"

            return None
        finally:
            conn.close()

    def queue_snapshot(self) -> list[int]:
        with self._pending_lock:
            return list(self._pending_ids)

    def _publish_queue(self) -> None:
        self.bus.publish({"type": "queue", "queue": self.queue_snapshot()})

    def _run(self) -> None:
        conn = db.connect(self.db_path)
        try:
            while True:
                job_id = self._queue.get()
                if job_id is _STOP:
                    break

                with self._pending_lock:
                    if job_id in self._pending_ids:
                        self._pending_ids.remove(job_id)
                self._publish_queue()

                job = db.get_job(conn, job_id)
                if job is None or job["status"] != "queued":
                    # Cancelled while queued (or otherwise no longer runnable).
                    with self._events_lock:
                        self._cancel_events.pop(job_id, None)
                    continue

                db.set_status(conn, job_id, "running")
                self.bus.publish({"type": "job_status", "job_id": job_id, "status": "running"})

                with self._events_lock:
                    cancel_event = self._cancel_events.get(job_id, threading.Event())
                ctx = JobContext(conn, self.bus, job_id, cancel_event)
                handler = self._handlers.get(job["kind"])

                try:
                    result = handler(job, ctx)
                except JobCancelled:
                    db.set_status(conn, job_id, "cancelled")
                    self.bus.publish({"type": "job_status", "job_id": job_id, "status": "cancelled"})
                except Exception as exc:  # noqa: BLE001 - handler errors become job errors
                    db.set_status(conn, job_id, "error", error=str(exc))
                    self.bus.publish({"type": "job_status", "job_id": job_id, "status": "error"})
                else:
                    db.set_status(conn, job_id, "done", result=result)
                    self.bus.publish({"type": "job_status", "job_id": job_id, "status": "done"})
                finally:
                    with self._events_lock:
                        self._cancel_events.pop(job_id, None)
                    self._publish_queue()
        finally:
            conn.close()
