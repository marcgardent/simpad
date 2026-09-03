"""
SimPad Haptic Mapper — Routing and mixing strategies for logical haptic channels.
"""

from abc import ABC, abstractmethod
from typing import Tuple


class HapticChannelMapper(ABC):
    """Abstract interface for mapping 4 logical channels to physical motors."""

    @abstractmethod
    def map_channels(
        self, left_low: float, left_high: float, right_low: float, right_high: float
    ) -> Tuple[float, float]:
        """
        Transforms 4 logical channels into motor intensities (Low frequency, High frequency).
        :return: Tuple (low_freq_intensity, high_freq_intensity) normalized in [0.0, 1.0].
        """
        pass


class DirectMixMapper(HapticChannelMapper):
    """
    Direct additive mixing 4 channels -> 2 motors.
    left_low + left_high -> left motor (LF)
    right_low + right_high -> right motor (HF)
    """

    def map_channels(
        self, left_low: float, left_high: float, right_low: float, right_high: float
    ) -> Tuple[float, float]:
        lf = min(1.0, max(0.0, left_low + left_high))
        hf = min(1.0, max(0.0, right_low + right_high))
        return lf, hf


class XInputSeparatedMapper(HapticChannelMapper):
    """
    Specific strategy for 2-motor XInput controllers (Xbox 360 / One / Series).
    Unifies L/R signals to strictly separate low frequency texture (heavy left motor)
    from high frequency texture (light/fast right motor).
    """

    def map_channels(
        self, left_low: float, left_high: float, right_low: float, right_high: float
    ) -> Tuple[float, float]:
        unified_low = max(left_low, right_low)
        unified_high = max(left_high, right_high)
        lf = min(1.0, max(0.0, unified_low))
        hf = min(1.0, max(0.0, unified_high))
        return lf, hf
