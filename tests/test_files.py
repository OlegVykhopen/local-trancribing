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
