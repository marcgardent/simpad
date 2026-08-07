"""
SimPad — GLFW Window & Screen Manager.
Provides cross-platform window management, screen resolution queries,
and transparent overlay window creation using GLFW.
"""

import sys
import logging
from typing import Tuple, Optional, Any


logger = logging.getLogger(__name__)

try:
    import glfw
    _GLFW_AVAILABLE = True
except ImportError:
    _GLFW_AVAILABLE = False
    glfw = None


class GLFWWindowManager:
    """
    Gestionnaire centralisé pour l'initialisation de GLFW, les mesures d'écran
    et la création de fenêtres overlays transparentes sans bordures.
    """

    _initialized = False

    @classmethod
    def init(cls) -> bool:
        """Initialise la bibliothèque GLFW s'il n'est pas déjà initialisé."""
        if cls._initialized:
            return True

        if not _GLFW_AVAILABLE:
            raise RuntimeError("Le paquet 'glfw' n'est pas installé dans l'environnement Python.")

        if not glfw.init():
            raise RuntimeError("Impossible d'initialiser GLFW")

        cls._initialized = True
        logger.info("[GLFW] Window Manager initialized successfully.")
        return True

    @classmethod
    def get_screen_dimensions(cls) -> Tuple[int, int]:
        """
        Récupère la résolution du moniteur principal via GLFW (width, height).
        Utilise glfw.get_primary_monitor() et glfw.get_video_mode().
        """
        cls.init()
        monitor = glfw.get_primary_monitor()
        if not monitor:
            raise RuntimeError("[GLFW] Aucun moniteur principal détecté via GLFW")

        mode = glfw.get_video_mode(monitor)
        if not mode or mode.size.width <= 0 or mode.size.height <= 0:
            raise RuntimeError("[GLFW] Réponse de mode vidéo invalide du moniteur principal")

        return (int(mode.size.width), int(mode.size.height))

    @classmethod
    def create_overlay_window(
        cls,
        width: int = 800,
        height: int = 600,
        title: str = "SimPad GLFW Overlay",
        visible: bool = True
    ) -> Optional[Any]:
        """
        Crée une fenêtre overlay GLFW (Borderless, Always-On-Top, Transparent Framebuffer, NO_API).
        """
        cls.init()

        # Configuration des hints de la fenêtre GLFW
        glfw.window_hint(glfw.CLIENT_API, glfw.NO_API)
        glfw.window_hint(glfw.DECORATED, glfw.FALSE)              # Borderless
        glfw.window_hint(glfw.FLOATING, glfw.TRUE)                # Always-on-top
        glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE) # Fond transparent
        glfw.window_hint(glfw.VISIBLE, glfw.TRUE if visible else glfw.FALSE)

        window = glfw.create_window(width, height, title, None, None)
        if not window:
            glfw.terminate()
            cls._initialized = False
            raise RuntimeError("Erreur création fenêtre GLFW")

        logger.info(f"[GLFW] Created overlay window '{title}' ({width}x{height})")
        return window

    @classmethod
    def terminate(cls) -> None:
        """Termine l'environnement GLFW."""
        if cls._initialized and _GLFW_AVAILABLE:
            try:
                glfw.terminate()
            except Exception as e:
                logger.warning(f"[GLFW] Error during termination: {e}")
            cls._initialized = False
