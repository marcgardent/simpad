"""
SimPad Audio Announcer — Chargeur et lecteur audio WAV ultra-rapide et non-bloquant
pour les annonces vocales et spotter (Clean/Dirty Lap, alertes trafic, décomptes).
Prise en charge native WAV : Linux (pw-play, paplay, aplay), Windows (winsound), macOS (afplay).
"""

import os
import sys
import time
import queue
import shutil
import logging
import threading
import subprocess
from pathlib import Path
from typing import Optional, List, Union

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SOUND_DIR = _PROJECT_ROOT / "assets" / "sound"


class AudioAnnouncer:
    """
    Chargeur et lecteur dédié exclusivement aux fichiers audio WAV avec File d'Attente FIFO.
    Garantit que les annonces et alertes se jouent séquentiellement sans collision ni coupure,
    même si plusieurs événements se déclenchent au même instant.
    Prend en charge l'interruption immédiate pour les alertes prioritaires (Spotter Overlap/Clear).
    """

    _last_lap_flag: Optional[int] = None
    _lock = threading.Lock()
    _current_process: Optional[subprocess.Popen] = None
    _is_muted: bool = False

    # FIFO Audio Queue Sub-System
    _audio_queue: "queue.Queue[dict]" = queue.Queue()
    _queue_thread: Optional[threading.Thread] = None
    _queue_running: bool = False
    _is_playing: bool = False

    @classmethod
    def set_muted(cls, muted: bool) -> None:
        cls._is_muted = muted

    @classmethod
    def is_muted(cls) -> bool:
        return cls._is_muted

    @classmethod
    def _ensure_worker_started(cls) -> None:
        """Démarre le thread de file d'attente audio FIFO s'il n'est pas déjà actif."""
        with cls._lock:
            if cls._queue_thread is None or not cls._queue_thread.is_alive():
                cls._queue_running = True
                cls._queue_thread = threading.Thread(
                    target=cls._queue_consumer_loop,
                    daemon=True,
                    name="AudioAnnouncerQueueThread"
                )
                cls._queue_thread.start()

    @classmethod
    def _queue_consumer_loop(cls) -> None:
        """Boucle d'arrière-plan traitant la file d'attente audio FIFO de façon ordonnée."""
        while cls._queue_running:
            try:
                item = cls._audio_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            phrase_key = item.get("key")
            text_prompt = item.get("text")

            cls._is_playing = True
            try:
                if not cls._is_muted and phrase_key:
                    wav_path = cls._resolve_wav_file(phrase_key, text=text_prompt)
                    if wav_path and wav_path.exists():
                        cls._play_wav_sync(wav_path)
                        # Pause naturelle entre deux sons consécutifs
                        time.sleep(0.12)
            except Exception as e:
                logger.debug(f"[AudioAnnouncer] Queue playback error: {e}")
            finally:
                cls._is_playing = False
                cls._audio_queue.task_done()

    @classmethod
    def clear_queue(cls) -> None:
        """Vide immédiatement tous les sons en attente dans la file."""
        with cls._lock:
            while not cls._audio_queue.empty():
                try:
                    cls._audio_queue.get_nowait()
                    cls._audio_queue.task_done()
                except Exception:
                    break

    @classmethod
    def get_queue_size(cls) -> int:
        """Retourne le nombre d'annonces en attente dans la file."""
        return cls._audio_queue.qsize()

    @classmethod
    def is_playing(cls) -> bool:
        """Indique si un son est en cours de diffusion."""
        return cls._is_playing or (cls._current_process is not None)

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
    def _resolve_wav_file(cls, phrase_key_or_filename: str, text: Optional[str] = None) -> Optional[Path]:
        """
        Résout le fichier .wav dans assets/sound/.
        Si le fichier est absent du disque, déclenche la synthèse à la demande via Piper.
        """
        stem = Path(phrase_key_or_filename).stem
        wav_path = _SOUND_DIR / f"{stem}.wav"

        if wav_path.exists():
            return wav_path

        # Synthèse à la demande
        try:
            from src.utils.audio_baker import AudioBaker, DEFAULT_MODEL_PATH
            if DEFAULT_MODEL_PATH.exists():
                return AudioBaker.bake_on_demand(stem, text=text, output_dir=_SOUND_DIR)
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
    def _play_file(cls, phrase_key: str, interrupt: bool = False, text: Optional[str] = None) -> None:
        """Ajoute une phrase audio à la file d'attente FIFO."""
        cls.play_phrase(phrase_key, interrupt=interrupt, text=text)

    @classmethod
    def play_phrase(cls, phrase_key: str, interrupt: bool = False, text: Optional[str] = None) -> None:
        """Joue une phrase audio WAV via la file d'attente FIFO."""
        cls._ensure_worker_started()

        if interrupt:
            cls.stop_current()
            cls.clear_queue()
        else:
            # Anti-spam : Éviter d'empiler plusieurs fois la même annonce si elle attend déjà dans la file
            with cls._lock:
                for item in list(cls._audio_queue.queue):
                    if item.get("key") == phrase_key:
                        return

        cls._audio_queue.put({"key": phrase_key, "text": text})

    @classmethod
    def play_sequence(cls, phrase_keys: List[str], interrupt: bool = False) -> None:
        """Ajoute une séquence ordonnée de phrases audio à jouer l'une après l'autre."""
        cls._ensure_worker_started()

        if interrupt:
            cls.stop_current()
            cls.clear_queue()

        for key in phrase_keys:
            cls._audio_queue.put({"key": key, "text": None})

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
    def play_give_time_back(cls, interrupt: bool = True) -> None:
        """Déclenche l'alerte d'action immédiate : Cut track, give time back (give_time_back.wav)."""
        logger.info("[AudioAnnouncer] Announcement: GIVE TIME BACK")
        print("[AUDIO] Playing announcement: GIVE TIME BACK", flush=True)
        cls._play_file("give_time_back", interrupt=interrupt)

    @classmethod
    def play_under_investigation(cls, interrupt: bool = True) -> None:
        """Déclenche l'alerte d'investigation : Under investigation (under_investigation.wav)."""
        logger.info("[AudioAnnouncer] Announcement: UNDER INVESTIGATION")
        print("[AUDIO] Playing announcement: UNDER INVESTIGATION", flush=True)
        cls._play_file("under_investigation", interrupt=interrupt)

    @classmethod
    def play_incident_cleared(cls) -> None:
        """Déclenche l'annonce de blanchiment : Incident cleared (incident_cleared.wav)."""
        logger.info("[AudioAnnouncer] Announcement: INCIDENT CLEARED")
        print("[AUDIO] Playing announcement: INCIDENT CLEARED", flush=True)
        cls._play_file("incident_cleared")

    @classmethod
    def play_time_cleared(cls) -> None:
        """Déclenche l'annonce de temps rendu : Time given back, cleared (time_cleared.wav)."""
        logger.info("[AudioAnnouncer] Announcement: TIME CLEARED")
        print("[AUDIO] Playing announcement: TIME CLEARED", flush=True)
        cls._play_file("time_cleared")

    @classmethod
    def play_no_penalty(cls) -> None:
        """Déclenche l'annonce d'absence de pénalité : No penalty (no_penalty.wav)."""
        logger.info("[AudioAnnouncer] Announcement: NO PENALTY")
        print("[AUDIO] Playing announcement: NO PENALTY", flush=True)
        cls._play_file("no_penalty")

    @classmethod
    def play_lap_deleted(cls) -> None:
        """Déclenche l'annonce d'invalidation de tour : Lap deleted (lap_deleted.wav)."""
        logger.info("[AudioAnnouncer] Announcement: LAP DELETED")
        print("[AUDIO] Playing announcement: LAP DELETED", flush=True)
        cls._play_file("lap_deleted")

    @classmethod
    def play_penalty_applied(cls) -> None:
        """Déclenche l'annonce de pénalité : Penalty applied (penalty_applied.wav)."""
        logger.info("[AudioAnnouncer] Announcement: PENALTY APPLIED")
        print("[AUDIO] Playing announcement: PENALTY APPLIED", flush=True)
        cls._play_file("penalty_applied")

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
    def play_series(cls, series_key_or_name: str, interrupt: bool = False) -> None:
        """Déclenche l'annonce audio du nom de la série officielle (ex: 'lmgt3_fixed', 'wec_weekly')."""
        key = series_key_or_name.lower().replace(" ", "_").replace("-", "_").replace("(", "").replace(")", "").strip("_")
        logger.info(f"[AudioAnnouncer] Announcement: SERIES {key.upper()}")
        print(f"[AUDIO] Playing announcement: SERIES {key.upper()}", flush=True)
        cls._play_file(key, interrupt=interrupt)

    @classmethod
    def play_registration_open(cls, interrupt: bool = False) -> None:
        """Déclenche l'annonce ouverture des inscriptions (registration_open.wav)."""
        logger.info("[AudioAnnouncer] Announcement: REGISTRATION OPEN")
        print("[AUDIO] Playing announcement: REGISTRATION OPEN", flush=True)
        cls._play_file("registration_open", interrupt=interrupt)

    @classmethod
    def play_race_starting(cls, interrupt: bool = False) -> None:
        """Déclenche l'annonce départ de course (race_starting.wav)."""
        logger.info("[AudioAnnouncer] Announcement: RACE STARTING")
        print("[AUDIO] Playing announcement: RACE STARTING", flush=True)
        cls._play_file("race_starting", interrupt=interrupt)

    @classmethod
    def play_fifteen_minutes(cls, interrupt: bool = False) -> None:
        """Déclenche l'annonce 15 minutes restantes (fifteen_minutes.wav)."""
        cls._play_file("fifteen_minutes", interrupt=interrupt)

    @classmethod
    def play_ten_minutes(cls, interrupt: bool = False) -> None:
        """Déclenche l'annonce 10 minutes restantes (ten_minutes.wav)."""
        cls._play_file("ten_minutes", interrupt=interrupt)

    @classmethod
    def play_five_minutes(cls, interrupt: bool = False) -> None:
        """Déclenche l'annonce 5 minutes restantes (five_minutes.wav)."""
        cls._play_file("five_minutes", interrupt=interrupt)

    @classmethod
    def play_one_minute(cls, interrupt: bool = False) -> None:
        """Déclenche l'annonce 1 minute restante (one_minute.wav)."""
        cls._play_file("one_minute", interrupt=interrupt)

    @classmethod
    def play_race_alert(cls, race_id: str, minutes: int, interrupt: bool = False) -> None:
        """
        Déclenche une annonce d'alerte programmée pour une série en enchaînant son nom et le décompte.
        """
        min_key_map = {15: "fifteen_minutes", 10: "ten_minutes", 5: "five_minutes", 1: "one_minute"}
        count_key = min_key_map.get(minutes, "five_minutes")
        cls.play_sequence([race_id, count_key], interrupt=interrupt)

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

