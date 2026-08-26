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
    Prend en charge l'interruption immédiate pour les alertes prioritaires (Spotter Overlap/Clear).
    """

    _last_lap_flag: Optional[int] = None
    _lock = threading.Lock()
    _current_process: Optional[subprocess.Popen] = None
    _is_muted: bool = False

    @classmethod
    def set_muted(cls, muted: bool) -> None:
        cls._is_muted = muted

    @classmethod
    def is_muted(cls) -> bool:
        return cls._is_muted

    @classmethod
    def stop_current(cls) -> None:
        """Interrompt immédiatement la lecture du son en cours."""
        with cls._lock:
            if cls._current_process is not None:
                try:
                    cls._current_process.terminate()
                except Exception:
                    pass
                cls._current_process = None

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
        if cls._is_muted:
            return False

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
                        proc = subprocess.Popen([cmd] + args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        with cls._lock:
                            cls._current_process = proc
                        proc.wait()
                        with cls._lock:
                            if cls._current_process == proc:
                                cls._current_process = None
                        return proc.returncode == 0
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
                    proc = subprocess.Popen(["afplay", file_str], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    with cls._lock:
                        cls._current_process = proc
                    proc.wait()
                    with cls._lock:
                        if cls._current_process == proc:
                            cls._current_process = None
                    return proc.returncode == 0
                except Exception as e:
                    logger.debug(f"[AudioAnnouncer] afplay failed: {e}")

        return False

    @classmethod
    def _play_file(cls, phrase_key: str, interrupt: bool = False) -> None:
        """Joue un fichier WAV de façon asynchrone non-bloquante."""
        if cls._is_muted:
            return

        if interrupt:
            cls.stop_current()

        def _worker():
            wav_path = cls._resolve_wav_file(phrase_key)
            if not wav_path or not wav_path.exists():
                logger.warning(f"[AudioAnnouncer] WAV file not found or could not be generated: {phrase_key}")
                return

            cls._play_wav_sync(wav_path)

        threading.Thread(target=_worker, daemon=True).start()

    @classmethod
    def play_phrase(cls, phrase_key: str, interrupt: bool = False) -> None:
        """Joue une phrase audio WAV (ex: 'clean_lap', 'car', 'one', 'incoming', 'alongside', 'clear')."""
        cls._play_file(phrase_key, interrupt=interrupt)

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
    def play_incoming(cls) -> None:
        """Déclenche le spotter : Incoming (incoming.wav)."""
        logger.info("[AudioAnnouncer] Announcement: INCOMING")
        print("[AUDIO] Playing announcement: INCOMING", flush=True)
        cls._play_file("incoming")

    @classmethod
    def play_traffic_5(cls) -> None:
        """Déclenche le spotter : Traffic 5 (traffic_5.wav)."""
        logger.info("[AudioAnnouncer] Announcement: TRAFFIC 5")
        print("[AUDIO] Playing announcement: TRAFFIC 5", flush=True)
        cls._play_file("traffic_5")

    @classmethod
    def play_alongside(cls, interrupt: bool = True) -> None:
        """Déclenche le spotter : Alongside (alongside.wav)."""
        logger.info("[AudioAnnouncer] Announcement: ALONGSIDE")
        print("[AUDIO] Playing announcement: ALONGSIDE", flush=True)
        cls._play_file("alongside", interrupt=interrupt)

    @classmethod
    def play_overlap(cls, interrupt: bool = True) -> None:
        """Déclenche le spotter : Overlap (overlap.wav)."""
        logger.info("[AudioAnnouncer] Announcement: OVERLAP")
        print("[AUDIO] Playing announcement: OVERLAP", flush=True)
        cls._play_file("overlap", interrupt=interrupt)

    @classmethod
    def play_clear(cls, interrupt: bool = True) -> None:
        """Déclenche le spotter : Clear (clear.wav)."""
        logger.info("[AudioAnnouncer] Announcement: CLEAR")
        print("[AUDIO] Playing announcement: CLEAR", flush=True)
        cls._play_file("clear", interrupt=interrupt)

    @classmethod
    def play_car_clear(cls, interrupt: bool = True) -> None:
        """Déclenche le spotter : Car clear (car_clear.wav)."""
        cls._play_file("car_clear", interrupt=interrupt)

    @classmethod
    def play_brake(cls, interrupt: bool = False) -> None:
        """Déclenche l'annonce de repère de freinage : Brake (brake.wav)."""
        logger.info("[AudioAnnouncer] Announcement: BRAKE")
        cls._play_file("brake", interrupt=interrupt)

    @classmethod
    def play_turn(cls, interrupt: bool = False) -> None:
        """Déclenche l'annonce de repère de braquage : Turn (turn.wav)."""
        logger.info("[AudioAnnouncer] Announcement: TURN")
        cls._play_file("turn", interrupt=interrupt)

    @classmethod
    def play_turn_number(cls, turn_number: int, interrupt: bool = False) -> None:
        """Déclenche l'annonce du numéro de virage : Turn N (turn_1.wav à turn_30.wav)."""
        num_clamped = min(30, max(1, turn_number))
        logger.info(f"[AudioAnnouncer] Announcement: TURN {num_clamped}")
        cls._play_file(f"turn_{num_clamped}", interrupt=interrupt)

    @classmethod
    def play_gear(cls, gear: int, interrupt: bool = False) -> None:
        """Déclenche l'annonce de rapport de boîte dédiée : G1 à G8 (gear_1.wav à gear_8.wav)."""
        g_clamped = min(8, max(1, gear))
        logger.info(f"[AudioAnnouncer] Announcement: GEAR {g_clamped} (gear_{g_clamped})")
        cls._play_file(f"gear_{g_clamped}", interrupt=interrupt)

    @classmethod
    def play_number(cls, number: int) -> None:
        """Déclenche le décompte numérique (1.wav à 8.wav)."""
        num_map = {
            1: "one", 2: "two", 3: "three", 4: "four",
            5: "five", 6: "six", 7: "seven", 8: "eight",
        }
        key = num_map.get(number)
        if key:
            cls._play_file(key)

    @classmethod
    def update_lap_flag(cls, new_flag: int) -> None:
        """
        Détecte les transitions d'état du drapeau de tour (compatibilité rétroactive).
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
