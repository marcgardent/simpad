"""
SimPad Haptic Factory — Usine d'instanciation automatique du contrôleur haptique.
"""

import sys
import logging
from src.haptics.base import HapticController
from src.haptics.windows import WindowsHapticController
from src.haptics.sdl3_controller import SDL3HapticController
from src.haptics.mock_controller import MockHapticController

logger = logging.getLogger(__name__)


class HapticBackendFactory:
    """Usine pour instancier le contrôleur haptique adapté au système et matériel détecté."""

    @staticmethod
    def create_backend(
        device_index: int = 0,
        invert_sides: bool = False,
        force_mock: bool = False
    ) -> HapticController:
        """
        Instancie le backend haptique approprié.
        - Si force_mock=True : Instancie MockHapticController.
        - Sur Windows : Instancie WindowsHapticController (SDL3 + XInput mapper).
        - Sur Linux/macOS : Instancie SDL3HapticController (SDL3 + Direct mix mapper).
        - Fallback : MockHapticController en cas d'absence de driver/lib.
        """
        if force_mock:
            logger.info("Usine haptique : Création forcée du MockHapticController.")
            return MockHapticController()

        try:
            if sys.platform == "win32":
                controller = WindowsHapticController(device_index=device_index, invert_sides=invert_sides)
            else:
                controller = SDL3HapticController(device_index=device_index, invert_sides=invert_sides)

            if controller.is_connected():
                logger.info(f"Usine haptique : Controller initialisé avec succès ({controller.get_gamepad_name()}).")
                return controller
            else:
                logger.info("Usine haptique : Aucune manette physique détectée. Utilisation du contrôleur SDL3 en attente de connexion.")
                return controller

        except Exception as e:
            logger.warning(f"Usine haptique : Échec d'initialisation du contrôleur physique ({e}). Basculement sur MockHapticController.")
            return MockHapticController()
