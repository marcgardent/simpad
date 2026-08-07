"""
SimPad Audio Announcer — Non-blocking audio playback engine for lap status voice announcements.
Utilizes native SDL3 / SDL3_mixer Python package to trigger clean_lap.mp3 and dirty_lap.mp3.
"""

import os
import sys
import time
import logging
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SOUND_DIR = _PROJECT_ROOT / "assets" / "sound"

try:
    import sdl3
    _HAS_SDL3 = True
except ImportError:
    _HAS_SDL3 = False


class AudioAnnouncer:
    """
    Gestionnaire d'annonces vocales (Clean Lap / Dirty Lap) basé sur SDL3 Python.
    """

    _last_lap_flag: Optional[int] = None
    _lock = threading.Lock()
    _mixer = None
    _initialized = False

    @classmethod
    def _init_sdl_audio(cls) -> None:
        if cls._initialized or not _HAS_SDL3:
            return
        try:
            sdl3.SDL_Init(sdl3.SDL_INIT_AUDIO)
            cls._mixer = sdl3.MIX_CreateMixer(None)
            cls._initialized = True
            logger.info("[AudioAnnouncer] Native SDL3 audio mixer initialized.")
        except Exception as e:
            logger.warning(f"[AudioAnnouncer] Failed to initialize SDL3 audio mixer: {e}")

    @classmethod
    def _play_file(cls, filename: str) -> None:
        """Joue un fichier audio MP3 via SDL3 de manière asynchrone."""
        def _worker():
            audio_path = _SOUND_DIR / filename
            if not audio_path.exists():
                logger.warning(f"[AudioAnnouncer] Sound file not found: {audio_path}")
                return

            if not cls._initialized:
                cls._init_sdl_audio()

            if cls._mixer:
                try:
                    path_bytes = str(audio_path).encode("utf-8")
                    audio = sdl3.MIX_LoadAudio(cls._mixer, path_bytes, True)
                    if audio:
                        sdl3.MIX_PlayAudio(cls._mixer, audio)
                        time.sleep(1.5)
                        sdl3.MIX_DestroyAudio(audio)
                        return
                except Exception as e:
                    logger.warning(f"[AudioAnnouncer] SDL3 playback error: {e}")

            # Backup WinMM player if SDL3 audio device unavailable
            if sys.platform == "win32":
                try:
                    import ctypes
                    winmm = ctypes.windll.winmm
                    alias = f"simpad_audio_{os.getpid()}"
                    winmm.mciSendStringW(f'open "{audio_path}" alias {alias}', None, 0, 0)
                    winmm.mciSendStringW(f'play {alias} wait', None, 0, 0)
                    winmm.mciSendStringW(f'close {alias}', None, 0, 0)
                except Exception as e:
                    logger.debug(f"[AudioAnnouncer] Backup audio error: {e}")

        threading.Thread(target=_worker, daemon=True).start()

    @classmethod
    def play_clean_lap(cls) -> None:
        """Déclenche le son de validation : Clean Lap."""
        logger.info("[AudioAnnouncer] Announcement: CLEAN LAP")
        print("[AUDIO] Playing announcement: CLEAN LAP", flush=True)
        cls._play_file("clean_lap.mp3")

    @classmethod
    def play_dirty_lap(cls) -> None:
        """Déclenche le son d'invalidation : Dirty Lap."""
        logger.info("[AudioAnnouncer] Announcement: DIRTY LAP")
        print("[AUDIO] Playing announcement: DIRTY LAP", flush=True)
        cls._play_file("dirty_lap.mp3")

    @classmethod
    def update_lap_flag(cls, new_flag: int) -> None:
        """
        Détecte les transitions d'état du drapeau de tour :
        - Passages Orange/Rouge (0 ou 1) -> Vert (2) : Déclenche 'clean_lap.mp3'
        - Passages Vert (2) -> Orange/Rouge (0 ou 1) : Déclenche 'dirty_lap.mp3'
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
