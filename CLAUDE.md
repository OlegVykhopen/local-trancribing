# Local Audio Transcription with Speaker Diarization

## What this project does

Two ways to transcribe audio locally with WhisperX, with optional speaker diarization (who said what). Everything runs on-device — no cloud APIs, no costs.

1. **CLI**: `transcribe.py` — batch-transcribe audio files from the terminal.
2. **Transcribing Studio** (web app): FastAPI backend + React frontend on `127.0.0.1:8756` — download YouTube audio (yt-dlp), transcribe with a form instead of CLI flags, watch live progress over SSE, browse sources/transcripts by category.

## How transcription works

1. Audio files live in `audio_sources/` (optionally under one category subdirectory)
2. WhisperX transcribes using a local Whisper model; timestamps are aligned at the word level
3. If a HuggingFace token is provided (`HF_TOKEN` in `.env`), pyannote performs speaker diarization
4. Output is saved as timestamped text files in `transcripts/`, mirroring the source's relative path

Output format: `[HH:MM:SS - HH:MM:SS] SPEAKER_XX: transcribed text`

## Project structure

- `transcribe.py` — CLI tool; also imported by the web app for its model-loading/transcription functions
- `app/` — FastAPI backend: `main.py` (routes, SSE, static mount), `worker.py` (single worker thread + job queue, cooperative cancellation), `db.py` (SQLite job store, WAL), `events.py` (thread-safe event bus → SSE), `schemas.py` (Pydantic models incl. `JobStatus`/`JobResponse`), `services/` (downloader, transcriber with warm model cache, file browser)
- `frontend/` — React + TypeScript + Vite + Tailwind; `npm run build` produces `frontend/dist`, which the backend serves
- `tests/` — backend pytest suite; frontend tests are vitest (`frontend/src/**/*.test.*`)
- `run.sh` — launcher: sets `DYLD_LIBRARY_PATH`, starts uvicorn on port 8756, auto-opens the browser (`NO_BROWSER=1` to skip)
- `audio_sources/` / `transcripts/` — input/output roots (gitignored; created at app startup)
- `app.db` — SQLite job history (gitignored)
- `.env` / `.env.example` — HuggingFace token (`HF_TOKEN`) for speaker diarization
- `venv/` — Python 3.13 virtual environment
- `docs/APP_PLAN.md` — original design plan for the Studio (see its status note; some details superseded)

## Key technical details

- **Runtime**: Python 3.13, uses a local `venv/`
- **Device**: Runs on CPU with `int8` compute type (even on Apple Silicon Macs — WhisperX diarization works best on CPU)
- **Supported formats**: mp3, wav, m4a, flac, ogg, wma, aac, webm, mp4
- **Models**: Whisper model sizes from `tiny` to `large-v3` (default: `base`)
- **Dependencies**: whisperx, torch, pyannote (via whisperx), python-dotenv, fastapi, uvicorn, sse-starlette, yt-dlp, pydantic (see `requirements.txt`)
- **ffmpeg, two distinct roles**: torchcodec needs the ffmpeg@7 *libraries* (`DYLD_LIBRARY_PATH=/opt/homebrew/opt/ffmpeg@7/lib`, set by `run.sh` and `transcribe.py`); yt-dlp needs an ffmpeg *binary* (`/opt/homebrew/bin/ffmpeg`, set in `app/config.py`). Don't "unify" them.

## Usage

```bash
# Web app (build the frontend once first: cd frontend && npm install && npm run build)
./run.sh

# CLI: transcribe all files in audio_sources/
python transcribe.py

# CLI: specific files / larger model / pre-download models
python transcribe.py recording.mp3 interview.wav
python transcribe.py -m large-v3
python transcribe.py setup
```

## Tests

```bash
venv/bin/python -m pytest              # backend
cd frontend && npx vitest run          # frontend
cd frontend && npx tsc -b              # typecheck
```

## Development notes

- Existing transcripts are skipped (won't re-transcribe if output file exists); the job result carries `skipped: true` and the UI surfaces it
- Language is auto-detected unless specified (`-l` in the CLI, Language dropdown in the UI). The API normalizes codes to lowercase and rejects codes Whisper doesn't accept with 400 (list comes from `whisperx.utils.LANGUAGES`, exposed via `/api/meta`)
- A failed transcribe job shows a Retry button in the job view; it reopens the transcribe form prefilled from the job's params (file, model, language, diarization, speaker count); values no longer valid are dropped with a visible notice
- Speaker diarization is optional — works without `HF_TOKEN` but won't separate speakers; when requested but unavailable, the job result carries `diarized: false`
- Job statuses: `queued → running → done | error`, plus `cancelling → cancelled` (see `JobStatus` in `app/schemas.py`, mirrored in `frontend/src/lib/types.ts`)
- Jobs orphaned by a server restart are marked `error: "interrupted by restart"` on next startup
