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
    (audio_root / "podcast" / "ep1.mp3").write_bytes(b"fake audio")

    db_path = tmp_path / "app.db"
    return audio_root, transcripts_root, db_path


def fake_transcribe_handler(job, ctx):
    """Instant, model-free stand-in for app.services.transcriber.run_transcribe."""
    ctx.log("fake transcribe started")
    return {"output_path": job["params"]["path"] + ".txt"}


@pytest.fixture
def client(roots):
    audio_root, transcripts_root, db_path = roots
    app = create_app(audio_root, transcripts_root, db_path)
    with TestClient(app) as test_client:
        # Overwrite the real "transcribe" handler so tests never load a real model.
        app.state.worker.register("transcribe", fake_transcribe_handler)
        yield test_client


def test_post_transcribe_validates_model(client):
    resp = client.post(
        "/api/jobs/transcribe",
        json={"path": "podcast/ep1.mp3", "model": "not-a-real-model", "diarize": False},
    )
    assert resp.status_code == 400


def test_post_transcribe_rejects_escaping_path(client):
    resp = client.post(
        "/api/jobs/transcribe",
        json={"path": "../outside.mp3", "model": "tiny", "diarize": False},
    )
    assert resp.status_code == 400


def test_post_transcribe_queues_job(client):
    resp = client.post(
        "/api/jobs/transcribe",
        json={"path": "podcast/ep1.mp3", "model": "tiny", "diarize": False},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert isinstance(job_id, int)

    assert wait_until(lambda: client.get(f"/api/jobs/{job_id}").json()["status"] == "done")
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["kind"] == "transcribe"
    assert job["params"]["path"] == "podcast/ep1.mp3"
    assert job["params"]["model"] == "tiny"
    assert job["category"] == "podcast"
    assert job["result"]["output_path"] == "podcast/ep1.mp3.txt"
