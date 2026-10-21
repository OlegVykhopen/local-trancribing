"""Transcription service with a warm, process-wide model cache.

Wraps transcribe.py's load_whisper_model / load_diarization_model /
transcribe_file for use by the job worker. Loading a Whisper (or
diarization) model is expensive (seconds to tens of seconds), so this
module keeps a warm ModelCache across jobs instead of reloading per job.

The three transcribe.py functions are imported by name (rather than
accessed as `transcribe.load_whisper_model` etc.) so tests can
monkeypatch `transcriber.load_whisper_model` and friends without ever
loading a real model.
"""

import gc
import os
from pathlib import Path

from transcribe import (
    JobCancelled,  # noqa: F401 - re-exported for callers that only import this module
    load_diarization_model,
    load_whisper_model,
    transcribe_file,
)

# transcribe.py's CLI argparse defaults for these knobs aren't exported as
# module constants, so they're duplicated here.
DEFAULT_THREADS = 4
DEFAULT_BEAM_SIZE = 5
DEFAULT_BATCH_SIZE = 16

# transcribe_file() has no stage-progress hooks for alignment/diarization —
# it only logs these exact strings via log_fn. Matching on them to emit
# ctx.progress(0, "aligning"/"diarizing") is a brittle string coupling to
# transcribe.py's log lines; if those literals change there, this silently
# stops reporting the stage (tests would still pass since they don't probe
# transcribe.py itself).
_ALIGNING_LOG_LINE = "  Aligning timestamps..."
_DIARIZING_LOG_LINE = "  Diarizing speakers..."


class ModelCache:
    """Process-wide warm cache for the whisper model, diarizer, and align models.

    - Whisper: single entry, keyed by (model_name, language, threads, beam_size).
      When the key changes, the old model reference is dropped and gc.collect()
      is run before loading the new one, to free the old model's memory before
      the new (also large) model is loaded.
    - Diarizer: keyed by hf_token, loaded once and cached forever *on success*.
      A failed load (None) is deliberately NOT cached, so the next job that
      requests diarization retries the load — e.g. after the user fixes an
      invalid HF_TOKEN or accepts the pyannote model terms, without needing to
      restart the server.
    - align_cache: a plain dict handed straight through to transcribe_file's
      align_cache param. transcribe_file manages its own language-keyed reuse
      inside that dict; this class just keeps one instance alive across jobs.
    """

    def __init__(self):
        self._whisper_key = None
        self._whisper_model = None
        self._diarizers: dict[str, object] = {}
        self.align_cache: dict = {}

    def get_whisper(self, key):
        if key != self._whisper_key:
            # Invalidate the key together with the model *before* attempting
            # the load: if load_whisper_model raises, _whisper_key must not
            # keep pointing at the old (now-dropped) model, or a later call
            # for that old key would skip the reload branch and return the
            # None left behind below.
            self._whisper_model = None
            self._whisper_key = None
            gc.collect()
            model_name, language, threads, beam_size = key
            self._whisper_model = load_whisper_model(
                model_name, language=language, threads=threads, beam_size=beam_size
            )
            self._whisper_key = key
        return self._whisper_model

    def get_diarizer(self, hf_token, log_fn=print):
        model = self._diarizers.get(hf_token)
        if model is not None:
            return model
        model = load_diarization_model(hf_token, log_fn=log_fn)
        if model is not None:
            self._diarizers[hf_token] = model
        return model


def run_transcribe(params: dict, ctx, audio_root: Path, transcripts_root: Path, cache: "ModelCache") -> dict:
    """Transcribe one audio file, reporting stage progress through ctx.

    params: {"path": rel source path under audio_root, "model": str,
             "language": str | None, "diarize": bool, "num_speakers": int | None}.

    Raises RuntimeError if params["path"] doesn't resolve to an existing file
    under audio_root (missing file, or a path that escapes the root).
    Propagates JobCancelled if ctx.cancel_event is set mid-transcription.

    Returns {"output_path": rel_path}, plus "skipped": True when
    transcribe_file skipped an already-existing transcript, plus
    "diarized": bool when diarization was requested (False means the request
    was downgraded because no diarizer was available).
    """
    rel_path = params["path"]
    audio_root = Path(audio_root).resolve()
    source = (audio_root / rel_path).resolve()
    if not source.is_relative_to(audio_root) or not source.is_file():
        raise RuntimeError(f"source file not found: {rel_path}")
    # Derive the output location from the *resolved* source, not the raw
    # rel_path: a param like "../x/audio_sources/a.mp3" can pass the source
    # check above while `transcripts_root / rel_dir` would escape the root.
    rel_dir = source.relative_to(audio_root).parent

    model_name = params.get("model") or "base"
    language = params.get("language")
    diarize = bool(params.get("diarize"))
    num_speakers = params.get("num_speakers")

    output_dir = transcripts_root / rel_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    ctx.progress(0, "loading_model")
    whisper_key = (model_name, language, DEFAULT_THREADS, DEFAULT_BEAM_SIZE)
    model = cache.get_whisper(whisper_key)

    hf_token = os.environ.get("HF_TOKEN")
    diarize_model = None
    if diarize and hf_token:
        diarize_model = cache.get_diarizer(hf_token, log_fn=ctx.log)
    elif diarize:
        ctx.log("Diarization requested but HF_TOKEN is not set on the server.")
    if diarize and diarize_model is None:
        ctx.log("Diarization unavailable — continuing without speaker labels.")

    def progress_fn(pct):
        ctx.progress(pct, "transcribing")

    def log_fn(line):
        ctx.log(line)
        if line == _ALIGNING_LOG_LINE:
            ctx.progress(0, "aligning")
        elif line == _DIARIZING_LOG_LINE:
            ctx.progress(0, "diarizing")

    output_path = transcribe_file(
        model,
        str(source),
        str(output_dir),
        language=language,
        hf_token=hf_token,
        diarize_model=diarize_model,
        align_cache=cache.align_cache,
        batch_size=DEFAULT_BATCH_SIZE,
        num_speakers=num_speakers,
        log_fn=log_fn,
        progress_fn=progress_fn,
        cancel_event=ctx.cancel_event,
    )

    rel_output = (rel_dir / (source.name + ".txt")).as_posix()
    result: dict = {"output_path": rel_output}
    if diarize:
        # Record whether the explicit diarization request was honored, so the
        # UI can distinguish "done with speakers" from "silently downgraded".
        result["diarized"] = diarize_model is not None
    if output_path is None:
        result["skipped"] = True
    return result
