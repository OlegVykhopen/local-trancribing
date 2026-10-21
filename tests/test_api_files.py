import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def roots(tmp_path):
    """Build a small audio/transcripts tree under tmp_path.

    audio/therapy/a.m4a -> transcribed
    audio/c.mp3         -> loose, not transcribed
    """
    audio_root = tmp_path / "audio_sources"
    transcripts_root = tmp_path / "transcripts"
    audio_root.mkdir()
    transcripts_root.mkdir()

    (audio_root / "therapy").mkdir()
    (audio_root / "therapy" / "a.m4a").write_bytes(b"")
    (audio_root / "c.mp3").write_bytes(b"")

    (transcripts_root / "therapy").mkdir()
    (transcripts_root / "therapy" / "a.m4a.txt").write_text("transcript a")

    db_path = tmp_path / "app.db"

    return audio_root, transcripts_root, db_path


@pytest.fixture
def client(roots):
    audio_root, transcripts_root, db_path = roots
    app = create_app(audio_root, transcripts_root, db_path)
    with TestClient(app) as test_client:
        yield test_client


def test_files_endpoint_shape(client):
    resp = client.get("/api/files")
    assert resp.status_code == 200
    body = resp.json()
    assert "tree" in body
    tree = body["tree"]
    assert isinstance(tree, list)

    therapy = next(node for node in tree if node["name"] == "therapy")
    assert therapy["type"] == "dir"
    a_file = next(child for child in therapy["children"] if child["name"] == "a.m4a")
    assert a_file["transcribed"] is True

    c_file = next(node for node in tree if node["name"] == "c.mp3")
    assert c_file["transcribed"] is False


def test_transcript_traversal_rejected(client):
    assert client.get("/api/transcript", params={"path": "../.env"}).status_code == 400


def test_transcript_returns_content(client):
    resp = client.get("/api/transcript", params={"path": "therapy/a.m4a.txt"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == "therapy/a.m4a.txt"
    assert body["content"] == "transcript a"


def test_transcript_unknown_file_is_400(client):
    resp = client.get("/api/transcript", params={"path": "therapy/does-not-exist.txt"})
    assert resp.status_code == 400


def test_create_category(client):
    resp = client.post("/api/categories", json={"name": "podcast"})
    assert resp.status_code == 201

    resp = client.get("/api/categories")
    assert resp.status_code == 200
    assert "podcast" in resp.json()["categories"]
    assert "therapy" in resp.json()["categories"]


def test_create_category_invalid_name_is_400(client):
    resp = client.post("/api/categories", json={"name": "../evil"})
    assert resp.status_code == 400


def test_meta_lists_models(client, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    resp = client.get("/api/meta")
    assert resp.status_code == 200
    body = resp.json()
    assert body["models"] == ["tiny", "base", "small", "medium", "large", "large-v3"]
    assert body["default_model"] == "base"
    assert body["hf_token_present"] is False


def test_meta_lists_languages(client):
    resp = client.get("/api/meta")
    body = resp.json()
    languages = body["languages"]
    assert {"code": "uk", "name": "ukrainian"} in languages
    assert {"code": "en", "name": "english"} in languages
    # sorted by name so the dropdown reads alphabetically
    names = [lang["name"] for lang in languages]
    assert names == sorted(names)


def test_meta_hf_token_present(client, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "some-token")
    resp = client.get("/api/meta")
    assert resp.json()["hf_token_present"] is True


def test_startup_marks_interrupted_jobs(roots):
    from app import db as db_module

    audio_root, transcripts_root, db_path = roots
    conn = db_module.connect(db_path)
    job_id = db_module.create_job(conn, "transcribe", {})
    db_module.set_status(conn, job_id, "running")
    conn.close()

    app = create_app(audio_root, transcripts_root, db_path)
    with TestClient(app):
        pass

    conn = db_module.connect(db_path)
    job = db_module.get_job(conn, job_id)
    conn.close()
    assert job["status"] == "error"
