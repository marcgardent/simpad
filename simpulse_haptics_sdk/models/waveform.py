"""
SimPulse Haptics — Waveform Synthesis Models.
"""

from __future__ import annotations
import math
from enum import Enum
from typing import Union
from .math import clamp


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
    """Synthesizes a time-modulated haptic waveform value clamped in [0.0, 1.0]."""
    if amplitude <= 0.001:
        return 0.0

    shape_enum = WaveformShape.from_str(shape)
    if shape_enum == WaveformShape.CONSTANT:
        return clamp(amplitude, 0.0, 1.0)

    freq = max(0.1, float(frequency_hz))
    duty = clamp(float(duty_cycle), 0.01, 1.0)
    period_s = 1.0 / freq
    phase = (time_s % period_s) / period_s

    if phase > duty:
        return 0.0

    phi = phase / max(0.001, duty)

    if shape_enum == WaveformShape.SINE:
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
