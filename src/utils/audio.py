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
    Gestionnaire d'annonces vocales (Clean Lap / Dirty Lap) multiplateforme (Linux, Windows, macOS).
    Utilise SDL3 / SDL3_mixer comme moteur principal à faible latence, avec fallback automatique
    sur les utilitaires système (pw-play, paplay, ffplay, mpv, WinMM, afplay).
    """

    _last_lap_flag: Optional[int] = None
    _lock = threading.Lock()
    _mixer = None
    _initialized = False
    _audio_cache = {}

    @classmethod
    def _init_sdl_audio(cls) -> bool:
        if cls._initialized:
            return cls._mixer is not None
        if not _HAS_SDL3:
            cls._initialized = True
            return False

        with cls._lock:
            if cls._initialized:
                return cls._mixer is not None
            try:
                sdl3.SDL_Init(sdl3.SDL_INIT_AUDIO)
                sdl3.MIX_Init()
                device_id = getattr(sdl3, 'SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK', 0xFFFFFFFF)
                cls._mixer = sdl3.MIX_CreateMixerDevice(device_id, None)
                if cls._mixer:
                    logger.info("[AudioAnnouncer] Native SDL3 audio mixer initialized with default playback device.")
                else:
                    err = sdl3.SDL_GetError() if hasattr(sdl3, 'SDL_GetError') else b''
                    logger.warning(f"[AudioAnnouncer] SDL3 MIX_CreateMixerDevice returned NULL: {err}")
            except Exception as e:
                logger.warning(f"[AudioAnnouncer] Failed to initialize SDL3 audio mixer: {e}")
                cls._mixer = None
            finally:
                cls._initialized = True
        return cls._mixer is not None

    @classmethod
    def _play_fallback(cls, audio_path: Path) -> None:
        """Fallback multiplateforme si SDL3 n'est pas disponible."""
        file_str = str(audio_path)

        # 1. Linux fallbacks (PipeWire / PulseAudio / CLI players)
        if sys.platform.startswith("linux"):
            import shutil
            import subprocess
            for cmd, args in [
                ("pw-play", [file_str]),
                ("paplay", [file_str]),
                ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet", file_str]),
                ("mpv", ["--no-video", "--really-quiet", file_str]),
            ]:
                if shutil.which(cmd):
                    try:
                        subprocess.run([cmd] + args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        return
                    except Exception as e:
                        logger.debug(f"[AudioAnnouncer] Fallback {cmd} failed: {e}")

        # 2. Windows fallback (WinMM)
        elif sys.platform == "win32":
            try:
                import ctypes
                winmm = ctypes.windll.winmm
                alias = f"simpad_audio_{os.getpid()}_{int(time.time() * 1000) % 10000}"
                winmm.mciSendStringW(f'open "{file_str}" alias {alias}', None, 0, 0)
                winmm.mciSendStringW(f'play {alias} wait', None, 0, 0)
                winmm.mciSendStringW(f'close {alias}', None, 0, 0)
                return
            except Exception as e:
                logger.debug(f"[AudioAnnouncer] WinMM fallback failed: {e}")

        # 3. macOS fallback (afplay)
        elif sys.platform == "darwin":
            import shutil
            import subprocess
            if shutil.which("afplay"):
                try:
                    subprocess.run(["afplay", file_str], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return
                except Exception as e:
                    logger.debug(f"[AudioAnnouncer] afplay fallback failed: {e}")

    @classmethod
    def _play_file(cls, filename: str) -> None:
        """Joue un fichier audio de manière asynchrone non-bloquante."""
        def _worker():
            audio_path = _SOUND_DIR / filename
            if not audio_path.exists():
                logger.warning(f"[AudioAnnouncer] Sound file not found: {audio_path}")
                return

            # Essai 1: SDL3
            if not cls._initialized:
                cls._init_sdl_audio()

            if cls._mixer:
                try:
                    # Chargement / mise en cache du son
                    if filename not in cls._audio_cache:
                        path_bytes = str(audio_path.resolve()).encode("utf-8")
                        audio = sdl3.MIX_LoadAudio(cls._mixer, path_bytes, True)
                        if audio:
                            cls._audio_cache[filename] = audio

                    audio_obj = cls._audio_cache.get(filename)
                    if audio_obj:
                        res = sdl3.MIX_PlayAudio(cls._mixer, audio_obj)
                        if res:
                            return
                        else:
                            err = sdl3.SDL_GetError() if hasattr(sdl3, 'SDL_GetError') else b''
                            logger.warning(f"[AudioAnnouncer] MIX_PlayAudio failed: {err}")
                except Exception as e:
                    logger.warning(f"[AudioAnnouncer] SDL3 playback error: {e}")

            # Essai 2: Fallback système
            cls._play_fallback(audio_path)

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
