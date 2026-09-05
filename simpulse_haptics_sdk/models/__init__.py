from .output import HapticMotorOutput
from .waveform import WaveformShape, generate_waveform
from .math import clamp, lerp, normalize_signal, invert_signal, apply_response_curve

__all__ = [
    "HapticMotorOutput",
    "WaveformShape",
    "generate_waveform",
    "clamp",
    "lerp",
    "normalize_signal",
    "invert_signal",
    "apply_response_curve",
]
