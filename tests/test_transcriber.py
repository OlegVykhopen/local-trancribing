from pathlib import Path

import pytest

from app.services import transcriber
from transcribe import JobCancelled


class FakeContext:
    """Stand-in for JobContext: records progress/log calls, exposes cancel_event."""

    def __init__(self):
        self.progress_calls = []
        self.logs = []
        self.cancel_event = None

    def progress(self, percent, stage, detail=""):
        self.progress_calls.append((percent, stage, detail))

    def log(self, line):
        self.logs.append(line)

    def check_cancelled(self):
        pass


@pytest.fixture
def roots(tmp_path):
    audio_root = tmp_path / "audio_sources"
    transcripts_root = tmp_path / "transcripts"
    audio_root.mkdir()
    transcripts_root.mkdir()
    return audio_root, transcripts_root


def _patch_models(monkeypatch, whisper_model="fake-whisper-model", diarizer=None):
    calls = {"whisper": [], "diarizer": []}

    def fake_load_whisper_model(model_name, language=None, threads=4, beam_size=5):
        calls["whisper"].append((model_name, language, threads, beam_size))
        return object() if whisper_model == "fresh" else whisper_model

    def fake_load_diarization_model(hf_token, log_fn=print):
        calls["diarizer"].append(hf_token)
        return diarizer

    monkeypatch.setattr(transcriber, "load_whisper_model", fake_load_whisper_model)
    monkeypatch.setattr(transcriber, "load_diarization_model", fake_load_diarization_model)
    return calls


def test_missing_source_raises_readable_error(tmp_path, monkeypatch):
    audio_root = tmp_path / "audio_sources"
    transcripts_root = tmp_path / "transcripts"
    audio_root.mkdir()
    transcripts_root.mkdir()
    _patch_models(monkeypatch)
    monkeypatch.setattr(transcriber, "transcribe_file", lambda *a, **k: pytest.fail("should not be called"))

    ctx = FakeContext()
    cache = transcriber.ModelCache()
    params = {"path": "missing.mp3", "model": "base", "language": None, "diarize": False, "num_speakers": None}

    with pytest.raises(RuntimeError, match="source file not found: missing.mp3"):
        transcriber.run_transcribe(params, ctx, audio_root, transcripts_root, cache)


def test_missing_source_raises_readable_error_when_escaping_root(tmp_path, monkeypatch):
    audio_root = tmp_path / "audio_sources"
    transcripts_root = tmp_path / "transcripts"
    audio_root.mkdir()
    transcripts_root.mkdir()
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"x")
    _patch_models(monkeypatch)
    monkeypatch.setattr(transcriber, "transcribe_file", lambda *a, **k: pytest.fail("should not be called"))

    ctx = FakeContext()
    cache = transcriber.ModelCache()
    params = {"path": "../outside.mp3", "model": "base", "language": None, "diarize": False, "num_speakers": None}

    with pytest.raises(RuntimeError, match="source file not found"):
        transcriber.run_transcribe(params, ctx, audio_root, transcripts_root, cache)


def test_output_dir_mirrors_nested_relative_path(roots, monkeypatch):
    audio_root, transcripts_root = roots
    (audio_root / "consulting" / "marketing").mkdir(parents=True)
    source = audio_root / "consulting" / "marketing" / "x.mp3"
    source.write_bytes(b"audio")

    _patch_models(monkeypatch)

    captured = {}

    def fake_transcribe_file(model, audio_path, output_dir, **kwargs):
        captured["audio_path"] = audio_path
        captured["output_dir"] = output_dir
        return str(Path(output_dir) / "x.mp3.txt")

    monkeypatch.setattr(transcriber, "transcribe_file", fake_transcribe_file)

    ctx = FakeContext()
    cache = transcriber.ModelCache()
    params = {
        "path": "consulting/marketing/x.mp3",
        "model": "base",
        "language": None,
        "diarize": False,
        "num_speakers": None,
    }

    result = transcriber.run_transcribe(params, ctx, audio_root, transcripts_root, cache)

    expected_output_dir = transcripts_root / "consulting" / "marketing"
    assert expected_output_dir.is_dir()
    assert captured["output_dir"] == str(expected_output_dir)
    assert captured["audio_path"] == str(source)
    assert result == {"output_path": "consulting/marketing/x.mp3.txt"}


def test_cache_reuses_model_for_same_key_and_evicts_on_change():
    cache = transcriber.ModelCache()
    load_calls = []

    class FakeModel:
        def __init__(self, name):
            self.name = name

    def fake_load_whisper_model(model_name, language=None, threads=4, beam_size=5):
        load_calls.append((model_name, language, threads, beam_size))
        return FakeModel(model_name)

    original = transcriber.load_whisper_model
    transcriber.load_whisper_model = fake_load_whisper_model
    try:
        key1 = ("base", None, 4, 5)
        m1 = cache.get_whisper(key1)
        m2 = cache.get_whisper(key1)
        assert m1 is m2
        assert len(load_calls) == 1

        key2 = ("small", None, 4, 5)
        m3 = cache.get_whisper(key2)
        assert m3 is not m1
        assert len(load_calls) == 2
        assert m3.name == "small"
    finally:
        transcriber.load_whisper_model = original


def test_cache_retries_after_failed_load_without_corrupting_key():
    """Regression: a failed load must not leave _whisper_key pointing at a
    key whose model was already dropped — otherwise a later request for the
    OLD key would skip the reload branch and get back the stale None."""
    cache = transcriber.ModelCache()

    class FakeModel:
        def __init__(self, name):
            self.name = name

    def ok_loader(model_name, language=None, threads=4, beam_size=5):
        return FakeModel(model_name)

    def failing_loader(model_name, language=None, threads=4, beam_size=5):
        raise RuntimeError(f"failed to load {model_name!r}")

    original = transcriber.load_whisper_model
    try:
        key_a = ("base", None, 4, 5)
        key_b = ("small", None, 4, 5)

        transcriber.load_whisper_model = ok_loader
        model_a = cache.get_whisper(key_a)
        assert model_a.name == "base"

        transcriber.load_whisper_model = failing_loader
        with pytest.raises(RuntimeError):
            cache.get_whisper(key_b)

        transcriber.load_whisper_model = ok_loader
        model_a_again = cache.get_whisper(key_a)
        assert model_a_again is not None
        assert model_a_again.name == "base"
    finally:
        transcriber.load_whisper_model = original


def test_stage_progression_reported(roots, monkeypatch):
    audio_root, transcripts_root = roots
    source = audio_root / "x.mp3"
    source.write_bytes(b"audio")

    _patch_models(monkeypatch)

    def fake_transcribe_file(model, audio_path, output_dir, **kwargs):
        log_fn = kwargs["log_fn"]
        progress_fn = kwargs["progress_fn"]
        log_fn("  Loading audio: x.mp3")
        progress_fn(0)
        progress_fn(50)
        log_fn("  Aligning timestamps...")
        log_fn("  Diarizing speakers...")
        progress_fn(100)
        return str(Path(output_dir) / "x.mp3.txt")

    monkeypatch.setattr(transcriber, "transcribe_file", fake_transcribe_file)

    ctx = FakeContext()
    cache = transcriber.ModelCache()
    params = {"path": "x.mp3", "model": "base", "language": None, "diarize": False, "num_speakers": None}

    transcriber.run_transcribe(params, ctx, audio_root, transcripts_root, cache)

    stages = [call[1] for call in ctx.progress_calls]
    assert stages[0] == "loading_model"
    assert "transcribing" in stages
    assert stages.index("transcribing") > stages.index("loading_model")
    assert "aligning" in stages
    assert "diarizing" in stages
    assert stages.index("aligning") > stages.index("transcribing")
    assert stages.index("diarizing") > stages.index("aligning")
    assert "  Loading audio: x.mp3" in ctx.logs
    assert "  Aligning timestamps..." in ctx.logs
    assert "  Diarizing speakers..." in ctx.logs


def test_diarization_unavailable_logs_explicit_line(roots, monkeypatch):
    """When diarize was requested but the (fake) diarizer loader returns
    None, run_transcribe must emit an explicit job-log line so the failure
    is visible in the job's log instead of only on server stdout."""
    audio_root, transcripts_root = roots
    source = audio_root / "x.mp3"
    source.write_bytes(b"audio")

    monkeypatch.setenv("HF_TOKEN", "fake-token")
    _patch_models(monkeypatch, diarizer=None)

    def fake_transcribe_file(model, audio_path, output_dir, **kwargs):
        return str(Path(output_dir) / "x.mp3.txt")

    monkeypatch.setattr(transcriber, "transcribe_file", fake_transcribe_file)

    ctx = FakeContext()
    cache = transcriber.ModelCache()
    params = {"path": "x.mp3", "model": "base", "language": None, "diarize": True, "num_speakers": None}

    transcriber.run_transcribe(params, ctx, audio_root, transcripts_root, cache)

    assert "Diarization unavailable — continuing without speaker labels." in ctx.logs


def test_skip_existing_reported(roots, monkeypatch):
    audio_root, transcripts_root = roots
    source = audio_root / "x.mp3"
    source.write_bytes(b"audio")

    _patch_models(monkeypatch)
    monkeypatch.setattr(transcriber, "transcribe_file", lambda *a, **k: None)

    ctx = FakeContext()
    cache = transcriber.ModelCache()
    params = {"path": "x.mp3", "model": "base", "language": None, "diarize": False, "num_speakers": None}

    result = transcriber.run_transcribe(params, ctx, audio_root, transcripts_root, cache)

    assert result == {"skipped": True, "output_path": "x.mp3.txt"}
