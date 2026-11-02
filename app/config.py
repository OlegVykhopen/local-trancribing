from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).parent.parent
AUDIO_ROOT = BASE_DIR / "audio_sources"
TRANSCRIPTS_ROOT = BASE_DIR / "transcripts"
DB_PATH = BASE_DIR / "app.db"
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"

# Server config
PORT = 8756
HOST = "127.0.0.1"

# External tools.
# yt-dlp needs the ffmpeg *binary*; the ffmpeg@7 DYLD_LIBRARY_PATH set in
# run.sh / transcribe.py is only for torchcodec's libraries — two different
# ffmpeg roles, deliberately not unified.
FFMPEG_LOCATION = "/opt/homebrew/bin/ffmpeg"

# Whisper models
WHISPER_MODELS = ["tiny", "base", "small", "medium", "large", "large-v3"]
