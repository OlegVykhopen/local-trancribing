# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

A CLI tool that transcribes audio files locally using WhisperX, with optional speaker diarization via pyannote. Everything runs on-device; no cloud APIs. `README.md` has the full user-facing option table.

## Setup and commands

There is no build step, test suite, linter, or `requirements.txt`. Dependencies are installed by hand into a local (gitignored) `venv/`:

```bash
python3 -m venv venv && source venv/bin/activate
pip install whisperx python-dotenv     # torch and pyannote come in via whisperx
cp .env.example .env                   # then set HF_TOKEN to enable diarization
```

Running it:

```bash
python transcribe.py                          # all supported files in audio_sources/
python transcribe.py a.mp3 b.wav              # specific files
python transcribe.py -m large-v3 -l en --num-speakers 2 interview.mp3
python transcribe.py --fast recording.mp3     # auto-tuned thread count
python transcribe.py setup [-m large-v3]      # pre-download models for offline use
```

To verify a change, run it on a short audio clip with `-m tiny` (fastest model). Delete the matching file in `transcripts/` first, because existing transcripts are skipped.

Requires ffmpeg; on macOS, ffmpeg@7 (`brew install ffmpeg@7`). At import time the script sets `DYLD_LIBRARY_PATH` to `/opt/homebrew/opt/ffmpeg@7/lib` if that directory exists.

## Architecture

All logic is in `transcribe.py`:

- **`main()`**: parses args, validates them, loads the models once, then loops over the files. Each file's failure is caught and listed at the end, so one bad file doesn't stop the batch.
- **`transcribe_file()`**: the per-file pipeline: `whisperx.load_audio` (16 kHz) → `model.transcribe` → `whisperx.align` (word-level timestamps) → optional diarization + `assign_word_speakers` → write the output.
- **`setup_models()`**: downloads the models only (`setup` subcommand).

Non-obvious points:

- **Subcommand dispatch is hand-rolled.** If `argv[1]` is `setup` or `transcribe`, the full parser runs. Otherwise the `transcribe` subparser parses `argv` directly, which makes `transcribe` the default command. New transcription flags belong on `transcribe_parser`, not on the top-level `parser`.
- **Devices:** Whisper always runs on CPU with `int8` (ctranslate2 has no MPS support). Diarization tries `mps` when it is available and falls back to CPU if loading fails. If diarization can't load at all, the batch continues without speakers. `setup` downloads the diarization model on CPU. (The README says everything runs on CPU, but the code prefers MPS for diarization.)
- **Model reuse:** the Whisper and diarization models are loaded once per run. Alignment models are loaded lazily and cached in `align_cache`, keyed by the detected language, so the cache is reused only while consecutive files share a language.
- **Threads:** `--threads` goes to ctranslate2 through `load_model(threads=...)` and also sets `OMP/MKL/OPENBLAS_NUM_THREADS`. The PyTorch thread count is left at its default on purpose: limiting it slows down alignment and diarization. `--fast` sets threads to `cpu_count - 2`.
- **`num_workers` must stay 0 in practice.** WhisperX's DataLoader generator can't be pickled, so `FAST_NUM_WORKERS` is hard-coded to 0. The README's claim that `--fast` enables "prefetch workers" is out of date.
- **Speaker flags:** `--num-speakers` overrides `--min/--max-speakers`, which are reset to `None` with a warning.

## Output

Each input file produces `<output_dir>/<input basename>.txt`. The original extension is kept, so `talk.mp3` becomes `transcripts/talk.mp3.txt`. Each segment is one line:

```
[HH:MM:SS - HH:MM:SS] SPEAKER_XX: text
```

Without diarization, the speaker label is the literal string `SPEAKER`. Supported input extensions are listed in `SUPPORTED_EXTENSIONS`. `audio_sources/` and `transcripts/` sit next to the script and are gitignored.
