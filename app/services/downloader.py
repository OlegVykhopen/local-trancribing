"""YouTube audio download service, executed inside the worker thread.

Downloads a single video's audio via yt-dlp into audio_root/category,
reporting live progress through a JobContext and supporting cooperative
cancellation (JobContext.check_cancelled() raises JobCancelled, which
propagates out of yt-dlp's download() call via the progress hook).

MVP scope: audio-only (yt-dlp format "bestaudio" + FFmpegExtractAudio
postprocessor to mp3), single video (noplaylist=True). No playlist support,
no format selection beyond audio.
"""

from pathlib import Path

import yt_dlp

from app import config
from app.worker import JobCancelled


def _human_speed(speed) -> str:
    if not speed:
        return ""
    return f"{speed / 1024 / 1024:.2f} MiB/s"


def _human_eta(eta) -> str:
    if eta is None:
        return ""
    minutes, seconds = divmod(int(eta), 60)
    if minutes:
        return f"ETA {minutes}m{seconds:02d}s"
    return f"ETA {seconds}s"


def _format_detail(d: dict) -> str:
    parts = [p for p in (_human_speed(d.get("speed")), _human_eta(d.get("eta"))) if p]
    return " ".join(parts)


def _cleanup_litter(target_dir: Path) -> None:
    """Remove partial-download litter (*.part, *.ytdl) from target_dir.

    Scoped to the whole directory rather than this job's specific filename:
    acceptable for MVP because the queue is sequential (one job runs at a
    time), so any such file present when a job fails or is cancelled
    belongs to that job.
    """
    for pattern in ("*.part", "*.ytdl"):
        for path in target_dir.glob(pattern):
            path.unlink(missing_ok=True)


def run_download(
    params: dict,
    ctx,
    audio_root: Path,
    ffmpeg_location: str = config.FFMPEG_LOCATION,
) -> dict:
    """Download a YouTube video's audio into audio_root/category.

    params: {"url": str, "category": str | "", "format": "audio"}.
    Returns {"files": [relative POSIX paths under audio_root]}.
    Raises JobCancelled if ctx is cancelled mid-download, or RuntimeError
    (wrapping yt-dlp's DownloadError message) on a bad URL/download failure.
    """
    url = params["url"]
    category = params.get("category") or ""
    target_dir = audio_root / category if category else audio_root
    target_dir.mkdir(parents=True, exist_ok=True)

    finished_filenames: list[str] = []

    def hook(d: dict) -> None:
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes") or 0
            percent = (downloaded / total * 100) if total else 0
            ctx.progress(percent, "downloading", _format_detail(d))
            ctx.check_cancelled()
        elif status == "finished":
            filename = d.get("filename")
            if filename:
                finished_filenames.append(filename)
            ctx.progress(100, "postprocessing")

    opts = {
        "format": "bestaudio",
        "outtmpl": str(target_dir / "%(title)s [%(id)s].%(ext)s"),
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
        "ffmpeg_location": ffmpeg_location,
        "progress_hooks": [hook],
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except JobCancelled:
        _cleanup_litter(target_dir)
        raise
    except yt_dlp.utils.DownloadError as exc:
        _cleanup_litter(target_dir)
        raise RuntimeError(str(exc)) from exc

    files = []
    for filename in finished_filenames:
        # The "finished" hook fires on the raw download, before
        # FFmpegExtractAudio converts it to mp3 — map to the post-processed
        # extension to find the file that actually ends up on disk.
        final_path = Path(filename).with_suffix(".mp3")
        if not final_path.exists():
            final_path = Path(filename)
        if final_path.exists():
            files.append(final_path.relative_to(audio_root).as_posix())
        else:
            ctx.log(f"Downloaded file not found on disk: {filename}")

    if not files:
        # yt-dlp reported success but nothing usable landed on disk (e.g. the
        # postprocessor failed quietly, or the finished hook never fired).
        # Completing "done" with an empty file list would read as success.
        raise RuntimeError("download finished but no output file was found")

    return {"files": files}
