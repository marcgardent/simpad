from abc import ABC, abstractmethod


class HapticController(ABC):
    """Abstract base class for multi-channel haptic feedback control."""

    @abstractmethod
    def set_vibration(
        self,
        left_low: float = 0.0,
        left_high: float = 0.0,
        right_low: float = 0.0,
        right_high: float = 0.0,
        duration_ms: int = 0,
    ) -> None:
        """
        Sets haptic frequency intensities for Left and Right sides.

        :param left_low: Low frequency Left side (0.0 to 1.0)
        :param left_high: High frequency Left side (0.0 to 1.0)
        :param right_low: Low frequency Right side (0.0 to 1.0)
        :param right_high: High frequency Right side (0.0 to 1.0)
        :param duration_ms: Vibration duration in ms
        """
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
