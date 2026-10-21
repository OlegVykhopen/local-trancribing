"""SQLite-backed job store for the transcribing studio job queue.

Each caller (worker thread, FastAPI request handler) opens its own
connection via connect(); WAL mode makes concurrent per-thread
connections to the same file safe.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    kind TEXT CHECK(kind IN ('download', 'transcribe', 'pipeline')),
    status TEXT,
    params_json TEXT,
    category TEXT,
    parent_job_id INTEGER,
    progress INTEGER DEFAULT 0,
    stage TEXT,
    result_json TEXT,
    error TEXT,
    created_at TEXT,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS job_logs (
    id INTEGER PRIMARY KEY,
    job_id INTEGER,
    ts TEXT,
    line TEXT
);
"""

TERMINAL_STATUSES = {"done", "error", "cancelled"}


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a connection to the job store, creating the schema if missing."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _row_to_job(row: sqlite3.Row) -> dict:
    job = dict(row)
    params_json = job.pop("params_json")
    job["params"] = json.loads(params_json) if params_json is not None else None
    result_json = job.pop("result_json")
    job["result"] = json.loads(result_json) if result_json is not None else None
    return job


def create_job(
    conn: sqlite3.Connection,
    kind: str,
    params: dict,
    category: str | None = None,
    parent_job_id: int | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO jobs (kind, status, params_json, category, parent_job_id, progress, created_at)
        VALUES (?, 'queued', ?, ?, ?, 0, ?)
        """,
        (kind, json.dumps(params), category, parent_job_id, datetime.now().isoformat()),
    )
    conn.commit()
    return cursor.lastrowid


def get_job(conn: sqlite3.Connection, job_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row is not None else None


def list_jobs(conn: sqlite3.Connection, kind: str | None = None, limit: int = 100) -> list[dict]:
    if kind is not None:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE kind = ? ORDER BY id DESC LIMIT ?",
            (kind, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_job(row) for row in rows]


def set_status(
    conn: sqlite3.Connection,
    job_id: int,
    status: str,
    error: str | None = None,
    result: dict | None = None,
) -> None:
    now = datetime.now().isoformat()
    started_at = now if status == "running" else None
    finished_at = now if status in TERMINAL_STATUSES else None
    result_json = json.dumps(result) if result is not None else None

    conn.execute(
        """
        UPDATE jobs
        SET status = ?,
            error = ?,
            result_json = COALESCE(?, result_json),
            started_at = COALESCE(?, started_at),
            finished_at = COALESCE(?, finished_at)
        WHERE id = ?
        """,
        (status, error, result_json, started_at, finished_at, job_id),
    )
    conn.commit()


def set_progress(conn: sqlite3.Connection, job_id: int, progress: int, stage: str) -> None:
    conn.execute(
        "UPDATE jobs SET progress = ?, stage = ? WHERE id = ?",
        (progress, stage, job_id),
    )
    conn.commit()


def append_log(conn: sqlite3.Connection, job_id: int, line: str) -> None:
    conn.execute(
        "INSERT INTO job_logs (job_id, ts, line) VALUES (?, ?, ?)",
        (job_id, datetime.now().isoformat(), line),
    )
    conn.commit()


def get_logs(conn: sqlite3.Connection, job_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT ts, line FROM job_logs WHERE job_id = ? ORDER BY id ASC",
        (job_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def mark_interrupted(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        """
        UPDATE jobs
        SET status = 'error', error = 'interrupted by restart', finished_at = ?
        WHERE status IN ('queued', 'running', 'cancelling')
        """,
        (datetime.now().isoformat(),),
    )
    conn.commit()
    return cursor.rowcount
