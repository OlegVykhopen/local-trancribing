# Files / Transcripts restructure: upload, delete, copy

Date: 2026-10-28
Status: built (see docs/superpowers/plans/2026-10-28-files-transcripts-restructure.md)

## Intent

The Studio currently has three tabs: Download, Transcribe, Files. "Transcribe"
shows the `audio_sources/` tree plus a form and history; "Files" shows the same
audio tree and renders the transcript for the selected audio file. The user wants
to manage the two folders on disk from the UI (add and remove source audio,
remove transcripts, copy a transcript's text) without touching Finder, and to
stop having two tabs that both start from the audio tree.

The restructure:

- **Files** tab (today's Transcribe) owns everything about *source audio*:
  pick, upload, delete, transcribe.
- **Transcripts** tab (today's Files) owns everything about *transcripts*:
  browse the `transcripts/` folder, read, copy, delete.

Because the Transcripts tab reads the `transcripts/` folder directly, a
transcript stays visible after its source audio is deleted.

## Goals

- Upload an audio file from the local file system into `audio_sources/` or
  `audio_sources/<category>/` from the Files tab.
- Delete a source audio file from the Files tab.
- Browse transcripts by category on the Transcripts tab; open one from the
  Files tab's "already transcribed" badge and from the Job view.
- Copy a transcript's text to the clipboard; delete a transcript.
- All actions are icon buttons with real icons, placed on the right side of the
  panel header or footer they belong to.

## Non-goals

- Renaming or moving files, editing transcripts, bulk actions, drag-and-drop
  upload, upload progress bars, undo / trash.
- Managing categories beyond what exists (create via the Download tab).
- Changing the CLI, the worker, or the transcript file format.

## Anti-goals

- Silent overwrite on upload. Same-name file in the target folder is an error.
- Deleting a file a job is still using. Delete is refused while a queued or
  running transcribe job references the file.
- Any path escaping `audio_sources/` or `transcripts/` via the new endpoints.

## Constraints

- Keep existing stack: FastAPI backend, React + TS + Vite + Tailwind frontend.
  Services under `app/services/` must stay free of `app.config` imports and take
  roots as parameters (see docstring in `app/services/files.py`) so tests run
  against `tmp_path`.
- Tests: backend pytest in `tests/`, frontend vitest. New behaviour gets tests
  in both suites. `cd frontend && npx tsc -b` must pass.
- `python-multipart` is not installed in `venv/`; FastAPI needs it for
  `UploadFile`. Add it to `requirements.txt` and install it.
- Transcript naming convention is fixed: `transcripts/<rel-dir>/<audio-name>.txt`
  (the audio filename *including* its extension, plus `.txt`). Deleting a source
  audio file must not touch its transcript and vice versa.

## Decisions (as decided with the user)

### Navigation and routes

| Today | New |
|---|---|
| nav "Transcribe" → `/transcribe` | nav "Files" → `/files` |
| nav "Files" → `/files` | nav "Transcripts" → `/transcripts` |

Nav order: Download · Files · Transcripts. `/` and unknown routes redirect to
`/files`. Add a `<Navigate>` route from `/transcribe` to `/files` for
bookmarks only. The Job view's Retry button must be changed to navigate to
`/files` directly (with the same `state: { retry }`), because a `<Navigate>`
redirect drops router state. Update `JobView.test.tsx` accordingly.

Deep links:

- `/transcripts?path=<rel path of .txt under transcripts/>` selects and opens
  that transcript, then consumes the param (same pattern as today's
  `/files?path=`).
- `/files?path=<rel audio path>` selects that audio file in the picker (keeps
  Retry prefill behaviour via router state as today).

The Job view's "View transcript" button and the Files-tab history card's
"view transcript →" link both navigate to `/transcripts?path=<audio rel
path>.txt`.

### Files tab (today's TranscribeView, renamed in nav only; component files may
keep or change their names, builder's call)

Layout unchanged: picker card (left) · form card · history card (right).

1. **Upload icon button** on the right of the picker header ("Pick a file"),
   `lucide-react` `Upload` icon.
   - Click opens the native file dialog (hidden `<input type="file">`, `accept`
     limited to the supported extensions). The extension list comes from
     `/api/meta` as a new `supported_extensions: string[]` field (source of
     truth stays `transcribe.SUPPORTED_EXTENSIONS`); add it to `Meta` in
     `types.ts`.
   - After a file is chosen, a small inline row appears under the header:
     category `<Select>` (options from `/api/categories`, plus "(none)" = root;
     default "(none)") and a confirm "Upload" button, plus a cancel. The chosen
     filename is shown in that row.
   - On confirm: `POST /api/files/upload` (multipart). While uploading the row
     shows "Uploading…" and the buttons are disabled.
   - On success: refetch the tree, select the uploaded file in the picker.
   - On error (409 duplicate, 400 bad extension, 413 etc.): show the message
     inline in the row; the row stays open so the user can change category.
2. **Delete-source icon button** on the right of the "Selected: <path>" footer
   row, `Trash2` icon. Click swaps the row content to "Delete <name>? [Delete]
   [Cancel]" (inline confirm, no browser `confirm()`). Confirm calls
   `DELETE /api/files?path=…`. On success: refetch tree, clear selection. On
   409 (job in flight) or other error: show message in the footer row.
3. **"already transcribed" badge becomes a link** to
   `/transcripts?path=<audio rel path>.txt`. `FileTree` renders each file row
   as a `<button>`, and an `<a>` inside a `<button>` is invalid HTML, so the
   row needs restructuring: render the row as a `<div>`/`<li>` with the name
   as the clickable button and the badge as a sibling `<a>`, keeping the
   `file-row` test id on the element that selects the file. Clicking the badge
   must not also select the file. Keep the badge's look; add hover affordance
   (underline or colour shift).

### Transcripts tab (today's FilesView)

Left card header: "Transcripts". Tree built from `GET /api/transcripts`, which
lists the `transcripts/` folder: dirs first then `.txt` files, same `TreeNode`
shape as `/api/files` with `transcribed` omitted. Empty state: "No transcripts
yet."

Right card: `TranscriptViewer` as today, header shows file name and relative
path. Two icon buttons on the right of the header:

1. **Copy** (`Copy` icon). Writes the transcript text to the clipboard via
   `navigator.clipboard.writeText`. On success the icon switches to `Check`
   for ~1.5 s with an accessible label "Copied". Disabled while loading or
   when there is no content. If the clipboard API rejects, show a short inline
   error next to the buttons.
2. **Delete** (`Trash2` icon). Inline confirm in the header ("Delete this
   transcript? [Delete] [Cancel]"). Confirm calls
   `DELETE /api/transcripts?path=…`. On success: refetch tree, clear selection,
   viewer returns to its empty state. On error: inline message.

Selecting a transcript in the tree fetches it with the existing
`GET /api/transcript?path=` endpoint (path is now the `.txt` rel path directly).

### Backend

All new service functions live in `app/services/files.py`, take explicit
roots, raise `ValueError` for caller mistakes (mapped to 4xx at the route, same
pattern as `create_category`), and reuse the existing resolve +
`is_relative_to(root)` escape check.

| Route | Behaviour |
|---|---|
| `GET /api/transcripts` | `{tree: [...]}` of `transcripts/` (dirs + `*.txt`). Same node shape as `/api/files`, no `transcribed` field. |
| `POST /api/files/upload` | Multipart: `file` (UploadFile), `category` (form field, `""` = root). Validates: category exists as a dir under `audio_root` (or is empty); filename has a supported extension (case-insensitive); filename is a bare name (no path separators, not `.`/`..`). Target = `audio_root / category / filename`. 409 if target exists. Streams to a temp file in the target dir then renames into place. Returns 201 `{path: "<category>/<filename>"}` (no leading slash; just `<filename>` for root). |
| `DELETE /api/files?path=…` | Deletes one audio file under `audio_root`. 404 if missing, 400 if path escapes or is a dir. 409 with detail `"a job is using this file"` if any job with `kind == "transcribe"` and status in `queued`, `running`, `cancelling` has `params.path == path`. Returns 204. |
| `DELETE /api/transcripts?path=…` | Deletes one `.txt` under `transcripts_root`. 404 if missing, 400 if path escapes / not a file / not `.txt`. 409 `"a job is writing this transcript"` if a transcribe job for the matching audio path is `running` or `cancelling` (the worker writes the transcript at the very end, so a mid-run delete would silently reappear). A merely `queued` job does *not* block: deleting the transcript first is exactly how the user forces a re-transcribe, and the Job view's copy already says so. Returns 204. |

The job-in-flight check needs a small `db` helper (e.g.
`list_active_transcribe_jobs(conn)` returning `(status, params.path)` pairs, or
a filtered `list_jobs`), builder's design. The `pipeline` job kind has no
handler and is never created by any route; ignore it.

Matching audio path for a transcript `<rel-dir>/<name>.txt` is
`<rel-dir>/<name>` (strip the trailing `.txt` only).

Upload size: no explicit limit (local app). Don't buffer the whole file in
memory; use `shutil.copyfileobj` from `UploadFile.file`.

### Icons and styling

- Add `lucide-react` to `frontend/package.json` dependencies (pin whatever
  current stable `npm` resolves). Icons: `Upload`, `Trash2`, `Copy`, `Check`,
  `X` as needed.
- Add an `IconButton` component in `frontend/src/components/ui/` : `size-8`
  rounded-md, `variant="ghost"` look (transparent, `hover:bg-zinc-800`,
  `text-zinc-400 hover:text-zinc-100`), a `danger` variant for delete
  (`hover:text-red-400 hover:bg-red-500/10`), `disabled:opacity-50`. Each
  instance has an `aria-label` and a native `title` tooltip. Icons at 16 px.
- Inline confirm rows use the existing `Button` (`outline` for cancel, a small
  red-tinted variant or `className` override for the destructive confirm).

### Frontend API (`frontend/src/lib/api.ts`)

Add `getTranscriptsTree()`, `uploadFile(file, category)` (FormData, no
`Content-Type` header so the browser sets the boundary), `deleteSourceFile(path)`,
`deleteTranscript(path)`. 204 responses must not be `.json()`-parsed: extend
`request()` to return `undefined` on 204.

### Tests (minimum)

Backend (`tests/`), using `tmp_path` roots and a per-file `client` fixture
built with `create_app` like `tests/test_api_files.py`. For the 409 tests,
follow `tests/test_api_transcribe.py`: register a fake `transcribe` handler on
`app.state.worker` that blocks on a `threading.Event` to hold a job in
`running`.

- transcripts tree lists dirs and `.txt` only, sorted, nested.
- `/api/meta` includes `supported_extensions`.
- upload: happy path root and category; 409 duplicate; 400 bad extension; 400
  unknown category; 400 filename with `/` or `..`.
- delete source: 204 and file gone; 404 missing; 400 escape; 409 when an
  active transcribe job references the path; transcript untouched.
- delete transcript: 204; 404; 400 escape; 400 non-txt; audio untouched; 409
  while a transcribe job for that audio is running; 204 while one is only queued.

Frontend (vitest):

- Files tab: badge link href; upload flow calls `uploadFile` with chosen
  category and refreshes/selects; delete-source confirm → `deleteSourceFile`
  → tree refetch and selection cleared; 409 message shown.
- Transcripts tab: `?path=` deep link selects and loads; copy writes to
  clipboard and shows "Copied"; delete confirm → `deleteTranscript` → viewer
  empties.
- Existing `FilesView.test.tsx` / `TranscribeView.test.tsx` updated for the
  renames and new endpoints.

Update `CLAUDE.md` (project structure and development notes) and the nav
description to the new tab names and endpoints.

## Left to the builder

- Component/file naming after the rename (keep git history readable; a rename
  with `git mv` is fine).
- Exact placement/markup of the inline upload row and confirm rows, as long as
  they stay inside the card they belong to and don't shift the tree.
- Whether `IconButton` wraps `Button` or is standalone.
- Shape of the db helper for the active-job check.
- Temp-file naming for the upload (must live in the target dir so the final
  rename is atomic on the same filesystem).
