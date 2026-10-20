# Transcribing Studio MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Local web app (FastAPI backend + React frontend) replacing the two terminal workflows: YouTube download and WhisperX transcription, with durable job history, live animated progress, and cancellation.

**Architecture:** Single uvicorn process on `127.0.0.1:8756` with one daemon worker thread running a sequential job queue. SQLite (`app.db`) stores jobs and logs; a thread-safe EventBus bridges the worker thread to asyncio SSE subscribers. The frontend is a React SPA in `frontend/`, built by Vite into `frontend/dist` and served as static files by FastAPI; during development Vite's dev server proxies `/api` to uvicorn. The existing `transcribe.py` CLI is minimally refactored (extracted loaders, progress/cancel hooks) and must remain regression-free.

**Tech Stack:** Python 3.13 (existing `venv/`), FastAPI, uvicorn, sse-starlette, yt-dlp, sqlite3 (stdlib), pytest + httpx. Frontend: React 18 + TypeScript, Vite, Tailwind CSS, shadcn/ui components, `motion` (Framer Motion's successor) for animations, `react-router-dom` (HashRouter), vitest + @testing-library/react.

**Spec:** `docs/APP_PLAN.md` — amended by two approved decisions: (1) MVP carve (2026-10-20): milestones **M1–M3 only**; combined URL→Transcript pipeline, queue panel, and cancelling-UX polish deferred to MVP+1; SQLite schema keeps `parent_job_id` and kind `pipeline` now. (2) Frontend decision (2026-10-21): the spec's "no-build vanilla JS" is **superseded** — user chose React + Vite + Tailwind + Motion for an animated, buildable UI.

## Global Constraints

- Python from `venv/bin/python` only; run backend tests as `venv/bin/python -m pytest` (the `transcribe.py:10-13` re-exec guard is then a no-op).
- Server binds `127.0.0.1:8756`. No `--reload`.
- Frontend lives in `frontend/` (Vite + React + TS). Production: `npm run build` → `frontend/dist`, served by FastAPI at `/`. Development: `npm run dev` (Vite on 5173, proxying `/api` and `/api/events` to 8756). Node ≥ 20 required. Frontend tests: `npm test` (vitest).
- `transcribe.py` CLI behavior must not change: `--help` output, transcript format `[HH:MM:SS - HH:MM:SS] SPEAKER_XX: text` unchanged, skip-existing behavior, exit codes.
- yt-dlp jobs pass `ffmpeg_location="/opt/homebrew/bin/ffmpeg"`; server launch exports `DYLD_LIBRARY_PATH=/opt/homebrew/opt/ffmpeg@7/lib`.
- Whisper models: `tiny|base|small|medium|large|large-v3`, default `base`.
- whisperx progress hook (verified in `venv/.../whisperx/asr.py:208`): `model.transcribe(..., progress_callback=fn)` where `fn(percent: float)` with percent in 0–100.
- All browser-supplied paths realpath-validated under `audio_sources/` or `transcripts/`.
- Reality check (2026-10-20): category dirs are **nested** (e.g. `transcripts/consulting/marketing/`) and loose audio files exist at `audio_sources/` root. The file tree is recursive to any depth; the download form's category picker lists **top-level** dirs only; the transcribed check mirrors the **full relative path**.
- Job state machine: `queued → running → done|error|cancelled`, plus `running → cancelling → cancelled`. Startup marks leftover `queued|running|cancelling` jobs as `error` ("interrupted by restart").
- Animation rules: animate presence/position of job cards and progress bars with `motion` (spring defaults); respect `prefers-reduced-motion`; never block interaction on an animation.

## Review Focus

1. **Garbage URL in the download form** (not a URL, or a page yt-dlp can't handle) → job must end `error` with the yt-dlp message in logs, never stuck `running`. — test in Task 8.
2. **Path traversal** `GET /api/transcript?path=../../.env` → 400/404, never file contents outside `transcripts/`. — test in Task 3.
3. **Cancel of a finished/already-cancelled job, or double cancel** → idempotent no-op response, no crash, status unchanged. — test in Task 7.
4. **Source file deleted between queueing and worker pickup** → transcribe job ends `error` with a readable message. — test in Task 11.
5. **Stalled/disconnected SSE browser** → worker never blocks; bounded queue drops oldest events. — test in Task 6.

---

### Task 1: Dependencies, package skeleton, config

**Files:**
- Create: `requirements.txt`, `app/__init__.py`, `app/config.py`, `tests/__init__.py`, `tests/test_config.py`, `run.sh`
- Modify: `.gitignore` (create if absent)

**Interfaces:**
- Produces: `app.config` constants: `BASE_DIR: Path` (repo root), `AUDIO_ROOT: Path` (`BASE_DIR/"audio_sources"`), `TRANSCRIPTS_ROOT: Path`, `DB_PATH: Path` (`BASE_DIR/"app.db"`), `FRONTEND_DIST: Path` (`BASE_DIR/"frontend"/"dist"`), `PORT = 8756`, `HOST = "127.0.0.1"`, `FFMPEG_LOCATION = "/opt/homebrew/bin/ffmpeg"`, `WHISPER_MODELS = ["tiny","base","small","medium","large","large-v3"]`.

- [ ] **Step 1: Write `requirements.txt`** — lines: `fastapi`, `uvicorn[standard]`, `sse-starlette`, `yt-dlp`, `pytest`, `httpx` (existing heavy pins — whisperx, torch — stay implicit in the venv; do not re-pin them here).

- [ ] **Step 2: Install into venv**

Run: `venv/bin/pip install -r requirements.txt`
Expected: success; `venv/bin/python -c "import fastapi, yt_dlp, sse_starlette, httpx"` exits 0. Also verify `node --version` ≥ 20 (needed from Task 5).

- [ ] **Step 3: Write the failing test**

```python
# tests/test_config.py
from app import config

def test_paths_and_constants():
    assert config.AUDIO_ROOT.name == "audio_sources"
    assert config.TRANSCRIPTS_ROOT.name == "transcripts"
    assert config.FRONTEND_DIST.parts[-2:] == ("frontend", "dist")
    assert config.PORT == 8756
    assert "base" in config.WHISPER_MODELS
```

- [ ] **Step 4: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL (ModuleNotFoundError: app)

- [ ] **Step 5: Implement `app/__init__.py` (empty) and `app/config.py` with the constants above; write `run.sh`; gitignore `app.db*`, `__pycache__/`, `frontend/node_modules/`, `frontend/dist/`**

`run.sh` content (exact):
```bash
#!/bin/bash
cd "$(dirname "$0")"
export DYLD_LIBRARY_PATH=/opt/homebrew/opt/ffmpeg@7/lib
if [ ! -d frontend/dist ]; then echo "WARNING: frontend/dist missing — run: cd frontend && npm run build"; fi
if [ -z "$NO_BROWSER" ]; then (sleep 1.5 && open "http://127.0.0.1:8756") & fi
exec venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8756
```
`chmod +x run.sh`.

- [ ] **Step 6: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add requirements.txt app/__init__.py app/config.py run.sh .gitignore tests/
git commit -m "feat: app skeleton, config, dependencies"
```

---

### Task 2: SQLite layer (`app/db.py`)

**Files:**
- Create: `app/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces (all take `conn: sqlite3.Connection` first; rows returned as plain `dict`):
  - `connect(db_path: str | Path) -> sqlite3.Connection` — WAL mode, `row_factory` dict-like, creates schema if missing; callers open per-thread connections.
  - `create_job(conn, kind: str, params: dict, category: str | None = None, parent_job_id: int | None = None) -> int`
  - `get_job(conn, job_id: int) -> dict | None` — `params` and `result` JSON-decoded.
  - `list_jobs(conn, kind: str | None = None, limit: int = 100) -> list[dict]` — newest first.
  - `set_status(conn, job_id: int, status: str, error: str | None = None, result: dict | None = None) -> None` — stamps `started_at` on `running`, `finished_at` on terminal states.
  - `set_progress(conn, job_id: int, progress: int, stage: str) -> None`
  - `append_log(conn, job_id: int, line: str) -> None`
  - `get_logs(conn, job_id: int) -> list[dict]` — `[{ts, line}]` in insert order.
  - `mark_interrupted(conn) -> int` — flips `queued|running|cancelling` → `error` with error `"interrupted by restart"`, returns count.
- Schema: `jobs(id INTEGER PK, kind TEXT CHECK(kind IN ('download','transcribe','pipeline')), status TEXT, params_json TEXT, category TEXT, parent_job_id INTEGER, progress INTEGER DEFAULT 0, stage TEXT, result_json TEXT, error TEXT, created_at TEXT, started_at TEXT, finished_at TEXT)`; `job_logs(id INTEGER PK, job_id INTEGER, ts TEXT, line TEXT)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_db.py  (fixture: conn = db.connect(tmp_path / "t.db"))
def test_create_and_get_roundtrip(conn):
    jid = db.create_job(conn, "download", {"url": "x"}, category="podcast")
    job = db.get_job(conn, jid)
    assert job["status"] == "queued" and job["params"] == {"url": "x"}

def test_pipeline_kind_and_parent_accepted(conn):
    pid = db.create_job(conn, "pipeline", {})
    cid = db.create_job(conn, "download", {}, parent_job_id=pid)
    assert db.get_job(conn, cid)["parent_job_id"] == pid

def test_status_timestamps(conn):
    jid = db.create_job(conn, "transcribe", {})
    db.set_status(conn, jid, "running"); db.set_status(conn, jid, "done", result={"output": "a.txt"})
    job = db.get_job(conn, jid)
    assert job["started_at"] and job["finished_at"] and job["result"] == {"output": "a.txt"}

def test_mark_interrupted(conn):
    a = db.create_job(conn, "download", {}); db.set_status(conn, a, "running")
    assert db.mark_interrupted(conn) == 1
    assert db.get_job(conn, a)["error"] == "interrupted by restart"

def test_logs_ordered(conn): ...  # append two lines, get_logs returns both in order
def test_list_jobs_filters_by_kind_newest_first(conn): ...
```

- [ ] **Step 2: Run tests to verify they fail** — `venv/bin/python -m pytest tests/test_db.py -v` → FAIL (no module `app.db`)

- [ ] **Step 3: Implement `app/db.py`** per the Interfaces block. One decision made here: timestamps are `datetime.now().isoformat()` strings; JSON columns stored with `json.dumps`, decoded in `get_job`/`list_jobs`.

- [ ] **Step 4: Run tests** — expected: PASS

- [ ] **Step 5: Commit** — `git commit -m "feat: sqlite job store with pipeline-ready schema"`

---

### Task 3: File services (`app/services/files.py`)

**Files:**
- Create: `app/services/__init__.py`, `app/services/files.py`
- Test: `tests/test_files.py`

**Interfaces:**
- Produces:
  - `list_tree(audio_root: Path, transcripts_root: Path) -> list[dict]` — recursive; dir node `{"name", "path" (rel, POSIX), "type": "dir", "children": [...]}`; file node `{"name", "path", "type": "file", "transcribed": bool}` where transcribed ⇔ `transcripts_root / rel_dir / (filename + ".txt")` exists. Only `SUPPORTED_EXTENSIONS` files (import the set from `transcribe.py`). Sorted dirs-first, then by name.
  - `list_categories(audio_root: Path) -> list[str]` — top-level directory names, sorted.
  - `create_category(audio_root: Path, transcripts_root: Path, name: str) -> None` — `ValueError` unless `name` matches `^[\w\- ]{1,64}$` (unicode `\w` — Cyrillic ok); mkdir in both roots.
  - `read_transcript(transcripts_root: Path, rel_path: str) -> str` — `ValueError` if realpath escapes `transcripts_root` or file missing.

- [ ] **Step 1: Write the failing tests** — build a tmp tree in a fixture: `audio/therapy/a.m4a`, `audio/consulting/marketing/b.mp3`, loose `audio/c.mp3`; transcripts for `a.m4a` and `b.mp3` only.

```python
def test_tree_transcribed_flags_nested_and_root(roots): ...
    # a.m4a transcribed=True, b.mp3 (nested 2 levels) True, c.mp3 False
def test_tree_ignores_unsupported_extensions(roots): ...
def test_list_categories_top_level_only(roots):  # ["consulting", "therapy"]
def test_create_category_valid_and_invalid(roots):
    files.create_category(a, t, "podcast")      # both dirs exist after
    with pytest.raises(ValueError): files.create_category(a, t, "../evil")
def test_read_transcript_blocks_traversal(roots):
    with pytest.raises(ValueError): files.read_transcript(t, "../.env")
def test_read_transcript_cyrillic_filename(roots): ...
```

- [ ] **Step 2: Run to verify FAIL**, **Step 3: Implement**, **Step 4: Run to PASS** — `venv/bin/python -m pytest tests/test_files.py -v`

- [ ] **Step 5: Commit** — `git commit -m "feat: file tree, categories, transcript reader with path validation"`

---

### Task 4: FastAPI app + read-only API (M1 backend)

**Files:**
- Create: `app/main.py`, `app/schemas.py`
- Test: `tests/test_api_files.py`

**Interfaces:**
- Consumes: Task 2 `db.connect/mark_interrupted`, Task 3 all functions.
- Produces:
  - `app/main.py` exposes module-level `app = FastAPI()` plus `create_app(audio_root, transcripts_root, db_path, frontend_dist=None) -> FastAPI` used by tests (the module-level app calls it with `config` values).
  - Routes: `GET /api/files` → `{"tree": [...]}`; `GET /api/categories` → `{"categories": [...]}`; `POST /api/categories {name}` → 201/400; `GET /api/transcript?path=` → `{"path", "content"}` or 400; `GET /api/meta` → `{"models": config.WHISPER_MODELS, "default_model": "base", "hf_token_present": bool}`.
  - If `frontend_dist` exists: mount it at `/` (`StaticFiles(html=True)`) — HashRouter needs no SPA fallback beyond `/`.
  - Startup handler: `db.mark_interrupted` (worker start added in Task 7).

- [ ] **Step 1: Write the failing tests** (httpx/`fastapi.testclient.TestClient` against `create_app` with tmp roots)

```python
def test_files_endpoint_shape(client): ...        # tree node has transcribed flag
def test_transcript_traversal_rejected(client):
    assert client.get("/api/transcript", params={"path": "../.env"}).status_code == 400
def test_create_category(client): ...             # POST then GET lists it
def test_meta_lists_models(client): ...
```

- [ ] **Step 2: Run to FAIL**, **Step 3: Implement** `schemas.py` (Pydantic models for the above payloads) and `main.py`. **Step 4: Run to PASS** — `venv/bin/python -m pytest tests/test_api_files.py -v`

- [ ] **Step 5: Commit** — `git commit -m "feat: FastAPI app with files, categories, transcript, meta routes"`

---

### Task 5: Frontend scaffold + Files view (M1 complete)

**Files:**
- Create: `frontend/` via Vite scaffold (`package.json`, `vite.config.ts`, `tsconfig.json`, Tailwind config, `index.html`, `src/main.tsx`, `src/App.tsx`), `src/lib/api.ts`, `src/lib/types.ts`, `src/views/FilesView.tsx`, `src/components/FileTree.tsx`, `src/components/TranscriptViewer.tsx`, `src/components/Layout.tsx` (left nav)
- Test: `frontend/src/lib/api.test.ts`, `frontend/src/components/FileTree.test.tsx`

**Interfaces:**
- Consumes: Task 4 routes.
- Produces (later tasks build on these):
  - `src/lib/types.ts`: `TreeNode { name: string; path: string; type: "dir"|"file"; transcribed?: boolean; children?: TreeNode[] }`, `Job { id: number; kind: "download"|"transcribe"|"pipeline"; status: string; params: Record<string, unknown>; category: string|null; progress: number; stage: string|null; result: Record<string, unknown>|null; error: string|null; created_at: string; started_at: string|null; finished_at: string|null }`, `AppEvent { type: "job_status"|"job_progress"|"job_log"|"queue"; [k: string]: unknown }`.
  - `src/lib/api.ts`: `getFiles(): Promise<TreeNode[]>`, `getCategories(): Promise<string[]>`, `createCategory(name: string)`, `getTranscript(path: string): Promise<string>`, `getMeta(): Promise<Meta>` — thin typed `fetch` wrappers over `/api/*`.
  - Routing: `HashRouter` with routes `#/files`, `#/download`, `#/transcribe`, `#/job/:id` (`download`/`transcribe`/`job` are placeholders until Tasks 9/12); `Layout` renders the left nav with animated active-item indicator (`motion` `layoutId`).

- [ ] **Step 1: Scaffold**

Run: `npm create vite@latest frontend -- --template react-ts`, then in `frontend/`: `npm i`, `npm i motion react-router-dom`, `npm i -D tailwindcss @tailwindcss/vite vitest @testing-library/react @testing-library/jest-dom jsdom`; init shadcn/ui (`npx shadcn@latest init`, add `button card select input progress badge scroll-area`). Configure `vite.config.ts`: Tailwind plugin, `server.proxy = {"/api": "http://127.0.0.1:8756"}`, vitest `environment: "jsdom"`.
Expected: `npm run build` produces `frontend/dist`; `npm test` runs (0 tests ok).

- [ ] **Step 2: Write the failing tests**

```ts
// api.test.ts — mock global fetch; getFiles() hits /api/files and returns tree array
// FileTree.test.tsx — renders nested TreeNode fixture; transcribed file shows badge (✓),
//                     untranscribed shows none; clicking a dir toggles its children
```

- [ ] **Step 3: Run to FAIL** — `cd frontend && npm test` → FAIL (modules missing)

- [ ] **Step 4: Implement** `types.ts`, `api.ts`, `Layout`, `FilesView` (tree + `TranscriptViewer` side pane; selecting a transcribed file loads the transcript; animate pane in with `motion`), placeholder routes.

- [ ] **Step 5: Run to PASS** — `npm test`; then `npm run build` → dist exists.

- [ ] **Step 6: Manual M1 verification**

Run `./run.sh` → browser opens built app; Files view badges match reality (spot-check `transcripts/therapy/`); a Cyrillic-named transcript opens in the viewer; nested `consulting/marketing` renders. Separately `npm run dev` + uvicorn → same via :5173 proxy.

- [ ] **Step 7: Commit** — `git commit -m "feat: M1 — React frontend scaffold, file browser, transcript viewer"`

---

### Task 6: EventBus (`app/events.py`)

**Files:**
- Create: `app/events.py`
- Test: `tests/test_events.py`

**Interfaces:**
- Produces: `class EventBus:` with `attach_loop(loop: asyncio.AbstractEventLoop) -> None`; `publish(event: dict) -> None` (safe from any thread; no-op before `attach_loop`); `subscribe() -> asyncio.Queue` (bounded, `maxsize=200`); `unsubscribe(q) -> None`. On a full subscriber queue, **drop the oldest** event and enqueue the new one. Event dicts: `{"type": "job_status"|"job_progress"|"job_log"|"queue", ...payload}`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_publish_from_thread_reaches_subscriber(): ...
    # attach running loop, publish from threading.Thread, q.get() returns event
async def test_full_queue_drops_oldest_not_blocks():
    # publish maxsize+1 events; first event gone, last present   (Review Focus #5)
async def test_unsubscribed_queue_stops_receiving(): ...
```

- [ ] **Step 2: FAIL**, **Step 3: Implement** (`loop.call_soon_threadsafe`; on `QueueFull`: `get_nowait()` then `put_nowait`), **Step 4: PASS** — `venv/bin/python -m pytest tests/test_events.py -v`

- [ ] **Step 5: Commit** — `git commit -m "feat: thread-safe event bus with drop-oldest backpressure"`

---

### Task 7: Worker + queue + cancellation (`app/worker.py`)

**Files:**
- Create: `app/worker.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: Task 2 db functions, Task 6 `EventBus`.
- Produces:
  - `class JobCancelled(Exception)` is imported from `transcribe.py` — **defined there in Task 10**; until then worker defines a local fallback: `try: from transcribe import JobCancelled except ImportError: class JobCancelled(Exception): pass`.
  - `class JobContext:` attrs `job_id: int`, `cancel_event: threading.Event`; methods `log(line: str)`, `progress(percent: float, stage: str, detail: str = "")` (DB writes throttled: ≥1s elapsed or ≥2% delta; every update published to bus), `check_cancelled()` (raises `JobCancelled` if set).
  - `class Worker:` `__init__(db_path, bus: EventBus)`; `register(kind: str, handler: Callable[[dict, JobContext], dict])`; `start()` (daemon thread); `submit(job_id: int)`; `cancel(job_id: int) -> str | None` — returns new status: `"cancelled"` if still queued (set directly), `"cancelling"` if running (sets event), `None` if job terminal/unknown; `queue_snapshot() -> list[int]`.
  - Run loop: pop job id → status `running` (publish) → handler → `done` + `result`; `JobCancelled` → `cancelled`; other exception → `error` with `str(e)` (publish all).

- [ ] **Step 1: Write the failing tests** (handlers are plain fakes; no real downloads/models)

```python
def test_jobs_run_sequentially_in_submit_order(): ...   # handler appends to list; submit 3
def test_handler_result_stored_and_status_done(): ...
def test_handler_exception_sets_error(): ...
def test_cancel_queued_job_never_runs(): ...
def test_cancel_running_sets_cancelling_then_cancelled():
    # handler waits on ctx.cancel_event then calls ctx.check_cancelled()
def test_cancel_finished_job_is_noop_returns_none(): ...   # Review Focus #3
def test_double_cancel_idempotent(): ...
```

- [ ] **Step 2: FAIL**, **Step 3: Implement** (stdlib `queue.Queue` of job ids; per-job `threading.Event` registry; worker opens its own db connection in-thread), **Step 4: PASS** — `venv/bin/python -m pytest tests/test_worker.py -v`

- [ ] **Step 5: Commit** — `git commit -m "feat: sequential worker with cooperative cancellation"`

---

### Task 8: Downloader service (`app/services/downloader.py`)

**Files:**
- Create: `app/services/downloader.py`
- Test: `tests/test_downloader.py`

**Interfaces:**
- Consumes: `JobContext` (Task 7).
- Produces: `run_download(params: dict, ctx: JobContext, audio_root: Path) -> dict`.
  - `params`: `{"url": str, "category": str | "" , "format": "audio"}` (MVP: audio-only, yt-dlp `format="bestaudio"` + `FFmpegExtractAudio` postprocessor to mp3).
  - Builds `YoutubeDL` opts: `outtmpl=str(target_dir / "%(title)s [%(id)s].%(ext)s")`, `ffmpeg_location=config.FFMPEG_LOCATION`, `progress_hooks=[hook]`, `noplaylist=True`.
  - hook: on `downloading` → `ctx.progress(downloaded/total*100, "downloading", f"{speed} {eta}")` and `ctx.check_cancelled()` (raising inside the hook aborts yt-dlp); on `finished` → `ctx.progress(100, "postprocessing")`.
  - Returns `{"files": [rel_paths]}`. On `JobCancelled` or error: delete `*.part`/`*.ytdl` litter in `target_dir` for this job, re-raise.
  - yt-dlp errors (`DownloadError`) re-raised as `RuntimeError` with yt-dlp's message (→ job `error`, Review Focus #1).

- [ ] **Step 1: Write the failing tests** (monkeypatch `yt_dlp.YoutubeDL` with a fake capturing opts and driving hooks; no network)

```python
def test_opts_built_correctly(tmp_path): ...       # outtmpl under category dir, ffmpeg_location set
def test_progress_hook_maps_to_ctx(): ...          # fake hook call → ctx.progress recorded
def test_cancel_during_download_cleans_part_files(tmp_path): ...
def test_downloaderror_becomes_runtimeerror_with_message(): ...   # Review Focus #1
def test_result_lists_relative_paths(tmp_path): ...
```

- [ ] **Step 2: FAIL**, **Step 3: Implement**, **Step 4: PASS** — `venv/bin/python -m pytest tests/test_downloader.py -v`

- [ ] **Step 5: Commit** — `git commit -m "feat: yt-dlp download service with progress and cancel"`

---

### Task 9: Jobs API + SSE + Download UI (M2 complete)

**Files:**
- Modify: `app/main.py`, `app/schemas.py`
- Create: `frontend/src/views/DownloadView.tsx`, `frontend/src/views/JobView.tsx`, `frontend/src/components/JobCard.tsx`, `frontend/src/components/ProgressBar.tsx`, `frontend/src/lib/useEvents.ts`
- Test: `tests/test_api_jobs.py`, `frontend/src/components/JobCard.test.tsx`

**Interfaces:**
- Consumes: Worker (Task 7), downloader (Task 8), EventBus (Task 6), frontend `api.ts`/`types.ts` (Task 5).
- Produces backend routes:
  - `POST /api/jobs/download {url, category}` → 202 `{"job_id"}` (validates category exists, url non-empty).
  - `GET /api/jobs?kind=` → `{"jobs": [...]}`; `GET /api/jobs/{id}` → job dict (404 if missing); `GET /api/jobs/{id}/logs` → `{"logs": [...]}`.
  - `POST /api/jobs/{id}/cancel` → `{"status": <new status>}`; 200 even when no-op (`{"status": null}`).
  - `GET /api/queue` → `{"queue": [ids]}`.
  - `GET /api/events` → SSE via sse-starlette `EventSourceResponse` over `bus.subscribe()`.
  - Lifespan startup: `bus.attach_loop(...)`, `db.mark_interrupted`, `worker.register("download", ...)`, `worker.start()`.
- Produces frontend:
  - `useEvents(onEvent: (e: AppEvent) => void)` — one shared `EventSource("/api/events")`, auto-reconnect, cleans up on unmount.
  - `api.ts` additions: `createDownloadJob({url, category})`, `getJobs(kind?)`, `getJob(id)`, `getJobLogs(id)`, `cancelJob(id)`.
  - `DownloadView`: URL input + category select (shadcn), submit → navigate to `#/job/<id>`; job history as `JobCard` list — cards animate in/out (`AnimatePresence`), live progress via events.
  - `JobView`: status badge, animated `ProgressBar` (spring-driven width, indeterminate shimmer when stage has no %), auto-scrolling log stream, Cancel button on queued/running.
  - `ProgressBar` props: `{percent: number | null, stage: string}` — `percent null` renders indeterminate.

- [ ] **Step 1: Write the failing backend tests** (TestClient; register a fake instant handler for kind "download" so no network)

```python
def test_post_download_creates_queued_job(client): ...
def test_get_job_and_logs(client): ...
def test_cancel_endpoint_noop_on_done_job(client): ...   # Review Focus #3 surface
def test_unknown_job_404(client): ...
```

- [ ] **Step 2: Run to FAIL**, **Step 3: Implement backend routes + lifespan**, **Step 4: Run to PASS** — `venv/bin/python -m pytest tests/test_api_jobs.py -v`

- [ ] **Step 5: Write the failing frontend test** — `JobCard.test.tsx`: renders a done job with title from params, status badge text, and progress 100; cancelled job shows "cancelled". Run `npm test` → FAIL.

- [ ] **Step 6: Implement frontend** (`useEvents`, views, components per Interfaces). Run `npm test` → PASS; `npm run build` succeeds.

- [ ] **Step 7: Manual M2 verification**

Run `./run.sh` (after build): short YouTube URL → animated live % → file lands in `audio_sources/<cat>/`; cancel mid-download → status `cancelled`, no `.part` litter; restart server → old running job shows `error: interrupted by restart`; Cyrillic-titled video downloads with correct filename; killing/reopening the tab reconnects SSE and shows current state.

- [ ] **Step 8: Commit** — `git commit -m "feat: M2 — jobs API, SSE, animated download module"`

---

### Task 10: `transcribe.py` refactor (CLI regression-free)

**Files:**
- Modify: `transcribe.py`
- Test: `tests/test_transcribe_refactor.py`

**Interfaces:**
- Produces (in `transcribe.py`):
  - `class JobCancelled(Exception)`
  - `load_whisper_model(model_name: str, language: str | None = None, threads: int = 4, beam_size: int = 5)` — extracted from `main()` lines 283–293; **raises** `RuntimeError(f"Failed to load WhisperX model '{model_name}': {e}")` instead of `sys.exit`; `main()` catches it, prints, exits 1.
  - `load_diarization_model(hf_token: str, log_fn=print)` — extracted from lines 295–322 including MPS→CPU fallback; returns model or `None`; all prints become `log_fn`.
  - `transcribe_file(...)` gains keyword args `progress_fn=None, cancel_event=None, skip_existing=True`; passes `progress_callback=_wrapped` to `model.transcribe` where `_wrapped(pct)` calls `progress_fn(pct)` and raises `JobCancelled` if `cancel_event` is set; explicit `cancel_event` checks before transcribe, before align, before diarize; returns `output_path: str` (or `None` when skipped). Existing positional/keyword params unchanged.

- [ ] **Step 1: Capture CLI baseline** — `venv/bin/python transcribe.py --help > /tmp/help_before.txt` (and `transcribe --help`).

- [ ] **Step 2: Write the failing tests** (import `transcribe`; monkeypatch `transcribe.whisperx` and model objects with fakes — fake `load_audio` returns `[0.0]*16000`, fake `model.transcribe` returns `{"segments": [{"start":0,"end":1,"text":"hi"}], "language":"en"}`, fake `align` passthrough)

```python
def test_transcribe_file_returns_output_path(tmp_path, fakes): ...
def test_skip_existing_returns_none(tmp_path, fakes): ...
def test_progress_fn_receives_percent(fakes): ...        # fake model calls progress_callback(50.0)
def test_cancel_event_raises_jobcancelled_before_align(tmp_path, fakes): ...
def test_load_whisper_model_raises_not_exits(monkeypatch): ...  # fake load_model throws
```

- [ ] **Step 3: Run to FAIL**, **Step 4: Implement the refactor**, **Step 5: Run to PASS** — `venv/bin/python -m pytest tests/test_transcribe_refactor.py -v`

- [ ] **Step 6: CLI regression check**

Run: `venv/bin/python transcribe.py --help | diff /tmp/help_before.txt -` → no diff.
Run: `venv/bin/python transcribe.py -m tiny --no-diarize <short existing audio file> -o /tmp/regression_out` → transcript produced in the exact `[HH:MM:SS - HH:MM:SS] SPEAKER: text` format; rerun reports skip.

- [ ] **Step 7: Commit** — `git commit -m "refactor: extract model loaders, add progress/cancel hooks to transcribe_file"`

---

### Task 11: Transcriber service with warm cache (`app/services/transcriber.py`)

**Files:**
- Create: `app/services/transcriber.py`
- Test: `tests/test_transcriber.py`

**Interfaces:**
- Consumes: Task 10 (`load_whisper_model`, `load_diarization_model`, `transcribe_file`, `JobCancelled`), `JobContext` (Task 7).
- Produces:
  - `class ModelCache:` single-entry whisper cache keyed by `(model_name, language, threads, beam_size)` — on key change: drop ref, `gc.collect()`, load new; `get_whisper(key) -> model`; `get_diarizer(hf_token) -> model | None` loaded once, cached forever; `align_cache: dict` shared across jobs.
  - `run_transcribe(params: dict, ctx: JobContext, audio_root: Path, transcripts_root: Path, cache: ModelCache) -> dict`
    - `params`: `{"path": rel source path, "model": str, "language": str|None, "diarize": bool, "num_speakers": int|None}`.
    - Validates source exists under `audio_root` (missing → `RuntimeError("source file not found: ...")`, Review Focus #4).
    - Stages via `ctx.progress`: `loading_model` (indeterminate, percent 0) → `transcribing` (map `progress_fn` 0–100 directly) → `aligning` → `diarizing` (both indeterminate).
    - Output dir mirrors the source's relative dir under `transcripts_root` (mkdir -p).
    - Returns `{"output_path": rel_path}` or `{"skipped": true, "output_path": rel_path}`.

- [ ] **Step 1: Write the failing tests** (monkeypatch the three `transcribe` functions with fakes)

```python
def test_missing_source_raises_readable_error(tmp_path): ...     # Review Focus #4
def test_output_dir_mirrors_nested_relative_path(tmp_path): ...  # consulting/marketing/x.mp3
def test_cache_reuses_model_for_same_key_and_evicts_on_change(): ...
def test_stage_progression_reported(): ...   # ctx captured stages include loading_model→transcribing
def test_skip_existing_reported(): ...
```

- [ ] **Step 2: FAIL**, **Step 3: Implement**, **Step 4: PASS** — `venv/bin/python -m pytest tests/test_transcriber.py -v`

- [ ] **Step 5: Commit** — `git commit -m "feat: transcriber service with warm single-entry model cache"`

---

### Task 12: Transcribe module API + UI (M3 complete, MVP done)

**Files:**
- Modify: `app/main.py`, `app/schemas.py`, `frontend/src/lib/api.ts`
- Create: `frontend/src/views/TranscribeView.tsx`, `frontend/src/components/FilePicker.tsx`
- Test: `tests/test_api_transcribe.py`

**Interfaces:**
- Consumes: Task 11 `run_transcribe`/`ModelCache`, worker registry, Task 9 `JobCard`/`ProgressBar`/`useEvents`, Task 5 `FileTree`.
- Produces:
  - `POST /api/jobs/transcribe {path, model, language?, diarize, num_speakers?}` → 202 `{"job_id"}`; 400 on model not in `config.WHISPER_MODELS` or path escaping `audio_root`.
  - Lifespan registers `worker.register("transcribe", ...)` with one process-wide `ModelCache` owned by the worker.
  - `TranscribeView`: `FilePicker` (reuses tree data; untranscribed files highlighted, transcribed dimmed), model select from `/api/meta`, language input, diarize switch (disabled with hint when `hf_token_present` is false), num-speakers input; submit → `#/job/<id>` with live stage/percent/logs; history list for `kind=transcribe`; done jobs link to the transcript in the Files view.

- [ ] **Step 1: Write the failing backend tests** (fake handler in test app)

```python
def test_post_transcribe_validates_model(client): ...   # bad model → 400
def test_post_transcribe_rejects_escaping_path(client): ...
def test_post_transcribe_queues_job(client): ...
```

- [ ] **Step 2: Run to FAIL**, **Step 3: Implement backend + frontend**, **Step 4: Run to PASS** — `venv/bin/python -m pytest tests/test_api_transcribe.py -v`; `cd frontend && npm test && npm run build`.

- [ ] **Step 5: Full test suite** — `venv/bin/python -m pytest -v` and `cd frontend && npm test` → all green.

- [ ] **Step 6: Manual M3 / MVP verification**

- CLI regression re-check: `venv/bin/python transcribe.py -m tiny --no-diarize <short file>` unchanged.
- Web: transcribe a short file with `tiny` → live animated % during transcription, stage changes for align/diarize (indeterminate shimmer), transcript opens from Files view in mirrored dir.
- Second same-model job starts without reloading (warm cache — log shows no "Loading" line).
- Cancel during transcription lands within seconds; cancel during diarization shows `cancelling` then `cancelled` at phase end.
- Skip-existing job reports skipped.
- Reduced-motion: with macOS "Reduce Motion" on, progress updates render without springs.

- [ ] **Step 7: Commit** — `git commit -m "feat: M3 — transcribe module; Transcribing Studio MVP complete"`
