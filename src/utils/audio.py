"""
SimPad Audio Announcer — Chargeur et lecteur audio WAV ultra-rapide et non-bloquant
pour les annonces vocales et spotter (Clean/Dirty Lap, alertes trafic, décomptes).
Prise en charge native WAV : Linux (pw-play, paplay, aplay), Windows (winsound), macOS (afplay).
"""

import os
import sys
import time
import shutil
import logging
import threading
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SOUND_DIR = _PROJECT_ROOT / "assets" / "sound"


class AudioAnnouncer:
    """
    Chargeur et lecteur dédié exclusivement aux fichiers audio WAV.
    Synthèse automatique à la demande via AudioBaker si un son est absent.
    """

    _last_lap_flag: Optional[int] = None
    _lock = threading.Lock()

    @classmethod
    def _resolve_wav_file(cls, phrase_key_or_filename: str) -> Optional[Path]:
        """
        Résout le fichier .wav dans assets/sound/.
        Si le fichier est absent du disque, déclenche la synthèse à la demande.
        """
        stem = Path(phrase_key_or_filename).stem
        wav_path = _SOUND_DIR / f"{stem}.wav"

        if wav_path.exists():
            return wav_path

        # Synthèse à la demande
        try:
            from src.utils.audio_baker import AudioBaker, DEFAULT_MODEL_PATH
            if DEFAULT_MODEL_PATH.exists():
                return AudioBaker.bake_on_demand(stem, output_dir=_SOUND_DIR)
        except Exception as e:
            logger.debug(f"[AudioAnnouncer] On-demand WAV bake failed for '{stem}': {e}")

        return None

    @classmethod
    def _play_wav_sync(cls, wav_path: Path) -> bool:
        """
        Joue directement un fichier WAV via le lecteur système le plus performant.
        """
        file_str = str(wav_path.resolve())

        # Linux : PipeWire -> PulseAudio -> ALSA
        if sys.platform.startswith("linux"):
            for cmd, args in [
                ("pw-play", [file_str]),
                ("paplay", [file_str]),
                ("aplay", ["-q", file_str]),
            ]:
                if shutil.which(cmd):
                    try:
                        res = subprocess.run([cmd] + args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        if res.returncode == 0:
                            return True
                    except Exception as e:
                        logger.debug(f"[AudioAnnouncer] {cmd} failed: {e}")

        # Windows : winsound natif C ultra-rapide pour WAV
        elif sys.platform == "win32":
            try:
                import winsound
                winsound.PlaySound(file_str, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
                return True
            except Exception as e:
                logger.debug(f"[AudioAnnouncer] winsound failed: {e}")

        # macOS : afplay natif
        elif sys.platform == "darwin":
            if shutil.which("afplay"):
                try:
                    res = subprocess.run(["afplay", file_str], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if res.returncode == 0:
                        return True
                except Exception as e:
                    logger.debug(f"[AudioAnnouncer] afplay failed: {e}")

        return False

    @classmethod
    def _play_file(cls, phrase_key: str) -> None:
        """Joue un fichier WAV de façon asynchrone non-bloquante."""
        def _worker():
            wav_path = cls._resolve_wav_file(phrase_key)
            if not wav_path or not wav_path.exists():
                logger.warning(f"[AudioAnnouncer] WAV file not found or could not be generated: {phrase_key}")
                return

            cls._play_wav_sync(wav_path)

        threading.Thread(target=_worker, daemon=True).start()

    @classmethod
    def play_phrase(cls, phrase_key: str) -> None:
        """Joue une phrase audio WAV (ex: 'clean_lap', 'car', 'one')."""
        cls._play_file(phrase_key)

    @classmethod
    def play_clean_lap(cls) -> None:
        """Déclenche le son de validation : Clean Lap (clean_lap.wav)."""
        logger.info("[AudioAnnouncer] Announcement: CLEAN LAP")
        print("[AUDIO] Playing announcement: CLEAN LAP", flush=True)
        cls._play_file("clean_lap")

    @classmethod
    def play_dirty_lap(cls) -> None:
        """Déclenche le son d'invalidation : Dirty Lap (dirty_lap.wav)."""
        logger.info("[AudioAnnouncer] Announcement: DIRTY LAP")
        print("[AUDIO] Playing announcement: DIRTY LAP", flush=True)
        cls._play_file("dirty_lap")

    @classmethod
    def play_lap(cls) -> None:
        """Déclenche le son : Lap (lap.wav)."""
        cls._play_file("lap")

    @classmethod
    def play_car(cls) -> None:
        """Déclenche le spotter : Car (car.wav)."""
        cls._play_file("car")

    @classmethod
    def play_car_clear(cls) -> None:
        """Déclenche le spotter : Car clear (car_clear.wav)."""
        cls._play_file("car_clear")

    @classmethod
    def play_number(cls, number: int) -> None:
        """Déclenche le décompte numérique (1.wav à 5.wav)."""
        num_map = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
        key = num_map.get(number)
        if key:
            cls._play_file(key)

    @classmethod
    def update_lap_flag(cls, new_flag: int) -> None:
        """
        Détecte les transitions d'état du drapeau de tour :
        - Passages Orange/Rouge (0 ou 1) -> Vert (2) : Déclenche 'clean_lap.wav'
        - Passages Vert (2) -> Orange/Rouge (0 ou 1) : Déclenche 'dirty_lap.wav'
        """
        with cls._lock:
            if cls._last_lap_flag is not None and cls._last_lap_flag != new_flag:
                # Transition vers Clean (2) depuis Orange/Rouge (0 ou 1)
                if cls._last_lap_flag in (0, 1) and new_flag == 2:
                    cls.play_clean_lap()
                # Transition vers Dirty / Invalid (0 ou 1) depuis Vert (2)
                elif cls._last_lap_flag == 2 and new_flag in (0, 1):
                    cls.play_dirty_lap()

            cls._last_lap_flag = new_flag
