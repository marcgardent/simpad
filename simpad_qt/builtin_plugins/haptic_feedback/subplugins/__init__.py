"""
SimPad Haptics Subplugins Package.
Provides modular, configurable haptic feedback subplugins including the decomposition of 'Marc Profile'.
"""

from .base import BaseHapticSubplugin
from .marc_abs import MarcAbsSubplugin
from .marc_tc import MarcTcSubplugin
from .marc_engine_shift import MarcEngineShiftSubplugin
from .curbs import CurbsHapticSubplugin
from .slip import SlipHapticSubplugin
from .grip import TireGripHapticSubplugin
from typing import List


def get_default_subplugins() -> List[BaseHapticSubplugin]:
    """
    Returns a newly instantiated list of all standard haptic subplugins.
    Marc Profile subplugins (ABS, TC, Engine Shift) are enabled by default.
    """
    return [
        MarcAbsSubplugin(),
        MarcTcSubplugin(),
        MarcEngineShiftSubplugin(),
        CurbsHapticSubplugin(),
        SlipHapticSubplugin(),
        TireGripHapticSubplugin(),
    ]


__all__ = [
    "BaseHapticSubplugin",
    "MarcAbsSubplugin",
    "MarcTcSubplugin",
    "MarcEngineShiftSubplugin",
    "CurbsHapticSubplugin",
    "SlipHapticSubplugin",
    "TireGripHapticSubplugin",
    "get_default_subplugins",
]
