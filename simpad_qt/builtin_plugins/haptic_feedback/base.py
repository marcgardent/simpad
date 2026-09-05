"""
SimPad Haptic Feedback — Hardware Controller & Channel Mapping Abstractions.
Internal host driver contracts for SDL3/Windows gamepad vibration.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Tuple


class HapticController(ABC):
    """Abstract base contract for multi-channel haptic feedback hardware control."""

    @abstractmethod
    def set_vibration(
        self,
        left_low: float = 0.0,
        left_high: float = 0.0,
        right_low: float = 0.0,
        right_high: float = 0.0,
        duration_ms: int = 0,
    ) -> None:
        """Sets haptic frequency intensities for Left and Right sides."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Immediately stops all vibrations."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Releases hardware resources."""
        pass

    def is_connected(self) -> bool:
        """Checks if a haptic device is connected."""
        return False

    def get_gamepad_name(self) -> str:
        """Returns name of detected gamepad."""
        return "Unknown"

    def get_axis(self, axis: int) -> float:
        """Reads normalized axis value between -1.0 and 1.0."""
        return 0.0

    def get_left_stick_x(self) -> float:
        """Left stick horizontal axis [-1.0, 1.0]."""
        return 0.0

    def get_button(self, button: int) -> bool:
        """Reads button state."""
        return False

    def get_south_button(self) -> bool:
        """Primary south button (A / Cross)."""
        return False


class IHapticChannelMapper(ABC):
    """Contract for mapping 4-channel haptic output to physical rumble motors."""

    @abstractmethod
    def map_channels(
        self,
        left_low: float = 0.0,
        left_high: float = 0.0,
        right_low: float = 0.0,
        right_high: float = 0.0,
    ) -> Tuple[float, float]:
        """Maps 4 channels to (low_freq_intensity, high_freq_intensity) in [0.0, 1.0]."""
        pass
