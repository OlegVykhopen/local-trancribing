"""File-tree, category, and transcript-reading services for the Transcribing Studio.

Every function here takes audio_root / transcripts_root explicitly as parameters
(this module must not import app.config) so it can be exercised against tmp_path
fixtures in tests without ever touching the real audio_sources/ or transcripts/
directories, which hold personal data.
"""

import ast
import re
from pathlib import Path

_TRANSCRIBE_PY = Path(__file__).resolve().parents[2] / "transcribe.py"

_CATEGORY_NAME_RE = re.compile(r"^[\w\- ]{1,64}$", re.UNICODE)


def _load_supported_extensions() -> frozenset[str]:
    """Read SUPPORTED_EXTENSIONS out of transcribe.py's source without importing it.

    A real `import transcribe` transitively imports whisperx -> pyannote.audio ->
    pyannote's telemetry module, which currently fails to import in this venv due
    to a pre-existing, unrelated opentelemetry-api/opentelemetry-sdk version skew
    (api 1.45.1 installed for fastapi vs sdk/exporters pinned to 1.41.0 by
    pyannote's own otel dependency -- the two requirements are mutually
    exclusive). Pulling in the whole ML stack just to read a constant set of file
    extensions is also unnecessary weight for a lightweight file-listing service.
    Parsing transcribe.py's AST reads the real source of truth with no risk of
    drift, and keeps this module free of heavy/broken dependencies.
    """
    tree = ast.parse(_TRANSCRIBE_PY.read_text(encoding="utf-8"), filename=str(_TRANSCRIBE_PY))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "SUPPORTED_EXTENSIONS"
            for target in node.targets
        ):
            return frozenset(ast.literal_eval(node.value))
    raise RuntimeError(f"SUPPORTED_EXTENSIONS not found in {_TRANSCRIBE_PY}")


SUPPORTED_EXTENSIONS = _load_supported_extensions()


def _is_transcribed(audio_file: Path, audio_root: Path, transcripts_root: Path) -> bool:
    rel_dir = audio_file.relative_to(audio_root).parent
    transcript_path = transcripts_root / rel_dir / (audio_file.name + ".txt")
    return transcript_path.is_file()


def _build_tree(directory: Path, audio_root: Path, transcripts_root: Path) -> list[dict]:
    entries = list(directory.iterdir())
    dirs = sorted((e for e in entries if e.is_dir()), key=lambda p: p.name)
    audio_files = sorted(
        (e for e in entries if e.is_file() and e.suffix.lower() in SUPPORTED_EXTENSIONS),
        key=lambda p: p.name,
    )

    nodes = []
    for d in dirs:
        nodes.append(
            {
                "name": d.name,
                "path": d.relative_to(audio_root).as_posix(),
                "type": "dir",
                "children": _build_tree(d, audio_root, transcripts_root),
            }
        )
    for f in audio_files:
        nodes.append(
            {
                "name": f.name,
                "path": f.relative_to(audio_root).as_posix(),
                "type": "file",
                "transcribed": _is_transcribed(f, audio_root, transcripts_root),
            }
        )
    return nodes


def list_tree(audio_root: Path, transcripts_root: Path) -> list[dict]:
    """Recursively list audio_root as a tree of dir/file nodes.

    Dirs are listed before files at each level; each group is sorted by name.
    Only files with a SUPPORTED_EXTENSIONS suffix are included.
    """
    return _build_tree(audio_root, audio_root, transcripts_root)


def list_categories(audio_root: Path) -> list[str]:
    """Return the sorted names of top-level directories under audio_root."""
    return sorted(p.name for p in audio_root.iterdir() if p.is_dir())


def create_category(audio_root: Path, transcripts_root: Path, name: str) -> None:
    """Create a category directory of the given name in both roots.

    Raises ValueError if name doesn't match ^[\\w\\- ]{1,64}$ (unicode-aware).
    """
    if not _CATEGORY_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid category name: {name!r}")
    (audio_root / name).mkdir(parents=True, exist_ok=True)
    (transcripts_root / name).mkdir(parents=True, exist_ok=True)


def read_transcript(transcripts_root: Path, rel_path: str) -> str:
    """Read a transcript file's text content, given a path relative to transcripts_root.

    Raises ValueError if the resolved path escapes transcripts_root, or if the
    file doesn't exist.
    """
    root = transcripts_root.resolve()
    candidate = (transcripts_root / rel_path).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"path escapes transcripts root: {rel_path!r}")
    if not candidate.is_file():
        raise ValueError(f"transcript not found: {rel_path!r}")
    return candidate.read_text(encoding="utf-8")
