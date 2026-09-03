#!/usr/bin/env python3
"""
CLI Script to bake voice announcements using Piper TTS.

Usage:
    python scripts/bake_audio.py
    python scripts/bake_audio.py --force
    python scripts/bake_audio.py --text "Pit this lap" --name "pit_lap"
    python scripts/bake_audio.py --list
"""

import sys
import argparse
from pathlib import Path

# Add project root to sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.utils.audio_baker import AudioBaker, DEFAULT_PHRASES, DEFAULT_MODEL_PATH, DEFAULT_SOUND_DIR


def main():
    parser = argparse.ArgumentParser(
        description="SimPad Audio Baker — Bakes WAV voice audio files using Piper TTS."
    )
    parser.add_argument(
        "-m", "--model",
        type=Path,
        default=DEFAULT_MODEL_PATH,
        help=f"Path to ONNX voice model (default: {DEFAULT_MODEL_PATH})"
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=DEFAULT_SOUND_DIR,
        help=f"Target directory for .wav sound files (default: {DEFAULT_SOUND_DIR})"
    )
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Force regeneration even if files already exist on disk"
    )
    parser.add_argument(
        "-t", "--text",
        type=str,
        default=None,
        help="Custom single phrase to generate"
    )
    parser.add_argument(
        "-n", "--name",
        type=str,
        default=None,
        help="Output filename for single phrase (without .wav extension)"
    )
    parser.add_argument(
        "-l", "--list",
        action="store_true",
        help="List all default phrases"
    )

    args = parser.parse_args()

    if args.list:
        print("\n=== Default Configured SimPad Phrases ===")
        for k, v in DEFAULT_PHRASES.items():
            wav_file = args.output_dir / f"{k}.wav"
            status = "✓ [Present on disk]" if wav_file.exists() else "✗ [Not generated]"
            print(f"  • {k:12} : \"{v}\"  -> {wav_file.name} ({status})")
        print()
        return

    # Single phrase mode
    if args.text:
        name = args.name or args.text.lower().replace(" ", "_")
        out_file = args.output_dir / f"{name}.wav"
        print(f"[AudioBaker] Baking unique phrase: \"{args.text}\" -> {out_file} ...")
        baked = AudioBaker.bake_file(args.text, out_file, model_path=args.model, force=args.force)
        if baked:
            print(f"[AudioBaker] Success: {out_file} generated ({out_file.stat().st_size} bytes).")
        else:
            print(f"[AudioBaker] File {out_file} already exists. Use --force to overwrite.")
        return

    # Standard batch mode
    print(f"\n=======================================================")
    print(f"  SimPad Piper-TTS Audio Baker")
    print(f"  ONNX Model   : {args.model}")
    print(f"  Target Dir   : {args.output_dir}")
    print(f"  Force Mode   : {'Yes' if args.force else 'No (missing files only)'}")
    print(f"=======================================================\n")

    baked, skipped = AudioBaker.bake_batch(
        phrases=DEFAULT_PHRASES,
        output_dir=args.output_dir,
        model_path=args.model,
        force=args.force
    )

    print("\n--- Audio Baking Summary ---")
    print(f"  Total phrases : {len(DEFAULT_PHRASES)}")
    print(f"  Generated     : {baked}")
    print(f"  Skipped/Cached: {skipped}")
    print(f"  Audio Dir     : {args.output_dir.resolve()}\n")


if __name__ == "__main__":
    main()
