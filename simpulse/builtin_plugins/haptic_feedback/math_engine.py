"""
SimPulse Haptics — Math Engine & Waveform Synthesis.
Re-exported from simpulse_haptics_sdk for single source of truth.
"""
from simpulse_haptics_sdk import (
    clamp,
    lerp,
    normalize_signal,
    invert_signal,
    apply_response_curve,
    WaveformShape,
    generate_waveform,
)

__all__ = [
    "clamp",
    "lerp",
    "normalize_signal",
    "invert_signal",
    "apply_response_curve",
    "WaveformShape",
    "generate_waveform",
]
