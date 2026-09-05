"""
SimPad Loader — Dynamic cross-platform loading of the SDL3 library.
"""

import ctypes
import ctypes.util
import logging
import types
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class SDL3Loader:
    """
    Abstracts discovery and loading of the SDL3 library.
    Resolution order:
      1. Python package 'sdl3' (installed via PyPI / uv add sdl3)
      2. System library via ctypes.util.find_library("SDL3")
    """

    _sdl_module: Optional[types.ModuleType] = None
    _sdl_cdll: Optional[ctypes.CDLL] = None

    @classmethod
    def load(cls) -> Tuple[Optional[types.ModuleType], Optional[ctypes.CDLL]]:
        """
        Attempts to load SDL3.
        Returns a tuple (sdl_module, cdll_handle).
        """
        if cls._sdl_module is not None or cls._sdl_cdll is not None:
            return cls._sdl_module, cls._sdl_cdll

        # 1. Python package `sdl3` (recommended & cross-platform)
        try:
            import sdl3
            cls._sdl_module = sdl3
            logger.info("SDL3 initialized successfully from Python 'sdl3' package.")
            return cls._sdl_module, None
        except ImportError:
            logger.debug("Python 'sdl3' package not found, falling back to ctypes system library.")

        # 2. System lookup via ctypes.util.find_library
        sys_lib = ctypes.util.find_library("SDL3")
        if sys_lib:
            try:
                cls._sdl_cdll = ctypes.CDLL(sys_lib)
                logger.info(f"SDL3 loaded from system library: {sys_lib}")
                return None, cls._sdl_cdll
            except Exception as e:
                logger.debug(f"Unable to load system library {sys_lib}: {e}")

        logger.warning("No instance of SDL3 could be loaded (PyPI package or system lib).")
        return None, None
