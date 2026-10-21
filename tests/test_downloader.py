from pathlib import Path

import pytest
import yt_dlp

from app.services import downloader
from app.worker import JobCancelled


class FakeContext:
    """Stand-in for JobContext: records progress calls, lets tests drive cancellation."""

    def __init__(self):
        self.progress_calls = []
        self.logs = []
        self.cancelled = False

    def progress(self, percent, stage, detail=""):
        self.progress_calls.append((percent, stage, detail))

    def log(self, line):
        self.logs.append(line)

    def check_cancelled(self):
        if self.cancelled:
            raise JobCancelled()


def test_opts_built_correctly(tmp_path, monkeypatch):
    captured = {}

    class FakeYDL:
        def __init__(self, opts):
            captured.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def download(self, urls):
            captured["urls"] = urls

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)

    audio_root = tmp_path / "audio"
    audio_root.mkdir()
    ctx = FakeContext()
    params = {"url": "https://youtu.be/abc", "category": "lectures", "format": "audio"}

    # This fake never produces a file, so run_download raises at the end —
    # the opts under test are captured before that.
    with pytest.raises(RuntimeError, match="no output file"):
        downloader.run_download(params, ctx, audio_root)

    target_dir = audio_root / "lectures"
    assert target_dir.is_dir()
    assert captured["format"] == "bestaudio"
    assert captured["outtmpl"] == str(target_dir / "%(title)s [%(id)s].%(ext)s")
    assert captured["ffmpeg_location"]
    assert captured["noplaylist"] is True
    assert captured["urls"] == ["https://youtu.be/abc"]
    assert any(pp["key"] == "FFmpegExtractAudio" for pp in captured["postprocessors"])


def test_progress_hook_maps_to_ctx(tmp_path, monkeypatch):
    hooks = {}

    class FakeYDL:
        def __init__(self, opts):
            hooks["hook"] = opts["progress_hooks"][0]

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def download(self, urls):
            hook = hooks["hook"]
            hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 200, "speed": 1048576, "eta": 65})
            hook({"status": "downloading", "downloaded_bytes": 10, "total_bytes_estimate": 100})
            hook({"status": "downloading", "downloaded_bytes": 10})
            output = tmp_path / "audio" / "x.webm"
            output.write_bytes(b"audio")
            hook({"status": "finished", "filename": str(output)})

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)

    audio_root = tmp_path / "audio"
    audio_root.mkdir()
    ctx = FakeContext()
    params = {"url": "u", "category": "", "format": "audio"}

    downloader.run_download(params, ctx, audio_root)

    assert ctx.progress_calls[0][0] == pytest.approx(25.0)
    assert ctx.progress_calls[0][1] == "downloading"
    assert "MiB/s" in ctx.progress_calls[0][2]
    assert "ETA" in ctx.progress_calls[0][2]

    assert ctx.progress_calls[1][0] == pytest.approx(10.0)
    assert ctx.progress_calls[1][1] == "downloading"

    assert ctx.progress_calls[2][0] == 0
    assert ctx.progress_calls[2][1] == "downloading"
    assert ctx.progress_calls[2][2] == ""

    assert ctx.progress_calls[3] == (100, "postprocessing", "")


def test_cancel_during_download_cleans_part_files(tmp_path, monkeypatch):
    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def download(self, urls):
            target_dir = Path(self.opts["outtmpl"]).parent
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "video.part").write_bytes(b"x")
            (target_dir / "video.ytdl").write_bytes(b"x")
            ctx.cancelled = True
            self.opts["progress_hooks"][0](
                {"status": "downloading", "downloaded_bytes": 10, "total_bytes": 100}
            )

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)

    audio_root = tmp_path / "audio"
    audio_root.mkdir()
    ctx = FakeContext()
    params = {"url": "u", "category": "", "format": "audio"}

    with pytest.raises(JobCancelled):
        downloader.run_download(params, ctx, audio_root)

    assert list(audio_root.glob("*.part")) == []
    assert list(audio_root.glob("*.ytdl")) == []


def test_downloaderror_becomes_runtimeerror_with_message(tmp_path, monkeypatch):
    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def download(self, urls):
            target_dir = Path(self.opts["outtmpl"]).parent
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "stub.part").write_bytes(b"x")
            raise yt_dlp.utils.DownloadError("Unsupported URL: garbage")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)

    audio_root = tmp_path / "audio"
    audio_root.mkdir()
    ctx = FakeContext()
    params = {"url": "garbage", "category": "", "format": "audio"}

    with pytest.raises(RuntimeError, match="Unsupported URL: garbage"):
        downloader.run_download(params, ctx, audio_root)

    assert list(audio_root.glob("*.part")) == []


def test_result_lists_relative_paths(tmp_path, monkeypatch):
    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def download(self, urls):
            target_dir = Path(self.opts["outtmpl"]).parent
            target_dir.mkdir(parents=True, exist_ok=True)
            webm_path = target_dir / "My Video [abc123].webm"
            mp3_path = target_dir / "My Video [abc123].mp3"
            mp3_path.write_bytes(b"audio-data")
            self.opts["progress_hooks"][0]({"status": "finished", "filename": str(webm_path)})

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)

    audio_root = tmp_path / "audio"
    audio_root.mkdir()
    ctx = FakeContext()
    params = {"url": "u", "category": "podcasts", "format": "audio"}

    result = downloader.run_download(params, ctx, audio_root)

    assert result == {"files": ["podcasts/My Video [abc123].mp3"]}


def test_download_with_no_locatable_output_raises(tmp_path, monkeypatch):
    """A download that yt-dlp reports as successful but which leaves no file
    on disk must fail the job, not complete 'done' with an empty file list."""

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def download(self, urls):
            # finished hook fires, but neither the raw file nor the .mp3 exists
            self.opts["progress_hooks"][0](
                {"status": "finished", "filename": str(tmp_path / "audio" / "ghost.webm")}
            )

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)

    audio_root = tmp_path / "audio"
    audio_root.mkdir()
    ctx = FakeContext()
    params = {"url": "u", "category": "", "format": "audio"}

    with pytest.raises(RuntimeError, match="no output file"):
        downloader.run_download(params, ctx, audio_root)
    assert any("not found on disk" in line for line in ctx.logs)
