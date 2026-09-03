"""
SimPad Haptics — Math Engine & Waveform Synthesis.
Provides response curves, normalization, signals processing, and time-modulated waveform synthesis
(Sine, Square, Sawtooth, Burst, Constant) for XInput rumble motors.
"""

from __future__ import annotations
import math
from enum import Enum
from typing import Union


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

    :param raw_intensity: Input signal level (0.0 to 1.0+)
    :param gamma: Non-linear exponent (<1.0 boosts low end, >1.0 creates progressive response)
    :param gain: Linear multiplier / scaling
    :param min_cutoff: Minimum activation threshold (values below return 0.0)
    :return: Processed intensity strictly clamped between 0.0 and 1.0
    """
    if raw_intensity < min_cutoff:
        return 0.0

    span = max(1e-5, 1.0 - min_cutoff)
    norm = (raw_intensity - min_cutoff) / span
    norm_clamped = clamp(norm, 0.0, 1.0)

    curved = math.pow(norm_clamped, max(0.01, gamma))
    return clamp(curved * gain, 0.0, 1.0)


class WaveformShape(str, Enum):
    """Supported waveform shapes for time-modulated haptic pulses."""
    SINE = "Sine (Smooth)"
    SQUARE = "Square (Pulsed)"
    SAWTOOTH = "Sawtooth (Scrub)"
    BURST = "Burst"
    CONSTANT = "Constant (Flat)"

    @classmethod
    def from_str(cls, value: Union[str, WaveformShape]) -> WaveformShape:
        if isinstance(value, WaveformShape):
            return value
        v_str = str(value).lower()
        if "sine" in v_str:
            return cls.SINE
        if "square" in v_str or "pulse" in v_str:
            return cls.SQUARE
        if "saw" in v_str or "scrub" in v_str:
            return cls.SAWTOOTH
        if "burst" in v_str:
            return cls.BURST
        return cls.CONSTANT


def generate_waveform(
    shape: Union[WaveformShape, str],
    time_s: float,
    frequency_hz: float = 20.0,
    duty_cycle: float = 1.0,
    amplitude: float = 1.0
) -> float:
    """
    Synthesizes a time-modulated haptic waveform value clamped in [0.0, 1.0].

    :param shape: Shape type (Sine, Square, Sawtooth, Burst, Constant)
    :param time_s: Elapsed simulation time in seconds
    :param frequency_hz: Modulation frequency in Hertz (> 0.1)
    :param duty_cycle: Active duty cycle window in [0.01, 1.0]
    :param amplitude: Peak signal amplitude (0.0 to 1.0)
    :return: Modulated vibration intensity in [0.0, 1.0]
    """
    if amplitude <= 0.001:
        return 0.0

    shape_enum = WaveformShape.from_str(shape)
    if shape_enum == WaveformShape.CONSTANT:
        return clamp(amplitude, 0.0, 1.0)

    freq = max(0.1, float(frequency_hz))
    duty = clamp(float(duty_cycle), 0.01, 1.0)
    period_s = 1.0 / freq

    # Normalized phase in current period [0.0, 1.0)
    phase = (time_s % period_s) / period_s

    if phase > duty:
        return 0.0

    # Local normalized time within the active pulse window [0.0, 1.0]
    phi = phase / max(0.001, duty)

    if shape_enum == WaveformShape.SINE:
        # Smooth sinusoidal pulse starting at 0, peaking at 1, returning to 0
        mod = 0.5 * (1.0 + math.sin(2.0 * math.pi * phi - math.pi / 2.0))
    elif shape_enum == WaveformShape.SQUARE:
        mod = 1.0
    elif shape_enum == WaveformShape.SAWTOOTH:
        mod = phi
    elif shape_enum == WaveformShape.BURST:
        mod = math.exp(-4.0 * phi)
    else:
        mod = 1.0

    return clamp(amplitude * mod, 0.0, 1.0)
