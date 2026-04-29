# Local Audio Transcription with Speaker Diarization

A CLI tool that transcribes audio files locally using [WhisperX](https://github.com/m-bain/whisperX) with optional speaker diarization (who said what). Everything runs on-device -- no cloud APIs, no costs.

## Output format

```
[00:00:05 - 00:00:12] SPEAKER_00: Hello, thanks for joining today.
[00:00:12 - 00:00:18] SPEAKER_01: Thanks for having me. Let's get started.
```

## Prerequisites

- Python 3.13+
- ffmpeg 7 (`brew install ffmpeg@7` on macOS)
- (Optional) [HuggingFace](https://huggingface.co) account + token for speaker diarization

## Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install whisperx python-dotenv

# (Optional) Configure speaker diarization
cp .env.example .env
# Edit .env and add your HuggingFace token
```

To enable speaker diarization, you need a free HuggingFace token:

1. Create an account at https://huggingface.co
2. Accept model terms at https://huggingface.co/pyannote/speaker-diarization-3.1
3. Accept model terms at https://huggingface.co/pyannote/segmentation-3.0
4. Get your token at https://huggingface.co/settings/tokens
5. Add it to `.env`: `HF_TOKEN=hf_your_token_here`

### Pre-download models for offline use

```bash
python transcribe.py setup
python transcribe.py setup -m large-v3  # for a specific model size
```

## Usage

### Basic transcription

```bash
# Transcribe all files in audio_sources/
python transcribe.py

# Transcribe specific files
python transcribe.py recording.mp3 interview.wav

# Use a larger model for better accuracy
python transcribe.py -m large-v3

# Specify language (skips auto-detection)
python transcribe.py -l en recording.mp3
```

### Performance optimization

```bash
# --fast preset: uses all CPU cores + prefetch workers (no accuracy loss)
python transcribe.py --fast recording.mp3

# Best settings for a known 2-speaker dialogue
python transcribe.py --fast -l en --num-speakers 2 interview.mp3

# Manual thread control
python transcribe.py --threads 8 --num-workers 2 recording.mp3

# Trade accuracy for speed (beam_size=1 is greedy decoding)
python transcribe.py --beam-size 1 recording.mp3
```

### Speaker diarization options

```bash
# Exact speaker count (significantly speeds up diarization)
python transcribe.py --num-speakers 2 interview.mp3

# Speaker count range
python transcribe.py --min-speakers 2 --max-speakers 5 meeting.mp3

# Skip diarization even with HF_TOKEN set
python transcribe.py --no-diarize recording.mp3
```

## All options

| Option | Default | Description |
|---|---|---|
| `files` | all in `audio_sources/` | Audio file(s) to transcribe |
| `-m, --model` | `base` | Whisper model size: `tiny`, `base`, `small`, `medium`, `large`, `large-v3` |
| `-o, --output` | `transcripts/` | Output directory |
| `-l, --language` | auto-detect | Language code (e.g. `en`, `uk`, `de`) |
| `--hf-token` | from `HF_TOKEN` env | HuggingFace token for speaker diarization |
| `--no-diarize` | off | Skip speaker diarization |
| `--batch-size` | `16` | Transcription batch size. Lower if running out of memory |
| `--threads` | `4` | CPU threads for inference (`--fast` auto-detects optimal) |
| `--num-workers` | `0` | DataLoader prefetch workers (`--fast` auto-detects optimal) |
| `--num-speakers` | none | Exact number of speakers (speeds up diarization) |
| `--min-speakers` | none | Minimum speakers for diarization |
| `--max-speakers` | none | Maximum speakers for diarization |
| `--beam-size` | `5` | Beam search width. Lower is faster but less accurate |
| `--fast` | off | Preset: optimal threads + prefetch. No accuracy loss |

## How it works

1. Audio is loaded and decoded via ffmpeg (resampled to 16kHz mono)
2. WhisperX transcribes the audio using a local Whisper model (int8 on CPU)
3. Word-level timestamps are aligned using a wav2vec2 model
4. If a HuggingFace token is provided, pyannote performs speaker diarization
5. Output is saved as timestamped text files in the output directory

## Supported formats

mp3, wav, m4a, flac, ogg, wma, aac, webm, mp4

## Project structure

```
transcribe.py      -- single-file CLI tool (all logic)
audio_sources/     -- default input directory
transcripts/       -- default output directory
.env               -- HuggingFace token (not committed)
.env.example       -- template for .env
```

## Notes

- Existing transcripts are skipped (delete the output file to re-transcribe)
- Runs on CPU even on Apple Silicon (WhisperX diarization has MPS stability issues)
- Speaker diarization is optional -- works without `HF_TOKEN` but won't separate speakers
- The `--fast` flag uses all available CPU cores and enables DataLoader prefetching without reducing transcription accuracy
