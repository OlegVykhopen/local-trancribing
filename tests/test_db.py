from app import db


def test_create_and_get_roundtrip(conn):
    jid = db.create_job(conn, "download", {"url": "x"}, category="podcast")
    job = db.get_job(conn, jid)
    assert job["status"] == "queued" and job["params"] == {"url": "x"}


def test_pipeline_kind_and_parent_accepted(conn):
    pid = db.create_job(conn, "pipeline", {})
    cid = db.create_job(conn, "download", {}, parent_job_id=pid)
    assert db.get_job(conn, cid)["parent_job_id"] == pid


def test_status_timestamps(conn):
    jid = db.create_job(conn, "transcribe", {})
    db.set_status(conn, jid, "running")
    db.set_status(conn, jid, "done", result={"output": "a.txt"})
    job = db.get_job(conn, jid)
    assert job["started_at"] and job["finished_at"] and job["result"] == {"output": "a.txt"}


def test_mark_interrupted(conn):
    a = db.create_job(conn, "download", {})
    db.set_status(conn, a, "running")
    assert db.mark_interrupted(conn) == 1
    assert db.get_job(conn, a)["error"] == "interrupted by restart"


def test_logs_ordered(conn):
    jid = db.create_job(conn, "download", {})
    db.append_log(conn, jid, "first line")
    db.append_log(conn, jid, "second line")
    logs = db.get_logs(conn, jid)
    assert [entry["line"] for entry in logs] == ["first line", "second line"]
    assert all("ts" in entry for entry in logs)


def test_list_jobs_filters_by_kind_newest_first(conn):
    d1 = db.create_job(conn, "download", {})
    t1 = db.create_job(conn, "transcribe", {})
    d2 = db.create_job(conn, "download", {})

    downloads = db.list_jobs(conn, kind="download")
    assert [job["id"] for job in downloads] == [d2, d1]

    all_jobs = db.list_jobs(conn)
    assert [job["id"] for job in all_jobs] == [d2, t1, d1]
