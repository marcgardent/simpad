"""
SimPad Window Management — Factory for Window Managers.
Instantiates and returns the appropriate BaseWindowManager implementation (WindowsWindowManager or LinuxWindowManager)
based on host OS platform detection.
"""

import sys
import logging
from src.utils.window.base import BaseWindowManager
from src.utils.window.windows import WindowsWindowManager
from src.utils.window.linux import LinuxWindowManager

logger = logging.getLogger(__name__)


class WindowManagerFactory:
    """Usine d'instanciation automatique du gestionnaire de fenêtres selon la plateforme."""

    _instance: BaseWindowManager = None

    @classmethod
    def create_manager(cls, force_refresh: bool = False) -> BaseWindowManager:
        """
        Instancie le gestionnaire de fenêtres approprié pour l'OS hôte.
        - Sur Windows (sys.platform == 'win32') : WindowsWindowManager
        - Sur Linux (sys.platform.startswith('linux')) : LinuxWindowManager
        - Fallback : BaseWindowManager (No-op)
        """
        if cls._instance is not None and not force_refresh:
            return cls._instance

        try:
            if sys.platform == "win32":
                manager = WindowsWindowManager()
                logger.info("Usine WindowManager : Initialisé avec succès (Windows / Win32).")
            elif sys.platform.startswith("linux"):
                manager = LinuxWindowManager()
                logger.info("Usine WindowManager : Initialisé avec succès (Linux / Wayland / X11).")
            else:
                class GenericFallbackWindowManager(BaseWindowManager):
                    pass

                manager = GenericFallbackWindowManager()
                logger.info("Usine WindowManager : Plateforme générique non gérée (Fallback).")

            cls._instance = manager
            return manager

        except Exception as e:
            logger.warning(f"Usine WindowManager : Échec d'initialisation ({e}). Basculement sur le gestionnaire générique.")
            class GenericFallbackWindowManager(BaseWindowManager):
                pass

            cls._instance = GenericFallbackWindowManager()
            return cls._instance

    @classmethod
    def get_manager(cls) -> BaseWindowManager:
        """Retourne l'instance unique du gestionnaire de fenêtres (Singleton)."""
        return cls.create_manager()
