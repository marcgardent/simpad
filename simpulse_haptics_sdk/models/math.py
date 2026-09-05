"""
SimPulse Haptics — Mathematical Utilities.
"""

from __future__ import annotations
import math


def clamp(value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    """Clamps a numeric value to [min_val, max_val]."""
    return min(max_val, max(min_val, value))


def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation between a and b."""
    return a + (b - a) * clamp(t, 0.0, 1.0)


def normalize_signal(value: float, min_val: float = 0.0, max_val: float = 1.0, clamp_output: bool = True) -> float:
    """Normalizes a raw value between min_val and max_val into [0.0, 1.0]."""
    span = max(1e-5, max_val - min_val)
    norm = (value - min_val) / span
    return clamp(norm, 0.0, 1.0) if clamp_output else norm


def invert_signal(value: float, max_val: float = 1.0) -> float:
    """Inverts a normalized signal (e.g. 1.0 - value)."""
    return clamp(max_val - value, 0.0, max_val)


def apply_response_curve(
    raw_intensity: float,
    gamma: float = 1.0,
    gain: float = 1.0,
    min_cutoff: float = 0.0
) -> float:
    """
    Applies a parametric response curve (Cutoff threshold + Gamma exponent + Gain scaling).
    """
    if raw_intensity < min_cutoff:
        return 0.0

    span = max(1e-5, 1.0 - min_cutoff)
    norm = (raw_intensity - min_cutoff) / span
    norm_clamped = clamp(norm, 0.0, 1.0)

    curved = math.pow(norm_clamped, max(0.01, gamma))
    return clamp(curved * gain, 0.0, 1.0)
