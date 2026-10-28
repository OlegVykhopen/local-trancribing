import io
import os

import pytest

from app.services import files


@pytest.fixture
def roots(tmp_path):
    """Build a small audio/transcripts tree under tmp_path.

    audio/therapy/a.m4a               -> transcribed
    audio/consulting/marketing/b.mp3  -> transcribed (nested 2 levels)
    audio/c.mp3                       -> loose, not transcribed
    """
    audio_root = tmp_path / "audio_sources"
    transcripts_root = tmp_path / "transcripts"
    audio_root.mkdir()
    transcripts_root.mkdir()

    (audio_root / "therapy").mkdir()
    (audio_root / "therapy" / "a.m4a").write_bytes(b"")
    (audio_root / "consulting" / "marketing").mkdir(parents=True)
    (audio_root / "consulting" / "marketing" / "b.mp3").write_bytes(b"")
    (audio_root / "c.mp3").write_bytes(b"")

    (transcripts_root / "therapy").mkdir()
    (transcripts_root / "therapy" / "a.m4a.txt").write_text("transcript a")
    (transcripts_root / "consulting" / "marketing").mkdir(parents=True)
    (transcripts_root / "consulting" / "marketing" / "b.mp3.txt").write_text("transcript b")

    return audio_root, transcripts_root


def test_tree_transcribed_flags_nested_and_root(roots):
    audio_root, transcripts_root = roots
    tree = files.list_tree(audio_root, transcripts_root)

    expected = [
        {
            "name": "consulting",
            "path": "consulting",
            "type": "dir",
            "children": [
                {
                    "name": "marketing",
                    "path": "consulting/marketing",
                    "type": "dir",
                    "children": [
                        {
                            "name": "b.mp3",
                            "path": "consulting/marketing/b.mp3",
                            "type": "file",
                            "transcribed": True,
                        },
                    ],
                },
            ],
        },
        {
            "name": "therapy",
            "path": "therapy",
            "type": "dir",
            "children": [
                {"name": "a.m4a", "path": "therapy/a.m4a", "type": "file", "transcribed": True},
            ],
        },
        {"name": "c.mp3", "path": "c.mp3", "type": "file", "transcribed": False},
    ]
    assert tree == expected


def test_tree_ignores_unsupported_extensions(roots):
    audio_root, transcripts_root = roots
    (audio_root / "notes.txt").write_text("not an audio file")
    (audio_root / "therapy" / "readme.md").write_text("also not audio")

    tree = files.list_tree(audio_root, transcripts_root)

    names = {node["name"] for node in tree if node["type"] == "file"}
    assert "notes.txt" not in names

    therapy = next(node for node in tree if node["name"] == "therapy")
    therapy_file_names = {child["name"] for child in therapy["children"]}
    assert therapy_file_names == {"a.m4a"}


def test_list_categories_top_level_only(roots):
    audio_root, _transcripts_root = roots
    assert files.list_categories(audio_root) == ["consulting", "therapy"]


def test_create_category_valid_and_invalid(roots):
    audio_root, transcripts_root = roots

    files.create_category(audio_root, transcripts_root, "podcast")
    assert (audio_root / "podcast").is_dir()
    assert (transcripts_root / "podcast").is_dir()

    with pytest.raises(ValueError):
        files.create_category(audio_root, transcripts_root, "../evil")

    with pytest.raises(ValueError):
        files.create_category(audio_root, transcripts_root, "podcast\n")


def test_create_category_cyrillic_name(roots):
    audio_root, transcripts_root = roots

    files.create_category(audio_root, transcripts_root, "терапия")

    assert (audio_root / "терапия").is_dir()
    assert (transcripts_root / "терапия").is_dir()


def test_read_transcript_blocks_traversal(roots):
    _audio_root, transcripts_root = roots

    with pytest.raises(ValueError):
        files.read_transcript(transcripts_root, "../.env")

    with pytest.raises(ValueError):
        files.read_transcript(transcripts_root, "therapy/does-not-exist.m4a.txt")


def test_read_transcript_cyrillic_filename(roots):
    _audio_root, transcripts_root = roots
    (transcripts_root / "терапия").mkdir()
    (transcripts_root / "терапия" / "сеанс.m4a.txt").write_text("привет мир", encoding="utf-8")

    content = files.read_transcript(transcripts_root, "терапия/сеанс.m4a.txt")

    assert content == "привет мир"


def test_transcripts_tree_lists_txt_only(roots):
    _, transcripts_root = roots
    (transcripts_root / ".DS_Store").write_bytes(b"")
    (transcripts_root / "therapy" / "notes.json").write_text("{}")
    tree = files.list_transcripts_tree(transcripts_root)
    assert tree == [
        {
            "name": "consulting",
            "path": "consulting",
            "type": "dir",
            "children": [
                {
                    "name": "marketing",
                    "path": "consulting/marketing",
                    "type": "dir",
                    "children": [
                        {"name": "b.mp3.txt", "path": "consulting/marketing/b.mp3.txt", "type": "file"},
                    ],
                },
            ],
        },
        {
            "name": "therapy",
            "path": "therapy",
            "type": "dir",
            "children": [
                {"name": "a.m4a.txt", "path": "therapy/a.m4a.txt", "type": "file"},
            ],
        },
    ]


def test_save_upload_into_category_and_root(roots):
    audio_root, _ = roots
    rel = files.save_upload(audio_root, "therapy", "new.MP3", io.BytesIO(b"abc"))
    assert rel == "therapy/new.MP3"
    assert (audio_root / "therapy" / "new.MP3").read_bytes() == b"abc"
    assert files.save_upload(audio_root, "", "loose.wav", io.BytesIO(b"x")) == "loose.wav"
    assert not list(audio_root.glob("**/.upload-*"))  # no temp files left behind


@pytest.mark.parametrize(
    "category,filename",
    [
        ("therapy", "notes.txt"),  # unsupported extension
        ("therapy", "../a.m4a"),  # path separator
        ("therapy", ".."),
        ("nope", "a.m4a"),  # unknown category
        ("../etc", "a.m4a"),  # category escape
    ],
)
def test_save_upload_rejects(roots, category, filename):
    audio_root, _ = roots
    with pytest.raises(ValueError):
        files.save_upload(audio_root, category, filename, io.BytesIO(b""))


def test_save_upload_duplicate_is_file_exists(roots):
    audio_root, _ = roots
    with pytest.raises(FileExistsError):
        files.save_upload(audio_root, "therapy", "a.m4a", io.BytesIO(b"new"))
    assert (audio_root / "therapy" / "a.m4a").read_bytes() == b""


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


def test_save_upload_file_mode_respects_umask(roots):
    audio_root, _ = roots
    files.save_upload(audio_root, "therapy", "perm.mp3", io.BytesIO(b"x"))
    mode = (audio_root / "therapy" / "perm.mp3").stat().st_mode & 0o777
    umask = os.umask(0)
    os.umask(umask)
    assert mode == 0o666 & ~umask  # same as a regular open(..., "wb"), not tempfile's 0600
