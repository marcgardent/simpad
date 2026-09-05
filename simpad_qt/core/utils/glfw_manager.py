"""
SimPad — GLFW Window & Screen Manager.
Provides cross-platform window management, screen resolution queries,
and transparent overlay window creation using GLFW.
"""

from __future__ import annotations
import sys
import logging
from typing import Tuple, Optional


logger = logging.getLogger(__name__)

try:
    import glfw
    _GLFW_AVAILABLE = True
except ImportError:
    _GLFW_AVAILABLE = False
    glfw = None


class GLFWWindowManager:
    """
    Centralized manager for GLFW initialization, screen measurements,
    and borderless transparent overlay window creation.
    """

    _initialized = False

    @classmethod
    def init(cls) -> bool:
        """Initialize GLFW library if not already initialized."""
        if cls._initialized:
            return True

        if not _GLFW_AVAILABLE:
            raise RuntimeError("The 'glfw' package is not installed in the Python environment.")

        if not glfw.init():
            raise RuntimeError("Failed to initialize GLFW")

        cls._initialized = True
        logger.info("[GLFW] Window Manager initialized successfully.")
        return True

    @classmethod
    def get_screen_dimensions(cls) -> Tuple[int, int]:
        """
        Retrieves primary monitor resolution via GLFW (width, height).
        Uses glfw.get_primary_monitor() and glfw.get_video_mode().
        """
        cls.init()
        monitor = glfw.get_primary_monitor()
        if not monitor:
            raise RuntimeError("[GLFW] No primary monitor detected via GLFW")

        mode = glfw.get_video_mode(monitor)
        if not mode or mode.size.width <= 0 or mode.size.height <= 0:
            raise RuntimeError("[GLFW] Invalid video mode response from primary monitor")

        return (int(mode.size.width), int(mode.size.height))

    @classmethod
    def create_overlay_window(
        cls,
        width: int = 800,
        height: int = 600,
        title: str = "SimPad GLFW Overlay",
        visible: bool = True
    ) -> Optional[glfw._GLFWwindow]:
        """
        Creates a GLFW overlay window (Borderless, Always-On-Top, Transparent Framebuffer, NO_API).
        """
        cls.init()

        # GLFW window hints configuration
        glfw.window_hint(glfw.CLIENT_API, glfw.NO_API)
        glfw.window_hint(glfw.DECORATED, glfw.FALSE)              # Borderless
        glfw.window_hint(glfw.FLOATING, glfw.TRUE)                # Always-on-top
        glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE) # Transparent background
        glfw.window_hint(glfw.VISIBLE, glfw.TRUE if visible else glfw.FALSE)

        window = glfw.create_window(width, height, title, None, None)
        if not window:
            glfw.terminate()
            cls._initialized = False
            raise RuntimeError("Error creating GLFW window")

        logger.info(f"[GLFW] Created overlay window '{title}' ({width}x{height})")
        return window

    @classmethod
    def terminate(cls) -> None:
        """Terminates the GLFW environment."""
        if cls._initialized and _GLFW_AVAILABLE:
            try:
                glfw.terminate()
            except Exception as e:
                logger.warning(f"[GLFW] Error during termination: {e}")
            cls._initialized = False
