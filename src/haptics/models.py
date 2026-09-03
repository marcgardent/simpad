"""
SimPad Haptics — Haptic Motor Channel Data Structures.
Defines multichannel and XInput dual-motor vibration output structures.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple
from src.haptics.math_engine import clamp


@dataclass
class HapticMotorOutput:
    """
    Multichannel haptic output intensities (0.0 to 1.0).
    - left_low: Low-frequency rumble motor (Left / Bass)
    - left_high: High-frequency buzz motor (Left / Treble)
    - right_low: Low-frequency rumble motor (Right / Bass)
    - right_high: High-frequency buzz motor (Right / Treble)
    """
    left_low: float = 0.0
    left_high: float = 0.0
    right_low: float = 0.0
    right_high: float = 0.0

    def to_xinput(self) -> Tuple[float, float]:
        """
        Maps 4-channel output to standard XInput Dual Rumble Gamepad Motors:
        - Low Frequency Rumble (Left Motor): max(left_low, right_low)
        - High Frequency Buzz (Right Motor): max(left_high, right_high)
        Returns (low_rumble, high_buzz) clamped to [0.0, 1.0].
        """
        low = clamp(max(self.left_low, self.right_low), 0.0, 1.0)
        high = clamp(max(self.left_high, self.right_high), 0.0, 1.0)
        return low, high

    def combine_max(self, other: HapticMotorOutput) -> HapticMotorOutput:
        """Combines two outputs taking the maximum intensity per channel."""
        return HapticMotorOutput(
            left_low=clamp(max(self.left_low, other.left_low)),
            left_high=clamp(max(self.left_high, other.left_high)),
            right_low=clamp(max(self.right_low, other.right_low)),
            right_high=clamp(max(self.right_high, other.right_high)),
        )

    def combine_sum(self, other: HapticMotorOutput) -> HapticMotorOutput:
        """Combines two outputs by summing intensities and clamping to [0.0, 1.0]."""
        return HapticMotorOutput(
            left_low=clamp(self.left_low + other.left_low),
            left_high=clamp(self.left_high + other.left_high),
            right_low=clamp(self.right_low + other.right_low),
            right_high=clamp(self.right_high + other.right_high),
        )

    def scaled(self, gain: float) -> HapticMotorOutput:
        """Returns a new output scaled by a scalar gain factor."""
        g = max(0.0, float(gain))
        return HapticMotorOutput(
            left_low=clamp(self.left_low * g),
            left_high=clamp(self.left_high * g),
            right_low=clamp(self.right_low * g),
            right_high=clamp(self.right_high * g),
        )

    def is_silent(self) -> bool:
        """Returns True if all channels are below audible/tactile threshold (0.005)."""
        return (
            self.left_low <= 0.005
            and self.left_high <= 0.005
            and self.right_low <= 0.005
            and self.right_high <= 0.005
        )
