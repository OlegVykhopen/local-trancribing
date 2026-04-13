#!/usr/bin/env python3
"""Local audio transcription with speaker diarization using WhisperX (free, runs locally)."""

import argparse
import os
import sys
import glob

# Ensure ffmpeg 7 libs are found by torchcodec
_ffmpeg7_lib = "/opt/homebrew/opt/ffmpeg@7/lib"
if os.path.isdir(_ffmpeg7_lib):
    os.environ.setdefault("DYLD_LIBRARY_PATH", _ffmpeg7_lib)

from dotenv import load_dotenv
import whisperx
from whisperx.diarize import DiarizationPipeline, assign_word_speakers
import torch

load_dotenv()


SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".wma", ".aac", ".webm", ".mp4"}

DEFAULT_SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio_sources")
DEFAULT_OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcripts")

DEVICE = "cpu"
COMPUTE_TYPE = "int8"
if torch.backends.mps.is_available():
    DEVICE = "cpu"  # WhisperX diarization works best on CPU for Mac
    COMPUTE_TYPE = "int8"


def format_timestamp(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def transcribe_file(model, audio_path, output_dir, language=None, hf_token=None):
    basename = os.path.basename(audio_path)
    output_path = os.path.join(output_dir, f"{basename}.txt")

    if os.path.exists(output_path):
        print(f"  Skipping (transcript exists): {output_path}")
        return

    print(f"  Transcribing: {audio_path}")
    audio = whisperx.load_audio(audio_path)
    result = model.transcribe(audio, language=language, batch_size=16)

    detected_language = result.get("language", language or "en")
    print(f"  Detected language: {detected_language}")

    # Align timestamps
    print("  Aligning timestamps...")
    align_model, metadata = whisperx.load_align_model(language_code=detected_language, device=DEVICE)
    result = whisperx.align(result["segments"], align_model, metadata, audio, DEVICE, return_char_alignments=False)

    # Speaker diarization
    if hf_token:
        print("  Diarizing speakers...")
        diarize_model = DiarizationPipeline(token=hf_token, device=DEVICE)
        diarize_segments = diarize_model(audio)
        result = assign_word_speakers(diarize_segments, result)

    # Format output
    lines = []
    for seg in result["segments"]:
        start = format_timestamp(seg["start"])
        end = format_timestamp(seg["end"])
        speaker = seg.get("speaker", "SPEAKER")
        text = seg["text"].strip()
        lines.append(f"[{start} - {end}] {speaker}: {text}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"  Saved: {output_path}")


def setup_models(whisper_model, hf_token):
    """Pre-download all models so transcription works offline."""
    print(f"Downloading WhisperX model: {whisper_model}...")
    whisperx.load_model(whisper_model, DEVICE, compute_type=COMPUTE_TYPE)
    print("  Done.")

    if hf_token:
        print("Downloading diarization models...")
        DiarizationPipeline(token=hf_token, device=DEVICE)
        print("  Done.")
    else:
        print("Skipping diarization models (no HF_TOKEN).")

    print("\nAll models cached locally. Ready to transcribe offline.")


def main():
    parser = argparse.ArgumentParser(description="Transcribe audio files with speaker diarization (local, free)")
    subparsers = parser.add_subparsers(dest="command")

    # setup subcommand
    setup_parser = subparsers.add_parser("setup", help="Pre-download all models for offline use")
    setup_parser.add_argument("-m", "--model", default="base", choices=["tiny", "base", "small", "medium", "large", "large-v3"],
                              help="Whisper model size to download (default: base)")

    # default: transcribe
    parser.add_argument("files", nargs="*", help="Audio file(s) to transcribe. If omitted, processes all files in audio_sources/")
    parser.add_argument("-m", "--model", default="base", choices=["tiny", "base", "small", "medium", "large", "large-v3"],
                        help="Whisper model size (default: base). Larger = more accurate but slower.")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT, help=f"Output directory (default: {DEFAULT_OUTPUT})")
    parser.add_argument("-l", "--language", default=None, help="Language code (e.g. en, uk, de). Auto-detected if omitted.")
    parser.add_argument("--hf-token", default=os.environ.get("HF_TOKEN"), help="HuggingFace token for speaker diarization (or set HF_TOKEN env var)")
    args = parser.parse_args()

    if args.command == "setup":
        hf_token = os.environ.get("HF_TOKEN")
        setup_models(args.model, hf_token)
        return

    os.makedirs(args.output, exist_ok=True)

    if not args.hf_token:
        print("WARNING: No HuggingFace token provided. Transcription will work but WITHOUT speaker separation.")
        print("  To enable speaker diarization:")
        print("  1. Create a free account at https://huggingface.co")
        print("  2. Accept terms at https://huggingface.co/pyannote/speaker-diarization-3.1")
        print("  3. Accept terms at https://huggingface.co/pyannote/segmentation-3.0")
        print("  4. Get your token at https://huggingface.co/settings/tokens")
        print("  5. Run: export HF_TOKEN=your_token_here")
        print()

    # Collect files to process
    if args.files:
        audio_files = args.files
    else:
        audio_files = sorted(
            f for f in glob.glob(os.path.join(DEFAULT_SOURCE, "*"))
            if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS
        )

    if not audio_files:
        print(f"No audio files found. Place files in {DEFAULT_SOURCE}/ or pass them as arguments.")
        sys.exit(1)

    print(f"Loading WhisperX model: {args.model} (device: {DEVICE})")
    model = whisperx.load_model(args.model, DEVICE, compute_type=COMPUTE_TYPE)
    print(f"Processing {len(audio_files)} file(s)...\n")

    for audio_path in audio_files:
        if not os.path.isfile(audio_path):
            print(f"  File not found: {audio_path}")
            continue
        ext = os.path.splitext(audio_path)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            print(f"  Unsupported format: {audio_path}")
            continue
        transcribe_file(model, audio_path, args.output, language=args.language, hf_token=args.hf_token)

    print("\nDone.")


if __name__ == "__main__":
    main()
