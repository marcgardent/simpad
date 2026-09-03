"""
SimPad Haptics Subplugins Package.
Provides modular, configurable haptic feedback subplugins including the decomposition of 'Marc Profile'.
"""

from src.haptics.subplugins.base import BaseHapticSubplugin
from src.haptics.subplugins.marc_abs import MarcAbsSubplugin
from src.haptics.subplugins.marc_tc import MarcTcSubplugin
from src.haptics.subplugins.marc_engine_shift import MarcEngineShiftSubplugin
from src.haptics.subplugins.curbs import CurbsHapticSubplugin
from src.haptics.subplugins.slip import SlipHapticSubplugin
from src.haptics.subplugins.grip import TireGripHapticSubplugin
from typing import List


def get_default_subplugins() -> List[BaseHapticSubplugin]:
    """
    Returns a newly instantiated list of all standard haptic subplugins.
    Marc Profile subplugins (ABS, TC, Engine Shift) are enabled by default.
    """
    return [
        MarcAbsSubplugin(enabled=True),
        MarcTcSubplugin(enabled=True),
        MarcEngineShiftSubplugin(enabled=True),
        CurbsHapticSubplugin(enabled=False),
        SlipHapticSubplugin(enabled=False),
        TireGripHapticSubplugin(enabled=False),
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
