import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def wait_until(predicate, timeout=2.0, interval=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture
def roots(tmp_path):
    audio_root = tmp_path / "audio_sources"
    transcripts_root = tmp_path / "transcripts"
    audio_root.mkdir()
    transcripts_root.mkdir()
    (audio_root / "podcast").mkdir()

    db_path = tmp_path / "app.db"
    return audio_root, transcripts_root, db_path


def fake_download_handler(job, ctx):
    """Instant, network-free stand-in for app.services.downloader.run_download."""
    ctx.log("fake download started")
    return {"files": []}


@pytest.fixture
def client(roots):
    audio_root, transcripts_root, db_path = roots
    app = create_app(audio_root, transcripts_root, db_path)
    with TestClient(app) as test_client:
        # Overwrite the real "download" handler so tests never hit the network.
        app.state.worker.register("download", fake_download_handler)
        yield test_client


def test_post_download_creates_queued_job(client):
    resp = client.post("/api/jobs/download", json={"url": "https://example.com/v", "category": "podcast"})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert isinstance(job_id, int)

    assert wait_until(lambda: client.get(f"/api/jobs/{job_id}").json()["status"] == "done")
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["kind"] == "download"
    assert job["params"]["url"] == "https://example.com/v"
    assert job["params"]["category"] == "podcast"
    assert job["result"]["files"] == []


def test_post_download_rejects_empty_url(client):
    resp = client.post("/api/jobs/download", json={"url": "", "category": "podcast"})
    assert resp.status_code == 422


def test_post_download_rejects_unknown_category(client):
    resp = client.post("/api/jobs/download", json={"url": "https://example.com/v", "category": "nope"})
    assert resp.status_code == 400


def test_post_download_rejects_traversal_category(client, roots):
    # transcripts_root is a real sibling directory of audio_root, so a naive
    # (audio_root / category).is_dir() check would accept "../transcripts"
    # and let the downloader write outside audio_root.
    audio_root, transcripts_root, _db_path = roots
    assert transcripts_root.is_dir()

    resp = client.post("/api/jobs/download", json={"url": "https://example.com/v", "category": "../transcripts"})
    assert resp.status_code == 400


def test_post_download_rejects_blank_url(client):
    resp = client.post("/api/jobs/download", json={"url": "   ", "category": "podcast"})
    assert resp.status_code == 422


def test_post_download_allows_empty_category(client):
    resp = client.post("/api/jobs/download", json={"url": "https://example.com/v", "category": ""})
    assert resp.status_code == 202


def test_get_job_and_logs(client):
    resp = client.post("/api/jobs/download", json={"url": "https://example.com/v", "category": "podcast"})
    job_id = resp.json()["job_id"]
    assert wait_until(lambda: client.get(f"/api/jobs/{job_id}").json()["status"] == "done")

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["id"] == job_id

    logs_resp = client.get(f"/api/jobs/{job_id}/logs")
    assert logs_resp.status_code == 200
    logs = logs_resp.json()["logs"]
    assert any(entry["line"] == "fake download started" for entry in logs)


def test_cancel_endpoint_conflict_on_done_job(client):
    resp = client.post("/api/jobs/download", json={"url": "https://example.com/v", "category": "podcast"})
    job_id = resp.json()["job_id"]
    assert wait_until(lambda: client.get(f"/api/jobs/{job_id}").json()["status"] == "done")

    cancel_resp = client.post(f"/api/jobs/{job_id}/cancel")
    assert cancel_resp.status_code == 409
    assert "not cancellable" in cancel_resp.json()["detail"]


def test_cancel_endpoint_404_on_unknown_job(client):
    cancel_resp = client.post("/api/jobs/999999/cancel")
    assert cancel_resp.status_code == 404


def test_unknown_job_404(client):
    resp = client.get("/api/jobs/999999")
    assert resp.status_code == 404


def test_jobs_list_filters_by_kind(client):
    resp = client.post("/api/jobs/download", json={"url": "https://example.com/v", "category": "podcast"})
    job_id = resp.json()["job_id"]
    assert wait_until(lambda: client.get(f"/api/jobs/{job_id}").json()["status"] == "done")

    resp = client.get("/api/jobs", params={"kind": "download"})
    assert resp.status_code == 200
    jobs = resp.json()["jobs"]
    assert any(j["id"] == job_id for j in jobs)

    resp = client.get("/api/jobs", params={"kind": "transcribe"})
    assert resp.json()["jobs"] == []


def test_queue_endpoint_returns_list(client):
    resp = client.get("/api/queue")
    assert resp.status_code == 200
    assert resp.json() == {"queue": []}
