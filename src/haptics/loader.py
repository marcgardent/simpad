"""
SimPad Loader — Chargement dynamique multi-plateforme de la bibliothèque SDL3.
"""

import sys
import ctypes
import ctypes.util
import logging
from pathlib import Path
from typing import Optional, Any, Tuple

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class SDL3Loader:
    """
    Abstrait la découverte et le chargement de la bibliothèque SDL3.
    Ordre de résolution :
      1. Package Python 'sdl3' (installe via PyPI / uv add sdl3)
      2. Lib système via ctypes.util.find_library("SDL3")
      3. Binaire Bundled local (SDL3.dll, libSDL3.so, libSDL3.dylib)
    """

    _sdl_module: Optional[Any] = None
    _sdl_cdll: Optional[ctypes.CDLL] = None

    @classmethod
    def load(cls) -> Tuple[Optional[Any], Optional[ctypes.CDLL]]:
        """
        Tente de charger SDL3.
        Retourne un tuple (sdl_module, cdll_handle).
        """
        if cls._sdl_module is not None or cls._sdl_cdll is not None:
            return cls._sdl_module, cls._sdl_cdll

        # 1. Package Python `sdl3` (recommandé & cross-platform)
        try:
            import sdl3
            cls._sdl_module = sdl3
            logger.info("SDL3 initialisé avec succès depuis le package Python 'sdl3'.")
            return cls._sdl_module, None
        except ImportError:
            logger.debug("Package Python 'sdl3' non trouvé, basculement sur ctypes.")

        # 2. Recherche système via ctypes.util.find_library
        sys_lib = ctypes.util.find_library("SDL3")
        if sys_lib:
            try:
                cls._sdl_cdll = ctypes.CDLL(sys_lib)
                logger.info(f"SDL3 chargé depuis la bibliothèque système : {sys_lib}")
                return None, cls._sdl_cdll
            except Exception as e:
                logger.debug(f"Impossible de charger la lib système {sys_lib} : {e}")

        # 3. Fallback sur binaire bundled dans le projet / CWD
        lib_filename = "SDL3.dll" if sys.platform == "win32" else ("libSDL3.dylib" if sys.platform == "darwin" else "libSDL3.so")
        candidates = [
            _PROJECT_ROOT / lib_filename,
            Path.cwd() / lib_filename,
        ]

        for p in candidates:
            if p.exists():
                try:
                    abs_p = str(p.resolve())
                    cls._sdl_cdll = ctypes.CDLL(abs_p)
                    logger.info(f"SDL3 chargé depuis le binaire local : {abs_p}")
                    return None, cls._sdl_cdll
                except Exception as e:
                    logger.debug(f"Échec chargement {p} : {e}")

        logger.warning("Aucune instance de SDL3 n'a pu être chargée (package PyPI, lib système ou binaire local).")
        return None, None
