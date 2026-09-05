"""
SimPad Mock Haptic Controller — Virtual fallback controller for CI/CD and hardware-less environments.
"""

import logging
from .base import HapticController

logger = logging.getLogger(__name__)


class MockHapticController(HapticController):
    """Mock implementation of the haptic controller."""

    def __init__(self):
        self.left_low = 0.0
        self.left_high = 0.0
        self.right_low = 0.0
        self.right_high = 0.0
        logger.info("MockHapticController initialized (virtual/mock mode).")

    def set_vibration(
        self,
        left_low: float = 0.0,
        left_high: float = 0.0,
        right_low: float = 0.0,
        right_high: float = 0.0,
        duration_ms: int = 0,
    ) -> None:
        self.left_low = left_low
        self.left_high = left_high
        self.right_low = right_low
        self.right_high = right_high

    def stop(self) -> None:
        self.set_vibration(0.0, 0.0, 0.0, 0.0)

    def close(self) -> None:
        self.stop()

    def is_connected(self) -> bool:
        return True

    def get_gamepad_name(self) -> str:
        return "SimPad Virtual Gamepad (Mock)"
