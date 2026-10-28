# Files / Transcripts Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the Studio into a Files tab (source audio: pick, upload, delete, transcribe) and a Transcripts tab (browse `transcripts/`, read, copy, delete), with icon buttons for every action.

**Architecture:** Backend adds four endpoints on top of `app/services/files.py` (transcripts tree, multipart upload, two deletes) plus a db helper for the "job in flight" guard. Frontend renames routes/nav, turns the existing `FilesView` into `TranscriptsView` driven by the transcripts tree, and gives `FilePicker` upload/delete controls. A small `IconButton` wraps `lucide-react` icons.

**Tech Stack:** FastAPI + python-multipart, pytest; React 19 + TS + Tailwind 4 + react-router 7, lucide-react, vitest + testing-library.

**Spec:** `docs/superpowers/specs/2026-10-28-files-transcripts-restructure-design.md`

## Global Constraints

- Services in `app/services/files.py` take `audio_root` / `transcripts_root` as parameters and never import `app.config`.
- Services raise `ValueError` for caller mistakes; routes map them to 4xx. New: `FileExistsError` → 409, `FileNotFoundError` → 404.
- Path safety: every rel path is resolved and checked with `.is_relative_to(root.resolve())` before use.
- Transcript naming: `transcripts/<rel-dir>/<audio-name-with-ext>.txt`. Deleting one side never touches the other.
- Nav order and labels: Download · Files · Transcripts. Routes: `/download`, `/files`, `/transcripts`, `/job/:id`. `/transcribe` redirects to `/files`.
- Icon buttons: 16 px lucide icons, `aria-label` + `title` on every instance. No browser `confirm()`; confirmations are inline.
- Upload: no size limit, no overwrite (409), stream to a temp file in the target dir then rename.
- Commands that must pass at the end: `venv/bin/python -m pytest`, `cd frontend && npx vitest run`, `cd frontend && npx tsc -b`, `cd frontend && npm run build`.
- Not built (no caller after the restructure): the `/files?path=` picker deep link from the spec. Retry still prefills via router state.

## Review Focus

1. Upload of `Recording.MP3` (uppercase extension) must be accepted; extension check is case-insensitive. Test in Task 2.
2. `transcripts/` containing `.DS_Store` or a stray `.json` must list only `.txt` files. Test in Task 1.
3. Deleting a source whose transcript exists leaves the transcript on disk and visible in the Transcripts tab. Test in Task 3.
4. Clicking the "already transcribed" badge must open the transcript and must not select the file for transcription. Test in Task 6.
5. Copy when `navigator.clipboard.writeText` rejects shows an inline error instead of a silent no-op. Test in Task 7.

---

### Task 1: Transcripts tree endpoint and `supported_extensions` in `/api/meta`

**Files:**
- Modify: `app/services/files.py`
- Modify: `app/main.py` (`get_meta`, new route after `get_files`)
- Modify: `app/schemas.py` (`MetaResponse`)
- Test: `tests/test_files.py`, `tests/test_api_files.py`

**Interfaces:**
- Produces: `files.list_transcripts_tree(transcripts_root: Path) -> list[dict]` (same node dicts as `list_tree`, no `transcribed` key); `GET /api/transcripts` → `FilesResponse`; `MetaResponse.supported_extensions: list[str]` sorted, with leading dots (e.g. `".m4a"`).

- [ ] **Step 1: Write the failing service test** in `tests/test_files.py`

```python
def test_transcripts_tree_lists_txt_only(roots):
    _, transcripts_root = roots
    (transcripts_root / ".DS_Store").write_bytes(b"")
    (transcripts_root / "therapy" / "notes.json").write_text("{}")
    tree = files.list_transcripts_tree(transcripts_root)
    assert tree == [
        {"name": "consulting", "path": "consulting", "type": "dir", "children": [
            {"name": "marketing", "path": "consulting/marketing", "type": "dir", "children": [
                {"name": "b.mp3.txt", "path": "consulting/marketing/b.mp3.txt", "type": "file"},
            ]},
        ]},
        {"name": "therapy", "path": "therapy", "type": "dir", "children": [
            {"name": "a.m4a.txt", "path": "therapy/a.m4a.txt", "type": "file"},
        ]},
    ]
```

- [ ] **Step 2: Run it**: `venv/bin/python -m pytest tests/test_files.py::test_transcripts_tree_lists_txt_only -v` → FAIL, `AttributeError`.

- [ ] **Step 3: Implement `list_transcripts_tree`** in `app/services/files.py`. Generalise `_build_tree` with a `file_filter` / `annotate` pair or write a sibling `_build_transcripts_tree`; dirs first, then `.txt` files, each group sorted by name.

- [ ] **Step 4: Write the failing API tests** in `tests/test_api_files.py`

```python
def test_transcripts_endpoint_shape(client):
    body = client.get("/api/transcripts").json()
    therapy = next(n for n in body["tree"] if n["name"] == "therapy")
    assert therapy["children"][0]["path"] == "therapy/a.m4a.txt"
    assert "transcribed" not in therapy["children"][0] or therapy["children"][0]["transcribed"] is None

def test_meta_exposes_supported_extensions(client):
    exts = client.get("/api/meta").json()["supported_extensions"]
    assert ".m4a" in exts and ".mp3" in exts and exts == sorted(exts)
```

- [ ] **Step 5: Run them** → FAIL (404 / KeyError).

- [ ] **Step 6: Add the route and field.** `@app.get("/api/transcripts", response_model=FilesResponse)`; `supported_extensions=sorted(SUPPORTED_EXTENSIONS)` in `get_meta` (import from `transcribe`). Add `supported_extensions: list[str]` to `MetaResponse`. Use `response_model_exclude_none=True` on the transcripts route so `transcribed: null` is omitted.

- [ ] **Step 7: Run** `venv/bin/python -m pytest tests/test_files.py tests/test_api_files.py -v` → PASS.

- [ ] **Step 8: Commit**: `git commit -m "feat: transcripts tree endpoint, expose supported extensions"`

---

### Task 2: Upload endpoint

**Files:**
- Modify: `requirements.txt` (add `python-multipart`), run `venv/bin/pip install python-multipart`
- Modify: `app/services/files.py`, `app/main.py`
- Test: `tests/test_files.py`, `tests/test_api_files.py`

**Interfaces:**
- Produces: `files.save_upload(audio_root: Path, category: str, filename: str, stream: BinaryIO) -> str` returning the rel path (`"podcast/ep2.mp3"` or `"ep2.mp3"`). Raises `ValueError` (bad extension, bad filename, unknown category), `FileExistsError` (duplicate). `POST /api/files/upload` multipart fields `file`, `category` → 201 `{"path": ...}`; 400 / 409.

- [ ] **Step 1: Failing service tests** in `tests/test_files.py`

```python
import io

def test_save_upload_into_category_and_root(roots):
    audio_root, _ = roots
    rel = files.save_upload(audio_root, "therapy", "new.MP3", io.BytesIO(b"abc"))
    assert rel == "therapy/new.MP3"
    assert (audio_root / "therapy" / "new.MP3").read_bytes() == b"abc"
    assert files.save_upload(audio_root, "", "loose.wav", io.BytesIO(b"x")) == "loose.wav"
    assert not list(audio_root.glob("**/.upload-*"))  # no temp files left behind

@pytest.mark.parametrize("category,filename", [
    ("therapy", "notes.txt"),        # unsupported extension
    ("therapy", "../a.m4a"),         # path separator
    ("therapy", ".."),
    ("nope", "a.m4a"),               # unknown category
    ("../etc", "a.m4a"),             # category escape
])
def test_save_upload_rejects(roots, category, filename):
    audio_root, _ = roots
    with pytest.raises(ValueError):
        files.save_upload(audio_root, category, filename, io.BytesIO(b""))

def test_save_upload_duplicate_is_file_exists(roots):
    audio_root, _ = roots
    with pytest.raises(FileExistsError):
        files.save_upload(audio_root, "therapy", "a.m4a", io.BytesIO(b""))
    assert (audio_root / "therapy" / "a.m4a").read_bytes() == b""
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement `save_upload`.** Validate: `Path(filename).name == filename` and filename not in `{".", ".."}`; `Path(filename).suffix.lower() in SUPPORTED_EXTENSIONS`; target dir = `audio_root` if `category == ""` else `audio_root / category`, must resolve inside the root and `is_dir()`. If target file exists → `FileExistsError`. Write with `tempfile.NamedTemporaryFile(dir=target_dir, prefix=".upload-", delete=False)` + `shutil.copyfileobj`, then `os.replace` into place; unlink the temp file on any exception.

- [ ] **Step 4: Run** → PASS.

- [ ] **Step 5: Failing API tests** in `tests/test_api_files.py`

```python
def test_upload_creates_file_and_returns_path(client, roots):
    audio_root, _, _ = roots
    resp = client.post("/api/files/upload", files={"file": ("ep2.mp3", b"data", "audio/mpeg")}, data={"category": "therapy"})
    assert resp.status_code == 201 and resp.json() == {"path": "therapy/ep2.mp3"}
    assert (audio_root / "therapy" / "ep2.mp3").read_bytes() == b"data"

def test_upload_duplicate_is_409(client):
    resp = client.post("/api/files/upload", files={"file": ("a.m4a", b"", "audio/mp4")}, data={"category": "therapy"})
    assert resp.status_code == 409

def test_upload_bad_extension_is_400(client):
    resp = client.post("/api/files/upload", files={"file": ("x.txt", b"", "text/plain")}, data={"category": ""})
    assert resp.status_code == 400
```

- [ ] **Step 6: Run** → FAIL (404).

- [ ] **Step 7: Add the route.** `def post_upload(file: UploadFile = File(...), category: str = Form("")) -> dict`, status 201; call `save_upload(audio_root, category, file.filename or "", file.file)`; map `ValueError`→400, `FileExistsError`→409 with `detail=f"{filename} already exists in that category"`.

- [ ] **Step 8: Run** `venv/bin/python -m pytest tests/test_files.py tests/test_api_files.py -v` → PASS.

- [ ] **Step 9: Commit**: `git commit -m "feat: upload audio files into a category"` (include `requirements.txt`).

---

### Task 3: Delete endpoints with the in-flight job guard

**Files:**
- Modify: `app/db.py`, `app/services/files.py`, `app/main.py`
- Test: `tests/test_db.py`, `tests/test_files.py`, `tests/test_api_files.py`

**Interfaces:**
- Produces: `db.list_active_transcribe_jobs(conn) -> list[dict]` (jobs with `kind == "transcribe"` and status in `queued`, `running`, `cancelling`); `files.delete_source_file(audio_root, rel_path) -> None`; `files.delete_transcript(transcripts_root, rel_path) -> None`; `DELETE /api/files?path=` and `DELETE /api/transcripts?path=` → 204 / 400 / 404 / 409.

- [ ] **Step 1: Failing db test** in `tests/test_db.py`

```python
def test_list_active_transcribe_jobs(conn):
    a = db.create_job(conn, kind="transcribe", params={"path": "x.mp3"}, category=None)
    b = db.create_job(conn, kind="transcribe", params={"path": "y.mp3"}, category=None)
    db.set_status(conn, b, "done")
    d = db.create_job(conn, kind="download", params={"url": "u"}, category=None)
    assert [j["id"] for j in db.list_active_transcribe_jobs(conn)] == [a]
```

(Match `create_job` / `set_status` argument names to their real signatures in `app/db.py`.)

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** with one `SELECT ... WHERE kind='transcribe' AND status IN ('queued','running','cancelling')`. **Step 4: Run** → PASS.

- [ ] **Step 5: Failing service tests** in `tests/test_files.py`

```python
def test_delete_source_file_leaves_transcript(roots):
    audio_root, transcripts_root = roots
    files.delete_source_file(audio_root, "therapy/a.m4a")
    assert not (audio_root / "therapy" / "a.m4a").exists()
    assert (transcripts_root / "therapy" / "a.m4a.txt").exists()
    assert files.list_transcripts_tree(transcripts_root)[1]["children"][0]["name"] == "a.m4a.txt"

def test_delete_transcript_leaves_audio(roots):
    audio_root, transcripts_root = roots
    files.delete_transcript(transcripts_root, "therapy/a.m4a.txt")
    assert not (transcripts_root / "therapy" / "a.m4a.txt").exists()
    assert (audio_root / "therapy" / "a.m4a").exists()

@pytest.mark.parametrize("rel", ["../x", "therapy", "a.m4a.txt"])
def test_delete_source_file_rejects(roots, rel):
    audio_root, _ = roots
    with pytest.raises((ValueError, FileNotFoundError)):
        files.delete_source_file(audio_root, rel)

def test_delete_transcript_rejects_non_txt(roots):
    _, transcripts_root = roots
    (transcripts_root / "therapy" / "x.json").write_text("{}")
    with pytest.raises(ValueError):
        files.delete_transcript(transcripts_root, "therapy/x.json")
    with pytest.raises(FileNotFoundError):
        files.delete_transcript(transcripts_root, "therapy/missing.txt")
```

- [ ] **Step 6: Run** → FAIL. **Step 7: Implement** both: resolve, escape → `ValueError`; not a file → `FileNotFoundError` if nothing exists there, `ValueError` if it's a dir; source must have a supported suffix, transcript must end `.txt`; then `unlink()`. **Step 8: Run** → PASS.

- [ ] **Step 9: Failing API tests** in `tests/test_api_files.py`. Add a `blocking_client` fixture that registers a transcribe handler which waits on a `threading.Event` (pattern from `tests/test_api_transcribe.py`), and a `wait_until` helper copied from there.

```python
def test_delete_source_file_204_and_404(client, roots):
    audio_root, _, _ = roots
    assert client.delete("/api/files", params={"path": "c.mp3"}).status_code == 204
    assert not (audio_root / "c.mp3").exists()
    assert client.delete("/api/files", params={"path": "c.mp3"}).status_code == 404
    assert client.delete("/api/files", params={"path": "../.env"}).status_code == 400

def test_delete_transcript_204_and_404(client, roots):
    _, transcripts_root, _ = roots
    assert client.delete("/api/transcripts", params={"path": "therapy/a.m4a.txt"}).status_code == 204
    assert not (transcripts_root / "therapy" / "a.m4a.txt").exists()
    assert client.delete("/api/transcripts", params={"path": "therapy/a.m4a.txt"}).status_code == 404

def test_delete_source_refused_while_job_queued_or_running(blocking_client):
    client, release = blocking_client
    first = client.post("/api/jobs/transcribe", json={"path": "therapy/a.m4a", "model": "tiny", "diarize": False}).json()["job_id"]
    second = client.post("/api/jobs/transcribe", json={"path": "c.mp3", "model": "tiny", "diarize": False}).json()["job_id"]
    assert wait_until(lambda: client.get(f"/api/jobs/{first}").json()["status"] == "running")
    assert client.delete("/api/files", params={"path": "therapy/a.m4a"}).status_code == 409   # running
    assert client.delete("/api/files", params={"path": "c.mp3"}).status_code == 409           # queued
    # transcript delete: refused only while running
    assert client.delete("/api/transcripts", params={"path": "therapy/a.m4a.txt"}).status_code == 409
    release.set()
    assert wait_until(lambda: client.get(f"/api/jobs/{second}").json()["status"] == "done")
    assert client.delete("/api/files", params={"path": "c.mp3"}).status_code == 204

def test_delete_transcript_allowed_while_job_only_queued(blocking_client):
    client, release = blocking_client
    client.post("/api/jobs/transcribe", json={"path": "c.mp3", "model": "tiny", "diarize": False})   # runs & blocks
    queued = client.post("/api/jobs/transcribe", json={"path": "therapy/a.m4a", "model": "tiny", "diarize": False}).json()["job_id"]
    assert wait_until(lambda: client.get(f"/api/jobs/{queued}").json()["status"] == "queued")
    assert client.delete("/api/transcripts", params={"path": "therapy/a.m4a.txt"}).status_code == 204
    release.set()
```

- [ ] **Step 10: Run** → FAIL (405/404).

- [ ] **Step 11: Add the routes** in `app/main.py`:
  - `@app.delete("/api/files", status_code=204)` `def delete_source(path: str) -> Response`: open db, if any active job has `params.get("path") == path` → 409 `detail="a job is using this file"`; else call service; map `ValueError`→400, `FileNotFoundError`→404; return `Response(status_code=204)`.
  - `@app.delete("/api/transcripts", status_code=204)` `def delete_transcript_route(path: str) -> Response`: audio path = `path[:-4]` when `path.endswith(".txt")`; 409 `detail="a job is writing this transcript"` only when an active job with status in `{"running", "cancelling"}` matches; same error mapping.

- [ ] **Step 12: Run** `venv/bin/python -m pytest -v` → PASS (whole suite).

- [ ] **Step 13: Commit**: `git commit -m "feat: delete source files and transcripts, guarded by in-flight jobs"`

---

### Task 4: Frontend API client, types, `IconButton`

**Files:**
- Modify: `frontend/src/lib/api.ts`, `frontend/src/lib/types.ts`
- Create: `frontend/src/components/ui/IconButton.tsx`
- Modify: `frontend/package.json` (run `cd frontend && npm install lucide-react`)
- Test: `frontend/src/lib/api.test.ts`, `frontend/src/components/ui/IconButton.test.tsx`

**Interfaces:**
- Produces: `getTranscriptsTree(): Promise<TreeNode[]>`; `uploadFile(file: File, category: string): Promise<{ path: string }>`; `deleteSourceFile(path: string): Promise<void>`; `deleteTranscript(path: string): Promise<void>`; `Meta.supported_extensions: string[]`; `IconButton` with props `label: string` (used for `aria-label` and `title`), `variant?: 'ghost' | 'danger'`, plus native button props; renders `type="button"`.

- [ ] **Step 1: Failing api tests** (extend `mockFetchOnce` so `json` rejects when `status === 204`)

```ts
it('getTranscriptsTree() hits /api/transcripts', async () => {
  const fetchMock = mockFetchOnce({ tree: [] })
  expect(await getTranscriptsTree()).toEqual([])
  expect(fetchMock).toHaveBeenCalledWith('/api/transcripts')
})
it('uploadFile() posts multipart with file and category', async () => {
  const fetchMock = mockFetchOnce({ path: 'therapy/x.mp3' }, { status: 201 })
  const file = new File(['x'], 'x.mp3', { type: 'audio/mpeg' })
  expect(await uploadFile(file, 'therapy')).toEqual({ path: 'therapy/x.mp3' })
  const [url, init] = fetchMock.mock.calls[0]
  expect(url).toBe('/api/files/upload')
  expect(init.method).toBe('POST')
  expect((init.body as FormData).get('category')).toBe('therapy')
  expect((init.body as FormData).get('file')).toBe(file)
  expect(init.headers).toBeUndefined()
})
it('deleteSourceFile() and deleteTranscript() send DELETE and resolve on 204', async () => {
  let fetchMock = mockFetchOnce(undefined, { status: 204 })
  await expect(deleteSourceFile('a/b.mp3')).resolves.toBeUndefined()
  expect(fetchMock).toHaveBeenCalledWith('/api/files?path=a%2Fb.mp3', { method: 'DELETE' })
  fetchMock = mockFetchOnce(undefined, { status: 204 })
  await deleteTranscript('a/b.mp3.txt')
  expect(fetchMock).toHaveBeenCalledWith('/api/transcripts?path=a%2Fb.mp3.txt', { method: 'DELETE' })
})
```

- [ ] **Step 2: Run** `cd frontend && npx vitest run src/lib/api.test.ts` → FAIL.

- [ ] **Step 3: Implement.** In `request()`, after the `ok` check: `if (response.status === 204) return undefined as T`. `uploadFile` builds a `FormData` and passes no `headers`.

- [ ] **Step 4: Failing IconButton test**

```tsx
it('exposes label as aria-label and title and is type=button', () => {
  render(<IconButton label="Copy transcript"><svg /></IconButton>)
  const btn = screen.getByRole('button', { name: 'Copy transcript' })
  expect(btn).toHaveAttribute('title', 'Copy transcript')
  expect(btn).toHaveAttribute('type', 'button')
})
```

- [ ] **Step 5: Implement `IconButton`.** Classes: `inline-flex size-8 items-center justify-center rounded-md transition-colors disabled:cursor-not-allowed disabled:opacity-50`; ghost: `text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100`; danger: `text-zinc-400 hover:bg-red-500/10 hover:text-red-400`.

- [ ] **Step 6: Run** `cd frontend && npx vitest run && npx tsc -b` → PASS.

- [ ] **Step 7: Commit**: `git commit -m "feat(frontend): api client for upload/delete/transcripts tree, IconButton"`

---

### Task 5: Routes, nav, and link targets

**Files:**
- Modify: `frontend/src/App.tsx`, `frontend/src/components/Layout.tsx`, `frontend/src/views/JobView.tsx`, `frontend/src/views/TranscribeView.tsx` (history link only)
- Rename: `git mv frontend/src/views/FilesView.tsx frontend/src/views/TranscriptsView.tsx` and its test; rename the component to `TranscriptsView`, header text "Transcripts"
- Test: `frontend/src/views/JobView.test.tsx`, `frontend/src/views/TranscribeView.test.tsx`, `frontend/src/views/TranscriptsView.test.tsx`

**Interfaces:**
- Produces: routes `/files` → `TranscribeView`, `/transcripts` → `TranscriptsView`, `/transcribe` → `<Navigate to="/files" replace />`; `NAV_ITEMS` = Download `/download`, Files `/files`, Transcripts `/transcripts`.

- [ ] **Step 1: Update tests first.** In `JobView.test.tsx`: route probes become `/files` ("files page" shows `location.state`) and `/transcripts` ("transcripts page" shows `location.search`); Retry test expects `/files page/` with the params; View-transcript test expects `/transcripts page/` and `/\?path=podcast%2Fep1\.mp3\.txt/`. In `TranscribeView.test.tsx`: `renderTranscribeView` route path `/files`, default entry `'/files'`, retry entry path `/files`. Add a test that a done job's history link has `href="#/transcripts?path=podcast%2Fep1.mp3.txt"` (mock `getJobs` with one done job whose `params.path` is `podcast/ep1.mp3`). In the renamed `TranscriptsView.test.tsx`: entries `/transcripts?path=…` and `/transcripts`.

- [ ] **Step 2: Run** `cd frontend && npx vitest run src/views` → FAIL.

- [ ] **Step 3: Implement.** `App.tsx` routes as above; `Layout.tsx` nav items; `JobView` Retry → `navigate('/files', { state: { retry: job.params } })`, View transcript → `navigate(`/transcripts?path=${encodeURIComponent(audioPath + '.txt')}`)`; TranscribeView history link → `href={`#/transcripts?path=${encodeURIComponent(String(job.params.path) + '.txt')}`}`. In `TranscriptsView`, keep the current audio-tree behaviour for now (Task 7 swaps the data source) but update the title to "Transcripts" and the search param handling to `/transcripts`.

- [ ] **Step 4: Run** `cd frontend && npx vitest run && npx tsc -b` → PASS.

- [ ] **Step 5: Commit**: `git commit -m "refactor(frontend): rename tabs to Files/Transcripts, retarget links"`

---

### Task 6: `FileTree` row restructure and badge link

**Files:**
- Modify: `frontend/src/components/FileTree.tsx`, `frontend/src/components/FilePicker.tsx`
- Test: `frontend/src/components/FileTree.test.tsx`, `frontend/src/components/FilePicker.test.tsx` (create)

**Interfaces:**
- Produces: file row = `<li><div data-testid="file-row" …><button type="button">{name}</button>{renderFileBadge(node)}</div></li>`; `FilePicker` badge = `<Link to={`/transcripts?path=${encodeURIComponent(node.path + '.txt')}`} data-testid="transcribed-badge">` wrapping the existing `Badge` text "already transcribed".

- [ ] **Step 1: Failing tests.** `FileTree.test.tsx` already asserts the badge lives inside `[data-testid="file-row"]`; keep it. Add to a new `FilePicker.test.tsx` (render inside `MemoryRouter`):

```tsx
it('links the transcribed badge to the transcript and does not select the file', async () => {
  const onSelect = vi.fn()
  render(<MemoryRouter><FilePicker nodes={fixture} onSelect={onSelect} categories={[]} accept="" onUpload={vi.fn()} onDelete={vi.fn()} /></MemoryRouter>)
  await userEvent.click(screen.getByText('therapy'))
  const badge = screen.getByTestId('transcribed-badge')
  expect(badge).toHaveAttribute('href', '/transcripts?path=therapy%2Fdone.m4a.txt')
  await userEvent.click(badge)
  expect(onSelect).not.toHaveBeenCalled()
  await userEvent.click(screen.getByText('done.m4a'))
  expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ path: 'therapy/done.m4a' }))
})
```

(The extra `FilePicker` props are defined in Task 8; add them to the interface now with no-op rendering so this compiles, or stub them as optional until Task 8 makes them required.)

- [ ] **Step 2: Run** → FAIL (badge is a `span` / nested-button warning).

- [ ] **Step 3: Implement.** Move `data-testid="file-row"`, `style={indent}`, hover/selected classes and `fileClassName(node)` to the wrapper `div`; the name `button` gets `min-w-0 flex-1 truncate text-left`. In `FilePicker`, import `Link` from `react-router-dom` and wrap the badge; add `hover:underline` on the badge.

- [ ] **Step 4: Run** `cd frontend && npx vitest run && npx tsc -b` → PASS, no "validateDOMNesting" warning in output.

- [ ] **Step 5: Commit**: `git commit -m "feat(frontend): transcribed badge opens the transcript"`

---

### Task 7: Transcripts tab: transcripts tree, copy, delete

**Files:**
- Modify: `frontend/src/views/TranscriptsView.tsx`, `frontend/src/components/TranscriptViewer.tsx`
- Test: `frontend/src/views/TranscriptsView.test.tsx`

**Interfaces:**
- Consumes: `getTranscriptsTree`, `getTranscript`, `deleteTranscript` (Task 4); `IconButton`.
- Produces: `TranscriptViewer` props become `{ node, content, loading, error, onDelete: (node: TreeNode) => Promise<void> }`. Header right side: Copy (`Copy`→`Check` for 1500 ms, label "Copy transcript" / "Copied"), Delete (`Trash2`, label "Delete transcript", `variant="danger"`). Inline confirm replaces the header's path line with text "Delete this transcript?" and buttons "Delete" / "Cancel". Error text rendered in `text-xs text-red-400` under the header.

- [ ] **Step 1: Rewrite `TranscriptsView.test.tsx`.** Mock `getTranscriptsTree`, `getTranscript`, `deleteTranscript`. Fixture: `therapy/done.m4a.txt` only (no `transcribed` field). Tests:

```tsx
it('selects the transcript from ?path= and loads it', …)            // path=therapy/done.m4a.txt → getTranscript('therapy/done.m4a.txt'), text shown
it('copies the transcript and shows Copied', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.assign(navigator, { clipboard: { writeText } })
  renderView('/transcripts?path=therapy/done.m4a.txt')
  await userEvent.click(await screen.findByRole('button', { name: 'Copy transcript' }))
  expect(writeText).toHaveBeenCalledWith('[00:00:00 - 00:00:05] SPEAKER_00: hello')
  expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
})
it('shows an error when the clipboard write fails', …)              // writeText rejects → text /Could not copy/ visible
it('deletes after inline confirm, refetches the tree, empties the viewer', async () => {
  vi.mocked(deleteTranscript).mockResolvedValue(undefined)
  renderView('/transcripts?path=therapy/done.m4a.txt')
  await userEvent.click(await screen.findByRole('button', { name: 'Delete transcript' }))
  await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
  await waitFor(() => expect(deleteTranscript).toHaveBeenCalledWith('therapy/done.m4a.txt'))
  expect(getTranscriptsTree).toHaveBeenCalledTimes(2)
  expect(await screen.findByText(/Select a transcript/)).toBeInTheDocument()
})
it('shows the API error when delete is refused', …)                 // deleteTranscript rejects Error('409 a job is writing this transcript') → text visible, transcript still shown
it('cancel keeps the transcript', …)
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement.** `TranscriptsView`: load with `getTranscriptsTree`; `handleSelectFile` calls `getTranscript(node.path)` directly (no `.txt` append, no `transcribed` check); `handleDelete` calls `deleteTranscript(node.path)`, then reloads the tree and sets `selected`/`content` to null; rethrow so the viewer can show the message. Empty-state copy: tree "No transcripts yet.", viewer "Select a transcript to view it." `TranscriptViewer`: add the buttons, `copied` state with a `setTimeout` cleared on unmount, `confirming` state, `actionError` state; copy error copy: "Could not copy to clipboard."

- [ ] **Step 4: Run** `cd frontend && npx vitest run && npx tsc -b` → PASS.

- [ ] **Step 5: Commit**: `git commit -m "feat(frontend): transcripts tab with copy and delete"`

---

### Task 8: Files tab: upload row and delete-source footer

**Files:**
- Modify: `frontend/src/components/FilePicker.tsx`, `frontend/src/views/TranscribeView.tsx`
- Test: `frontend/src/views/TranscribeView.test.tsx`, `frontend/src/components/FilePicker.test.tsx`

**Interfaces:**
- Consumes: `getCategories`, `uploadFile`, `deleteSourceFile`, `Meta.supported_extensions` (Task 4), `IconButton`.
- Produces: `FilePicker` props `{ nodes, selectedPath, onSelect, categories: string[], accept: string, onUpload: (file: File, category: string) => Promise<void>, onDelete: (node: TreeNode) => Promise<void> }`. Header right: `IconButton label="Upload audio file"` (`Upload` icon) over a hidden `<input type="file" accept={accept} data-testid="upload-input">`. After a file is chosen, a row under the header shows the filename, a `<Select aria-label="Category">` ("(none)" = `""`, then `categories`), buttons "Upload" / "Cancel"; while pending the Upload button reads "Uploading…" and both are disabled; errors render under the row in red; a successful upload closes the row. Footer right: `IconButton label="Delete source file" variant="danger"` (`Trash2`); confirm replaces footer text with "Delete {name}?" + "Delete" / "Cancel"; errors in red in the footer.

- [ ] **Step 1: Failing tests.** `TranscribeView.test.tsx`: extend the `vi.mock` with `getCategories`, `uploadFile`, `deleteSourceFile`; `beforeEach` resolves `getCategories` to `['podcast']`.

```tsx
it('uploads a chosen file into the chosen category and selects it', async () => {
  const file = new File(['x'], 'ep2.mp3', { type: 'audio/mpeg' })
  vi.mocked(uploadFile).mockResolvedValue({ path: 'podcast/ep2.mp3' })
  vi.mocked(getFiles).mockResolvedValueOnce(tree).mockResolvedValueOnce([
    { ...tree[0], children: [...tree[0].children!, { name: 'ep2.mp3', path: 'podcast/ep2.mp3', type: 'file' }] },
  ])
  renderTranscribeView()
  await userEvent.upload(await screen.findByTestId('upload-input'), file)
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Category' }), 'podcast')
  await userEvent.click(screen.getByRole('button', { name: 'Upload' }))
  await waitFor(() => expect(uploadFile).toHaveBeenCalledWith(file, 'podcast'))
  expect(await screen.findByText(/Selected:/)).toHaveTextContent('podcast/ep2.mp3')
})
it('shows the upload error and keeps the row open', …)   // uploadFile rejects Error('409 ep2.mp3 already exists in that category') → text visible, Upload button still present
it('deletes the selected source after confirm and clears the selection', async () => {
  vi.mocked(deleteSourceFile).mockResolvedValue(undefined)
  renderTranscribeView()
  await userEvent.click(await screen.findByText('podcast'))
  await userEvent.click(screen.getByText('ep1.mp3'))
  await userEvent.click(screen.getByRole('button', { name: 'Delete source file' }))
  await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
  await waitFor(() => expect(deleteSourceFile).toHaveBeenCalledWith('podcast/ep1.mp3'))
  expect(getFiles).toHaveBeenCalledTimes(2)
  expect(screen.queryByText(/Selected:/)).not.toBeInTheDocument()
})
it('shows the 409 message when delete is refused', …)   // text /a job is using this file/ visible, selection kept
```

Also assert in one test that the hidden input's `accept` equals `meta.supported_extensions.join(',')` (add `supported_extensions: ['.m4a', '.mp3']` to the test `meta`).

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement.** `TranscribeView`: add `getCategories()` to the initial `Promise.all`; `handleUpload` = `uploadFile` → `getFiles` → `setTree` → `setSelected(findFile(tree, path))`; `handleDelete` = `deleteSourceFile(node.path)` → `getFiles` → `setTree` → `setSelected(null)`; both rethrow for the picker to display. `FilePicker` owns the UI state (`pendingFile`, `category`, `uploading`, `uploadError`, `confirmingDelete`, `deleteError`) and resets it on success. Open the file dialog via a `useRef` to the hidden input and `.click()`.

- [ ] **Step 4: Run** `cd frontend && npx vitest run && npx tsc -b` → PASS.

- [ ] **Step 5: Commit**: `git commit -m "feat(frontend): upload and delete source files from the Files tab"`

---

### Task 9: Docs and end-to-end verification

**Files:**
- Modify: `CLAUDE.md` (project description: tabs are Download / Files / Transcripts; development notes: new endpoints, delete guards, `python-multipart`, `lucide-react`)
- Verify: full suites and a manual smoke run

- [ ] **Step 1: Update `CLAUDE.md`** as above, in the existing style (one bullet per fact).

- [ ] **Step 2: Run everything**

```bash
venv/bin/python -m pytest
cd frontend && npx vitest run && npx tsc -b && npm run build
```
Expected: all PASS, build writes `frontend/dist`.

- [ ] **Step 3: Smoke test** with `NO_BROWSER=1 ./run.sh` in the background: upload a short audio file into a category, confirm it appears and is selected; transcribe it with `tiny`; open the transcript from the badge; copy; delete transcript; delete source. Stop the server.

- [ ] **Step 4: Commit**: `git commit -m "docs: describe Files/Transcripts tabs and file management endpoints"`
