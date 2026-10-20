# Transcribing Studio — local web app for YouTube download + transcription flows

## Context

Today two flows run via terminal: (1) downloading YouTube media with the yt-dlp CLI (no script exists — `youtube_downloader/` is a cookbook + downloaded files), and (2) transcribing audio via `transcribe.py` (WhisperX + pyannote diarization). The flows are disconnected — downloads are manually copied/renamed into `audio_sources/<category>/`. Goal: a local app with UI — modules in a left panel, per-module history, parameterized job launch, live progress, and a file browser marking which sources already have transcripts.

## Vision & Mission

**Vision:** one local web app where all audio work happens without a terminal: paste a YouTube URL or pick local files, set options in a form instead of CLI flags, watch live progress, browse every source and transcript by category. Everything on-device — no cloud, no cost.

**Mission (v1):** replace the two terminal workflows with three UI flows — Download, Transcribe, combined URL→Transcript — with durable job history, safe cancellation, a sequential queue, and an in-app transcript viewer.

## Confirmed decisions (user-approved 2026-09-17)

| # | Decision | Choice |
|---|----------|--------|
| 1 | App shape | Local web app: FastAPI backend + vanilla-JS browser UI on `127.0.0.1:8756` |
| 2 | Pipeline | Combined URL→download→auto-transcribe flow included, plus two standalone modules |
| 3 | History | SQLite (`app.db`): params, status, timings, result paths, errors |
| 4 | V1 scope | Transcript viewer, first-class category folders, cancel running job, sequential job queue |

## Architecture

### Project layout (new `app/` package; CLI untouched in behavior)

```
transcribe.py            # existing CLI, minimal refactor (below)
run.sh                   # launcher: venv python + DYLD_LIBRARY_PATH + uvicorn, auto-opens browser
requirements.txt         # NEW: fastapi, uvicorn[standard], yt-dlp, sse-starlette + existing pins
docs/PRD.md              # NEW: product requirements doc (vision, decisions, this spec)
app/
├── main.py              # FastAPI app, routes, SSE endpoint, static mount
├── config.py            # paths, port, constants
├── db.py                # sqlite3, WAL, schema init, job CRUD
├── schemas.py           # Pydantic request/response models
├── events.py            # thread-safe EventBus: worker thread → asyncio SSE subscribers
├── worker.py            # single daemon worker thread, queue, warm model cache, cancellation
├── services/
│   ├── downloader.py    # yt_dlp.YoutubeDL wrapper, progress_hooks, cancel, .part cleanup
│   ├── transcriber.py   # imports transcribe.py functions; model cache; progress/cancel glue
│   └── files.py         # file browser, transcribed-status, categories, transcript reader
└── static/              # index.html + app.js (~600 lines, hash router) + styles.css
```

Frontend is no-build vanilla JS: single user, 4 views (`#download`, `#transcribe`, `#files`, `#job/<id>`), `fetch()` + `EventSource` — no node toolchain.

### Worker & cancellation

- **One daemon worker thread inside the uvicorn process.** ctranslate2/torch release the GIL, so API + SSE stay responsive. Sequential queue = one thread. `run.sh` uses `venv/bin/python`, so the `transcribe.py:10-18` os.execv re-exec guard is a no-op on import.
- Warm caches owned by the worker thread: single-entry whisper model cache (evict + gc on model change), diarization pipeline loaded once, `align_cache` dict as in CLI. Lazy load on first job.
- Crash recovery: on startup, jobs left `queued`/`running` → `error: interrupted by restart`.
- Cancellation is cooperative via per-job `threading.Event`: yt-dlp `progress_hooks` and whisperx `progress_callback` raise `JobCancelled`; phase-boundary checks after transcribe/before align/before diarize. Known limitation: no hook inside align/diarize → status `cancelling` until phase ends. State machine: `queued → running → done|error|cancelled`, plus `running → cancelling → cancelled`.

### transcribe.py refactor (minimal diff, CLI regression-free)

- Extract from `main()` (lines 283–325): `load_whisper_model(...)` and `load_diarization_model(hf_token, log_fn)` (MPS→CPU fallback logic); raise instead of `sys.exit`, `main()` catches and exits.
- Extend `transcribe_file(...)` with optional `progress_fn=None` (passed as `progress_callback=` to `model.transcribe` — confirm exact signature in `venv/.../whisperx/asr.py` first), `cancel_event=None`, `skip_existing=True`; return `output_path` (None on skip).
- `JobCancelled` exception class lives in transcribe.py.

### SQLite schema

`jobs`: id, kind (`download|transcribe|pipeline`), status, params_json, category, parent_job_id, progress (0–100), stage (`downloading|loading_model|transcribing|aligning|diarizing`), result_json, error, created/started/finished_at. `job_logs`: job_id, ts, line (every `log_fn` line — powers job detail view). Pipeline job = parent row; worker spawns child `download` then child `transcribe` rows with `parent_job_id` — per-module history for free.

### API surface

- Files: `GET /api/files` (tree with `transcribed` flags), `GET/POST /api/categories`, `GET /api/transcript?path=` (realpath-validated under `transcripts/`).
- Jobs: `POST /api/jobs/{download|transcribe|pipeline}`, `GET /api/jobs?kind=`, `GET /api/jobs/{id}` (+children), `GET /api/jobs/{id}/logs`, `POST /api/jobs/{id}/cancel`, `GET /api/queue`, `GET /api/meta` (models list, hf_token_present, defaults).
- Live: `GET /api/events` — single global SSE channel (EventSource auto-reconnects; WS not needed for one-directional). Events: `job_status`, `job_progress` ({job_id, stage, percent, detail}), `job_log`, `queue`. EventBus: bounded asyncio queues, `call_soon_threadsafe`, drop-oldest so a stalled browser can't block the worker.

### Progress sources

- yt-dlp: `progress_hooks` → bytes/total → % + speed/ETA; postprocess stage shown indeterminate.
- whisperx: `progress_callback` gives batch-level % for transcription; align/diarize are stage-change events with indeterminate bars.
- DB progress writes throttled (≥1s or ≥2%); SSE gets every update.

### Files & categories

- Category = subdirectory (one level) of `audio_sources/`, mirrored in `transcripts/`. V1: list + create only.
- Transcribed check: `transcripts/<relative dir>/<basename + ".txt">` exists (keeps audio extension: `x.m4a.txt`). Stat-walk per request, no caching.
- Transcribe output dir always mirrors the source file's relative path — selecting `audio_sources/therapy/x.m4a` writes `transcripts/therapy/x.m4a.txt`.
- Download jobs write to `audio_sources/<cat>/` via yt-dlp `outtmpl`. Pass `ffmpeg_location=/opt/homebrew/bin/ffmpeg` explicitly.
- All browser-supplied paths realpath-validated under the two roots. Cyrillic filenames safe: Python API only, no shell strings.

### Startup

`run.sh`: `cd` to repo, `export DYLD_LIBRARY_PATH=/opt/homebrew/opt/ffmpeg@7/lib`, `exec venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8756`. No `--reload` (would drop warm models mid-job). Startup handler opens the browser unless `NO_BROWSER=1`.

## Implementation steps

0. **PRD**: write `docs/PRD.md` from this plan (vision, decisions, spec) — the artifact the user asked for.
1. **M1 — skeleton + file browser**: `app/` package, db init, static shell, files/categories/transcript APIs, `run.sh`, `requirements.txt`, `pip install fastapi uvicorn[standard] yt-dlp sse-starlette` into venv. Gitignore `app.db`.
2. **M2 — queue + SSE + Download module**: `worker.py`, `events.py`, `services/downloader.py`, download form/history/progress/cancel UI.
3. **M3 — Transcribe module**: transcribe.py refactor, `services/transcriber.py` warm cache, transcribe form + log view.
4. **M4 — Pipeline + polish**: parent/child pipeline jobs, combined form, queue panel, category-creation UI, cancelling-state UX, error surfacing.

## Verification

- **M1**: `./run.sh` opens browser; badges match reality (spot-check `transcripts/therapy/`); Cyrillic transcript opens in viewer; `curl /api/files | jq` sane.
- **M2**: short YouTube URL → live % → file lands in `audio_sources/<cat>/`; cancel mid-download → `cancelled`, no `.part` litter; history survives restart (interrupted marking); Cyrillic-titled video OK.
- **M3**: CLI regression — `python3 transcribe.py -m tiny <short file>` identical to pre-refactor; web job with `tiny` shows % and produces same-format transcript in mirrored dir; second same-model job starts instantly (warm cache); cancel lands within seconds; skip-existing reported.
- **M4**: URL + auto-transcribe end-to-end: download stage hands off to transcribe, transcript opens from success toast; history shows pipeline parent + two children; cancel behaves per state machine in each stage.

## Risks

- Diarization cancel latency (no pyannote hook) — mitigated by `cancelling` status + UI note.
- RAM: one warm whisper model + diarization pipeline — single-entry cache with eviction is deliberate.
- Confirm whisperx 3.8.5 `progress_callback` signature before wiring (first task of M3).
