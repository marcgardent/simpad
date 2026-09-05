"""
SimPulse Window Management — Factory for Window Managers.
Instantiates and returns the appropriate BaseWindowManager implementation (WindowsWindowManager or LinuxWindowManager)
based on host OS platform detection.
"""

import sys
import logging
from .base import BaseWindowManager
from .windows import WindowsWindowManager
from .linux import LinuxWindowManager

logger = logging.getLogger(__name__)


class WindowManagerFactory:
    """Factory for automatic window manager instantiation based on platform."""

    _instance: BaseWindowManager = None

    @classmethod
    def create_manager(cls, force_refresh: bool = False) -> BaseWindowManager:
        """
        Instantiates the window manager appropriate for the host OS.
        - On Windows (sys.platform == 'win32') : WindowsWindowManager
        - On Linux (sys.platform.startswith('linux')) : LinuxWindowManager
        - Fallback : BaseWindowManager (No-op)
        """
        if cls._instance is not None and not force_refresh:
            return cls._instance

        try:
            if sys.platform == "win32":
                manager = WindowsWindowManager()
                logger.info("WindowManager Factory: Initialized successfully (Windows / Win32).")
            elif sys.platform.startswith("linux"):
                manager = LinuxWindowManager()
                logger.info("WindowManager Factory: Initialized successfully (Linux / Wayland / X11).")
            else:
                class GenericFallbackWindowManager(BaseWindowManager):
                    pass

                manager = GenericFallbackWindowManager()
                logger.info("WindowManager Factory: Unsupported generic platform (Fallback).")

            cls._instance = manager
            return manager

        except Exception as e:
            logger.warning(f"WindowManager Factory: Initialization failed ({e}). Falling back to generic manager.")
            class GenericFallbackWindowManager(BaseWindowManager):
                pass

            cls._instance = GenericFallbackWindowManager()
            return cls._instance

    @classmethod
    def get_manager(cls) -> BaseWindowManager:
        """Returns the unique window manager instance (Singleton)."""
        return cls.create_manager()
