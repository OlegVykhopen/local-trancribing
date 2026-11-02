import os
import threading
import types

import pytest

import transcribe


class FakeModel:
    """Stand-in for a loaded WhisperX model."""

    def __init__(self, segments=None, calls_progress_pct=None):
        self._segments = segments or [{"start": 0, "end": 1, "text": "hi"}]
        self._calls_progress_pct = calls_progress_pct

    def transcribe(self, audio, language=None, batch_size=16, num_workers=0, progress_callback=None):
        if progress_callback is not None and self._calls_progress_pct is not None:
            progress_callback(self._calls_progress_pct)
        return {"segments": self._segments, "language": "en"}


@pytest.fixture
def fakes(monkeypatch):
    def fake_load_audio(path):
        return [0.0] * 16000

    def fake_load_align_model(language_code, device):
        return ("align_model", "metadata")

    def fake_align(segments, align_model, metadata, audio, device, return_char_alignments=False):
        return {"segments": segments}

    monkeypatch.setattr(transcribe.whisperx, "load_audio", fake_load_audio)
    monkeypatch.setattr(transcribe.whisperx, "load_align_model", fake_load_align_model)
    monkeypatch.setattr(transcribe.whisperx, "align", fake_align)
    return types.SimpleNamespace(
        load_audio=fake_load_audio,
        load_align_model=fake_load_align_model,
        align=fake_align,
    )


def _make_audio_file(tmp_path, name="audio.mp3"):
    audio_path = tmp_path / name
    audio_path.write_bytes(b"fake-audio-bytes")
    return audio_path


def test_transcribe_file_returns_output_path(tmp_path, fakes):
    model = FakeModel()
    audio_path = _make_audio_file(tmp_path)

    result = transcribe.transcribe_file(
        model, str(audio_path), str(tmp_path), log_fn=lambda *a, **k: None
    )

    expected_path = os.path.join(str(tmp_path), "audio.mp3.txt")
    assert result == expected_path
    assert os.path.exists(expected_path)
    with open(expected_path, encoding="utf-8") as f:
        content = f.read()
    assert content == "[00:00:00 - 00:00:01] SPEAKER: hi"


def test_skip_existing_returns_none(tmp_path, fakes):
    model = FakeModel()
    audio_path = _make_audio_file(tmp_path)
    output_path = tmp_path / "audio.mp3.txt"
    output_path.write_text("existing transcript", encoding="utf-8")

    result = transcribe.transcribe_file(
        model, str(audio_path), str(tmp_path), log_fn=lambda *a, **k: None
    )

    assert result is None
    assert output_path.read_text(encoding="utf-8") == "existing transcript"


def test_skip_existing_false_overwrites(tmp_path, fakes):
    model = FakeModel()
    audio_path = _make_audio_file(tmp_path)
    output_path = tmp_path / "audio.mp3.txt"
    output_path.write_text("existing transcript", encoding="utf-8")

    result = transcribe.transcribe_file(
        model, str(audio_path), str(tmp_path),
        skip_existing=False, log_fn=lambda *a, **k: None,
    )

    assert result == str(output_path)
    assert output_path.read_text(encoding="utf-8") == "[00:00:00 - 00:00:01] SPEAKER: hi"


def test_progress_fn_receives_percent(tmp_path, fakes):
    model = FakeModel(calls_progress_pct=50.0)
    audio_path = _make_audio_file(tmp_path)
    received = []

    transcribe.transcribe_file(
        model, str(audio_path), str(tmp_path),
        progress_fn=received.append,
        log_fn=lambda *a, **k: None,
    )

    assert received == [50.0]


def test_cancel_event_raises_jobcancelled_before_align(tmp_path, fakes):
    cancel_event = threading.Event()

    class CancellingModel:
        def transcribe(self, audio, language=None, batch_size=16, num_workers=0, progress_callback=None):
            # Simulate cancellation arriving while transcription was running,
            # discovered only once transcribe() returns.
            cancel_event.set()
            return {"segments": [{"start": 0, "end": 1, "text": "hi"}], "language": "en"}

    audio_path = _make_audio_file(tmp_path)

    with pytest.raises(transcribe.JobCancelled):
        transcribe.transcribe_file(
            CancellingModel(), str(audio_path), str(tmp_path),
            cancel_event=cancel_event,
            log_fn=lambda *a, **k: None,
        )


def test_load_whisper_model_raises_not_exits(monkeypatch):
    def fake_load_model(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(transcribe.whisperx, "load_model", fake_load_model)

    with pytest.raises(RuntimeError, match=r"Failed to load WhisperX model 'tiny': boom"):
        transcribe.load_whisper_model("tiny")
