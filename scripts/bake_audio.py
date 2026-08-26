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
        description="SimPad Audio Baker — Génère les fichiers audio WAV avec Piper TTS."
    )
    parser.add_argument(
        "-m", "--model",
        type=Path,
        default=DEFAULT_MODEL_PATH,
        help=f"Chemin vers le modèle ONNX (défaut: {DEFAULT_MODEL_PATH})"
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=DEFAULT_SOUND_DIR,
        help=f"Dossier de destination pour les fichiers .wav (défaut: {DEFAULT_SOUND_DIR})"
    )
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Force la régénération même si les fichiers existent déjà sur le disque"
    )
    parser.add_argument(
        "-t", "--text",
        type=str,
        default=None,
        help="Phrase unique personnalisée à générer"
    )
    parser.add_argument(
        "-n", "--name",
        type=str,
        default=None,
        help="Nom du fichier de sortie pour la phrase unique (sans extension .wav)"
    )
    parser.add_argument(
        "-l", "--list",
        action="store_true",
        help="Affiche la liste des phrases par défaut"
    )

    args = parser.parse_args()

    if args.list:
        print("\n=== Phrases SimPad configurées par défaut ===")
        for k, v in DEFAULT_PHRASES.items():
            wav_file = args.output_dir / f"{k}.wav"
            status = "✓ [Présent sur le disque]" if wav_file.exists() else "✗ [Non généré]"
            print(f"  • {k:12} : \"{v}\"  -> {wav_file.name} ({status})")
        print()
        return

    # Cas phrase unique
    if args.text:
        name = args.name or args.text.lower().replace(" ", "_")
        out_file = args.output_dir / f"{name}.wav"
        print(f"[AudioBaker] Baking unique phrase: \"{args.text}\" -> {out_file} ...")
        baked = AudioBaker.bake_file(args.text, out_file, model_path=args.model, force=args.force)
        if baked:
            print(f"[AudioBaker] Succès: {out_file} généré ({out_file.stat().st_size} octets).")
        else:
            print(f"[AudioBaker] Le fichier {out_file} existe déjà. Utilisez --force pour écraser.")
        return

    # Cas batch standard
    print(f"\n=======================================================")
    print(f"  SimPad Piper-TTS Audio Baker")
    print(f"  Modèle ONNX  : {args.model}")
    print(f"  Destination  : {args.output_dir}")
    print(f"  Mode Forcé   : {'Oui' if args.force else 'Non (uniquement les fichiers absents)'}")
    print(f"=======================================================\n")

    baked, skipped = AudioBaker.bake_batch(
        phrases=DEFAULT_PHRASES,
        output_dir=args.output_dir,
        model_path=args.model,
        force=args.force
    )

    print("\n--- Résumé du Baking ---")
    print(f"  Total phrases : {len(DEFAULT_PHRASES)}")
    print(f"  Générés       : {baked}")
    print(f"  Ignorés/Cachés: {skipped}")
    print(f"  Dossier audio : {args.output_dir.resolve()}\n")


if __name__ == "__main__":
    main()
