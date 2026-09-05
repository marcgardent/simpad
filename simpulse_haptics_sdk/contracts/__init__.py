"""
SimPulse Haptics SDK — Subplugin Contracts.
"""

from .subplugin import BaseHapticSubplugin, IHapticSubplugin
from .slot import HapticHostSlot, SubpluginHostSlot

__all__ = [
    "BaseHapticSubplugin",
    "IHapticSubplugin",
    "HapticHostSlot",
    "SubpluginHostSlot",
]
