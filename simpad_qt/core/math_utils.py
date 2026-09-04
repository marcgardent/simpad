"""
SimPad Core — Shared Mathematical Utilities.
Provides unified, tested response curves, clamping, and interpolation helpers.
"""

import math


def clamp(value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    """Clamps a numeric value to [min_val, max_val]."""
    return min(max_val, max(min_val, value))


def apply_response_curve(raw_intensity: float, gamma: float = 1.0, gain: float = 1.0, min_cutoff: float = 0.0) -> float:
    """
    Applies a parametric exponential response curve (Cutoff threshold + Gamma exponent + Gain scaling).
    Used across Physics processor, GUI preview curves, and Compiled Haptic nodes.
    """
    if raw_intensity < min_cutoff:
        return 0.0

    # Normalize intensity above min_cutoff
    norm = (raw_intensity - min_cutoff) / max(0.001, 1.0 - min_cutoff)

    # Exponential curve response
    curved = math.pow(clamp(norm), gamma)

    # Apply gain & clamp to [0.0, 1.0]
    return clamp(curved * gain)
