#!/usr/bin/env python3
"""Local audio transcription with speaker diarization using WhisperX (free, runs locally)."""

import argparse
import os
import sys
import glob
import time

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


def format_duration(seconds):
    """Format seconds into a human-readable duration string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    m = int(seconds // 60)
    s = int(seconds % 60)
    if m < 60:
        return f"{m}m {s}s"
    h = int(m // 60)
    m = m % 60
    return f"{h}h {m}m {s}s"


def transcribe_file(model, audio_path, output_dir, language=None, hf_token=None,
                    diarize_model=None, align_cache=None, batch_size=16):
    basename = os.path.basename(audio_path)
    output_path = os.path.join(output_dir, f"{basename}.txt")

    if os.path.exists(output_path):
        print(f"  Skipping (transcript exists): {output_path}")
        return

    # Load audio and show duration
    print(f"  Loading audio: {audio_path}")
    audio = whisperx.load_audio(audio_path)
    sample_rate = 16000  # whisperx resamples to 16kHz
    duration_secs = len(audio) / sample_rate
    file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    print(f"  Audio duration: {format_duration(duration_secs)} | File size: {file_size_mb:.1f} MB")

    # Transcribe
    print(f"  Transcribing ({DEVICE}, batch_size={batch_size})...")
    t0 = time.time()
    result = model.transcribe(audio, language=language, batch_size=batch_size)
    print(f"  Transcription done in {format_duration(time.time() - t0)}")

    detected_language = result.get("language", language or "en")
    if language:
        print(f"  Language (specified): {language}")
    else:
        print(f"  Language (auto-detected): {detected_language}")

    # Align timestamps (reuse cached model if same language)
    print("  Aligning timestamps...")
    t0 = time.time()
    if align_cache and align_cache.get("language") == detected_language:
        align_model = align_cache["model"]
        metadata = align_cache["metadata"]
    else:
        align_model, metadata = whisperx.load_align_model(language_code=detected_language, device=DEVICE)
        if align_cache is not None:
            align_cache["language"] = detected_language
            align_cache["model"] = align_model
            align_cache["metadata"] = metadata
    result = whisperx.align(result["segments"], align_model, metadata, audio, DEVICE, return_char_alignments=False)
    print(f"  Alignment done in {format_duration(time.time() - t0)}")

    # Speaker diarization (uses pre-loaded model)
    if diarize_model:
        print("  Diarizing speakers...")
        t0 = time.time()
        diarize_segments = diarize_model(audio)
        result = assign_word_speakers(diarize_segments, result)
        print(f"  Diarization done in {format_duration(time.time() - t0)}")

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

    # transcribe subcommand (default)
    transcribe_parser = subparsers.add_parser("transcribe", help="Transcribe audio files")
    transcribe_parser.add_argument("files", nargs="*", help="Audio file(s) to transcribe. If omitted, processes all files in audio_sources/")
    transcribe_parser.add_argument("-m", "--model", default="base", choices=["tiny", "base", "small", "medium", "large", "large-v3"],
                        help="Whisper model size (default: base). Larger = more accurate but slower.")
    transcribe_parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT, help=f"Output directory (default: {DEFAULT_OUTPUT})")
    transcribe_parser.add_argument("-l", "--language", default=None, help="Language code (e.g. en, uk, de). Auto-detected if omitted.")
    transcribe_parser.add_argument("--hf-token", default=os.environ.get("HF_TOKEN"), help="HuggingFace token for speaker diarization (or set HF_TOKEN env var)")
    transcribe_parser.add_argument("--no-diarize", action="store_true", help="Skip speaker diarization even if HF_TOKEN is set")
    transcribe_parser.add_argument("--batch-size", type=int, default=16, help="Batch size for transcription (default: 16). Lower if running out of memory.")

    # Default to "transcribe" when no subcommand is given
    if len(sys.argv) > 1 and sys.argv[1] in ("setup", "transcribe"):
        args = parser.parse_args()
    else:
        args = transcribe_parser.parse_args()
        args.command = "transcribe"

    if args.command == "setup":
        hf_token = os.environ.get("HF_TOKEN")
        setup_models(args.model, hf_token)
        return

    os.makedirs(args.output, exist_ok=True)

    use_diarize = args.hf_token and not args.no_diarize

    if not args.hf_token:
        print("WARNING: No HuggingFace token provided. Transcription will work but WITHOUT speaker separation.")
        print("  To enable speaker diarization:")
        print("  1. Create a free account at https://huggingface.co")
        print("  2. Accept terms at https://huggingface.co/pyannote/speaker-diarization-3.1")
        print("  3. Accept terms at https://huggingface.co/pyannote/segmentation-3.0")
        print("  4. Get your token at https://huggingface.co/settings/tokens")
        print("  5. Run: export HF_TOKEN=your_token_here")
        print()
    elif args.no_diarize:
        print("Speaker diarization disabled (--no-diarize).\n")

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

    # Load whisper model once
    print(f"Loading WhisperX model: {args.model} (device: {DEVICE})...")
    try:
        model = whisperx.load_model(args.model, DEVICE, compute_type=COMPUTE_TYPE, language=args.language)
    except Exception as e:
        print(f"ERROR: Failed to load WhisperX model '{args.model}': {e}")
        sys.exit(1)

    # Load diarization model once (instead of per-file)
    diarize_model = None
    if use_diarize:
        print("Loading diarization model (this may take a minute on first run)...")
        try:
            diarize_model = DiarizationPipeline(token=args.hf_token, device=DEVICE)
            print("  Diarization model ready.")
        except Exception as e:
            print(f"ERROR: Failed to load diarization model: {e}")
            print("  Common causes:")
            print("  - HF_TOKEN is invalid or expired")
            print("  - You haven't accepted model terms at:")
            print("    https://huggingface.co/pyannote/speaker-diarization-3.1")
            print("    https://huggingface.co/pyannote/segmentation-3.0")
            print("  Continuing WITHOUT speaker diarization.\n")
            diarize_model = None

    # Alignment model cache (reused across files with same language)
    align_cache = {}

    print(f"Processing {len(audio_files)} file(s)...\n")

    failed = []
    for i, audio_path in enumerate(audio_files, 1):
        if not os.path.isfile(audio_path):
            print(f"  File not found: {audio_path}")
            continue
        ext = os.path.splitext(audio_path)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            print(f"  Unsupported format: {audio_path}")
            continue

        print(f"[{i}/{len(audio_files)}] {os.path.basename(audio_path)}")
        t_file = time.time()
        try:
            transcribe_file(model, audio_path, args.output, language=args.language,
                          hf_token=args.hf_token, diarize_model=diarize_model,
                          align_cache=align_cache, batch_size=args.batch_size)
            print(f"  Total time: {format_duration(time.time() - t_file)}\n")
        except Exception as e:
            print(f"  ERROR processing {audio_path}: {e}\n")
            failed.append(audio_path)

    if failed:
        print(f"\nFailed files ({len(failed)}):")
        for f in failed:
            print(f"  - {f}")

    print("\nDone.")


if __name__ == "__main__":
    main()
