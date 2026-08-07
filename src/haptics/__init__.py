"""Package haptics pour SimPad."""

from src.haptics.base import HapticController
from src.haptics.factory import HapticBackendFactory
from src.haptics.sdl3_controller import SDL3HapticController
from src.haptics.windows import WindowsHapticController
from src.haptics.mock_controller import MockHapticController

__all__ = [
    "HapticController",
    "HapticBackendFactory",
    "SDL3HapticController",
    "WindowsHapticController",
    "MockHapticController",
]
