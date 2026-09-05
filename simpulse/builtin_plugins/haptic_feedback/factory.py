"""
SimPulse Haptic Factory — Automatic haptic controller instantiation factory.
"""

import sys
import logging
from .base import HapticController
from .windows import WindowsHapticController
from .sdl3_controller import SDL3HapticController
from .mock_controller import MockHapticController

logger = logging.getLogger(__name__)


class HapticBackendFactory:
    """Factory to instantiate the haptic controller suitable for detected system and hardware."""

    @staticmethod
    def create_backend(
        device_index: int = 0,
        invert_sides: bool = False,
        force_mock: bool = False
    ) -> HapticController:
        """
        Instantiates the appropriate haptic backend.
        - If force_mock=True: Instantiates MockHapticController.
        - On Windows: Instantiates WindowsHapticController (SDL3 + XInput mapper).
        - On Linux/macOS: Instantiates SDL3HapticController (SDL3 + Direct mix mapper).
        - Fallback: MockHapticController in case of missing driver/library.
        """
        if force_mock:
            logger.info("Haptic Factory: Forced creation of MockHapticController.")
            return MockHapticController()

        try:
            if sys.platform == "win32":
                controller = WindowsHapticController(device_index=device_index, invert_sides=invert_sides)
            else:
                controller = SDL3HapticController(device_index=device_index, invert_sides=invert_sides)

            if controller.is_connected():
                logger.info(f"Haptic Factory: Controller initialized successfully ({controller.get_gamepad_name()}).")
                return controller
            else:
                logger.info("Haptic Factory: No physical gamepad detected. Using SDL3 controller waiting for connection.")
                return controller

        except Exception as e:
            logger.warning(f"Haptic Factory: Failed to initialize physical controller ({e}). Falling back to MockHapticController.")
            return MockHapticController()
