"""
SimPad Loader — Chargement dynamique multi-plateforme de la bibliothèque SDL3.
"""

import ctypes
import ctypes.util
import logging
from typing import Optional, Any, Tuple

logger = logging.getLogger(__name__)


class SDL3Loader:
    """
    Abstrait la découverte et le chargement de la bibliothèque SDL3.
    Ordre de résolution :
      1. Package Python 'sdl3' (installé via PyPI / uv add sdl3)
      2. Lib système via ctypes.util.find_library("SDL3")
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
            logger.debug("Package Python 'sdl3' non trouvé, basculement sur ctypes system library.")

        # 2. Recherche système via ctypes.util.find_library
        sys_lib = ctypes.util.find_library("SDL3")
        if sys_lib:
            try:
                cls._sdl_cdll = ctypes.CDLL(sys_lib)
                logger.info(f"SDL3 chargé depuis la bibliothèque système : {sys_lib}")
                return None, cls._sdl_cdll
            except Exception as e:
                logger.debug(f"Impossible de charger la lib système {sys_lib} : {e}")

        logger.warning("Aucune instance de SDL3 n'a pu être chargée (package PyPI ou lib système).")
        return None, None
