"""
SimPulse Haptics SDK — Contracts and Models for Haptic Subplugins & Effects.
Third-party developers implement BaseHapticSubplugin and return HapticMotorOutput.
"""

from simpulse_haptics_sdk.contracts import (
    BaseHapticSubplugin,
    IHapticSubplugin,
    HapticHostSlot,
    SubpluginHostSlot,
)
from simpulse_haptics_sdk.models import (
    HapticMotorOutput,
    WaveformShape,
    generate_waveform,
    clamp,
    lerp,
    normalize_signal,
    invert_signal,
    apply_response_curve,
)

__all__ = [
    # Contracts
    "BaseHapticSubplugin",
    "IHapticSubplugin",
    "HapticHostSlot",
    "SubpluginHostSlot",
    # Models & Helpers
    "HapticMotorOutput",
    "WaveformShape",
    "generate_waveform",
    "clamp",
    "lerp",
    "normalize_signal",
    "invert_signal",
    "apply_response_curve",
]
