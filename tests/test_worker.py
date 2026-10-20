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
