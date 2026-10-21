import threading
import time
from types import SimpleNamespace

import pytest

from app import db
from app.events import EventBus
from app.worker import JobCancelled, Worker


def wait_until(predicate, timeout=2.0, interval=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture
def env(tmp_path):
    db_path = str(tmp_path / "jobs.db")
    bus = EventBus()
    conn = db.connect(db_path)
    worker = Worker(db_path, bus)
    ns = SimpleNamespace(worker=worker, conn=conn, bus=bus, db_path=db_path)
    yield ns
    worker.stop()
    conn.close()


def test_jobs_run_sequentially_in_submit_order(env):
    order = []

    def handler(job, ctx):
        order.append(job["id"])
        return {}

    env.worker.register("download", handler)
    env.worker.start()

    ids = [db.create_job(env.conn, "download", {}) for _ in range(3)]
    for jid in ids:
        env.worker.submit(jid)

    assert wait_until(lambda: len(order) == 3)
    assert order == ids


def test_handler_result_stored_and_status_done(env):
    def handler(job, ctx):
        return {"output": "transcript.txt"}

    env.worker.register("transcribe", handler)
    env.worker.start()

    jid = db.create_job(env.conn, "transcribe", {})
    env.worker.submit(jid)

    assert wait_until(lambda: db.get_job(env.conn, jid)["status"] == "done")
    job = db.get_job(env.conn, jid)
    assert job["result"] == {"output": "transcript.txt"}


def test_handler_exception_sets_error(env):
    def handler(job, ctx):
        raise ValueError("boom")

    env.worker.register("download", handler)
    env.worker.start()

    jid = db.create_job(env.conn, "download", {})
    env.worker.submit(jid)

    assert wait_until(lambda: db.get_job(env.conn, jid)["status"] == "error")
    job = db.get_job(env.conn, jid)
    assert job["error"] == "boom"


def test_cancel_queued_job_never_runs(env):
    first_release = threading.Event()
    second_ran = []

    def blocking_handler(job, ctx):
        first_release.wait(timeout=5)
        return {}

    def tracking_handler(job, ctx):
        second_ran.append(job["id"])
        return {}

    env.worker.register("download", blocking_handler)
    env.worker.register("transcribe", tracking_handler)
    env.worker.start()

    first_id = db.create_job(env.conn, "download", {})
    second_id = db.create_job(env.conn, "transcribe", {})
    env.worker.submit(first_id)
    assert wait_until(lambda: db.get_job(env.conn, first_id)["status"] == "running")

    env.worker.submit(second_id)
    assert wait_until(lambda: second_id in env.worker.queue_snapshot())

    result = env.worker.cancel(second_id)
    assert result == "cancelled"

    first_release.set()
    assert wait_until(lambda: db.get_job(env.conn, first_id)["status"] == "done")

    # give the worker a moment to have (not) picked up the second job
    time.sleep(0.1)
    assert second_ran == []
    assert db.get_job(env.conn, second_id)["status"] == "cancelled"


def test_cancel_running_sets_cancelling_then_cancelled(env):
    def handler(job, ctx):
        ctx.cancel_event.wait(timeout=5)
        ctx.check_cancelled()
        return {}

    env.worker.register("download", handler)
    env.worker.start()

    jid = db.create_job(env.conn, "download", {})
    env.worker.submit(jid)

    assert wait_until(lambda: db.get_job(env.conn, jid)["status"] == "running")

    result = env.worker.cancel(jid)
    assert result == "cancelling"
    assert db.get_job(env.conn, jid)["status"] == "cancelling"

    assert wait_until(lambda: db.get_job(env.conn, jid)["status"] == "cancelled")


def test_cancel_finished_job_is_noop_returns_none(env):
    def handler(job, ctx):
        return {}

    env.worker.register("download", handler)
    env.worker.start()

    jid = db.create_job(env.conn, "download", {})
    env.worker.submit(jid)

    assert wait_until(lambda: db.get_job(env.conn, jid)["status"] == "done")

    assert env.worker.cancel(jid) is None


def test_double_cancel_idempotent(env):
    blocker = threading.Event()

    def blocking_handler(job, ctx):
        ctx.cancel_event.wait(timeout=5)
        ctx.check_cancelled()
        return {}

    def noop_handler(job, ctx):
        return {}

    env.worker.register("download", blocking_handler)
    env.worker.register("transcribe", noop_handler)
    env.worker.start()

    running_id = db.create_job(env.conn, "download", {})
    env.worker.submit(running_id)
    assert wait_until(lambda: db.get_job(env.conn, running_id)["status"] == "running")

    assert env.worker.cancel(running_id) == "cancelling"
    assert env.worker.cancel(running_id) is None

    assert wait_until(lambda: db.get_job(env.conn, running_id)["status"] == "cancelled")

    # unrelated queued job, cancelled twice while still queued
    queued_id = db.create_job(env.conn, "transcribe", {})
    # block the worker with a fresh running job so queued_id stays queued
    env.worker.register("download", blocking_handler)
    blocker_id = db.create_job(env.conn, "download", {})
    env.worker.submit(blocker_id)
    assert wait_until(lambda: db.get_job(env.conn, blocker_id)["status"] == "running")

    env.worker.submit(queued_id)
    assert wait_until(lambda: queued_id in env.worker.queue_snapshot())

    assert env.worker.cancel(queued_id) == "cancelled"
    assert env.worker.cancel(queued_id) is None

    env.worker.cancel(blocker_id)
    assert wait_until(lambda: db.get_job(env.conn, blocker_id)["status"] == "cancelled")


def test_rapid_progress_calls_final_value_persisted(env):
    def handler(job, ctx):
        ctx.progress(99, "transcribing")
        ctx.progress(100, "done")
        return {}

    env.worker.register("transcribe", handler)
    env.worker.start()

    jid = db.create_job(env.conn, "transcribe", {})
    env.worker.submit(jid)

    assert wait_until(lambda: db.get_job(env.conn, jid)["status"] == "done")
    assert db.get_job(env.conn, jid)["progress"] == 100


class RecordingBus:
    """Fake bus that records published events instead of fanning them out
    over asyncio — used to assert on event payloads without needing an
    attached event loop (see app.events.EventBus.publish)."""

    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


def test_terminal_error_event_includes_error_text(tmp_path):
    db_path = str(tmp_path / "jobs.db")
    bus = RecordingBus()
    conn = db.connect(db_path)
    worker = Worker(db_path, bus)

    def handler(job, ctx):
        raise ValueError("boom")

    worker.register("download", handler)
    worker.start()
    try:
        jid = db.create_job(conn, "download", {})
        worker.submit(jid)

        assert wait_until(lambda: db.get_job(conn, jid)["status"] == "error")
    finally:
        worker.stop()
        conn.close()

    error_events = [e for e in bus.events if e.get("type") == "job_status" and e.get("status") == "error"]
    assert error_events
    assert error_events[-1]["error"] == "boom"


def test_unknown_kind_sets_error(env):
    env.worker.start()

    jid = db.create_job(env.conn, "download", {})
    env.worker.submit(jid)

    assert wait_until(lambda: db.get_job(env.conn, jid)["status"] == "error")
    assert "no handler" in db.get_job(env.conn, jid)["error"]


def test_cancel_cannot_return_cancelled_for_a_job_that_is_being_picked_up(env, monkeypatch):
    """Deterministically forces the pickup-vs-cancel race window (Review Finding 1).

    Pauses _try_pickup's run-loop thread *while it holds _status_lock*, right
    before it writes 'running', then calls cancel() concurrently. If the lock
    didn't serialize these two operations, cancel() could read the
    pre-pickup 'queued' status and return 'cancelled' for a job that the run
    loop then goes on to execute anyway. With the lock, cancel() must block
    until pickup finishes and then correctly see 'running'.
    """
    env.worker.register("download", lambda job, ctx: {})
    jid = db.create_job(env.conn, "download", {})
    with env.worker._events_lock:
        env.worker._cancel_events[jid] = threading.Event()

    entered_critical_section = threading.Event()
    release_critical_section = threading.Event()
    real_set_status = db.set_status

    def patched_set_status(conn, job_id, status, error=None, result=None):
        if job_id == jid and status == "running":
            entered_critical_section.set()
            release_critical_section.wait(timeout=5)
        return real_set_status(conn, job_id, status, error=error, result=result)

    monkeypatch.setattr(db, "set_status", patched_set_status)

    pickup_result = {}

    def do_pickup():
        # sqlite3 connections are not safe to share across threads, so this
        # connection must be opened inside the thread that uses it.
        pickup_conn = db.connect(env.db_path)
        try:
            pickup_result["job"] = env.worker._try_pickup(pickup_conn, jid)
        finally:
            pickup_conn.close()

    pickup_thread = threading.Thread(target=do_pickup)
    pickup_thread.start()

    # Pickup is now inside the patched set_status call, which means it is
    # holding _status_lock with the DB status still 'queued' on disk.
    assert entered_critical_section.wait(timeout=2)

    cancel_result = {}

    def do_cancel():
        cancel_result["value"] = env.worker.cancel(jid)

    cancel_thread = threading.Thread(target=do_cancel)
    cancel_thread.start()

    # cancel_thread must block on _status_lock here, regardless of scheduling,
    # since pickup_thread provably still holds it.
    release_critical_section.set()
    pickup_thread.join(timeout=2)
    cancel_thread.join(timeout=2)

    assert pickup_result["job"] is not None  # pickup claimed the job
    assert cancel_result["value"] == "cancelling"  # never "cancelled" for a job that ran
    assert db.get_job(env.conn, jid)["status"] == "cancelling"


def test_cancel_cannot_clobber_a_terminal_status_just_written(env, monkeypatch):
    """Deterministically forces the running-vs-terminal-write race window (Review Finding 2).

    Pauses the run loop's terminal 'done' write *while it holds
    _status_lock*, then calls cancel() concurrently. If the lock didn't
    serialize these two operations, cancel() could read the stale 'running'
    status and overwrite the just-written terminal 'done' row with
    'cancelling' forever. With the lock, cancel() must block until the
    terminal write finishes and then correctly see 'done' and no-op.
    """
    env.worker.register("download", lambda job, ctx: {})
    jid = db.create_job(env.conn, "download", {})

    entered_critical_section = threading.Event()
    release_critical_section = threading.Event()
    real_set_status = db.set_status

    def patched_set_status(conn, job_id, status, error=None, result=None):
        if job_id == jid and status == "done":
            entered_critical_section.set()
            release_critical_section.wait(timeout=5)
        return real_set_status(conn, job_id, status, error=error, result=result)

    monkeypatch.setattr(db, "set_status", patched_set_status)
    env.worker.start()
    env.worker.submit(jid)

    # The handler returns instantly, so the run loop is now attempting its
    # terminal 'done' write and is stuck inside patched_set_status, holding
    # _status_lock, with the DB status still 'running' on disk.
    assert entered_critical_section.wait(timeout=2)

    cancel_result = {}

    def do_cancel():
        cancel_result["value"] = env.worker.cancel(jid)

    cancel_thread = threading.Thread(target=do_cancel)
    cancel_thread.start()

    release_critical_section.set()
    cancel_thread.join(timeout=2)

    assert cancel_result["value"] is None  # job was already terminal, no-op
    assert db.get_job(env.conn, jid)["status"] == "done"  # never clobbered
