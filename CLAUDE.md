# Local Audio Transcription with Speaker Diarization

## What this project does

A CLI tool that transcribes audio files locally using WhisperX with optional speaker diarization (who said what). Everything runs on-device — no cloud APIs, no costs.

## How it works

1. User places audio files in `audio_sources/` or passes them as CLI arguments
2. WhisperX transcribes the audio using a local Whisper model
3. Timestamps are aligned at the word level
4. If a HuggingFace token is provided, pyannote performs speaker diarization (identifies who is speaking)
5. Output is saved as timestamped text files in `transcripts/`

Output format: `[HH:MM:SS - HH:MM:SS] SPEAKER_XX: transcribed text`

## Project structure

- `transcribe.py` — single-file CLI tool (all logic lives here)
- `audio_sources/` — default input directory for audio files
- `transcripts/` — default output directory for transcription results
- `.env` / `.env.example` — HuggingFace token (`HF_TOKEN`) for speaker diarization
- `venv/` — Python 3.13 virtual environment

## Key technical details

- **Runtime**: Python 3.13, uses a local `venv/`
- **Device**: Runs on CPU with `int8` compute type (even on Apple Silicon Macs — WhisperX diarization works best on CPU)
- **Supported formats**: mp3, wav, m4a, flac, ogg, wma, aac, webm, mp4
- **Models**: Whisper model sizes from `tiny` to `large-v3` (default: `base`)
- **Dependencies**: whisperx, torch, pyannote (via whisperx), python-dotenv
- **ffmpeg**: Requires ffmpeg@7 on macOS (`/opt/homebrew/opt/ffmpeg@7/lib` is set via `DYLD_LIBRARY_PATH`)

## CLI usage

```bash
# Transcribe all files in audio_sources/
python transcribe.py

# Transcribe specific files
python transcribe.py recording.mp3 interview.wav

# Use a larger model for better accuracy
python transcribe.py -m large-v3

# Pre-download models for offline use
python transcribe.py setup
```

## Development notes

- Existing transcripts are skipped (won't re-transcribe if output file exists)
- Language is auto-detected unless `-l` is specified
- Speaker diarization is optional — works without `HF_TOKEN` but won't separate speakers
