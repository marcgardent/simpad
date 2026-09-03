"""
SimPad Haptics Package.
Provides hardware controller drivers (SDL3, XInput, Windows, Mock),
telemetry math calculations, waveform synthesizers, and modular subplugins.
"""

from src.haptics.base import HapticController
from src.haptics.factory import HapticBackendFactory
from src.haptics.sdl3_controller import SDL3HapticController
from src.haptics.windows import WindowsHapticController
from src.haptics.mock_controller import MockHapticController
from src.haptics.mapper import HapticChannelMapper, DirectMixMapper, XInputSeparatedMapper
from src.haptics.models import HapticMotorOutput
from src.haptics.math_engine import (
    clamp,
    lerp,
    normalize_signal,
    invert_signal,
    apply_response_curve,
    generate_waveform,
    WaveformShape,
)
from src.haptics.telemetry_math import (
    calc_abs_lockup,
    calc_tc_wheelspin,
    calc_oversteer_slip,
    calc_understeer_scrub,
    calc_engine_rev_state,
    calc_wheel_travel_impacts,
    calc_tire_grip_loss,
    calc_ecu_electronics,
)
from src.haptics.subplugins.base import BaseHapticSubplugin
from src.haptics.subplugins.marc_abs import MarcAbsSubplugin
from src.haptics.subplugins.marc_tc import MarcTcSubplugin
from src.haptics.subplugins.marc_engine_shift import MarcEngineShiftSubplugin
from src.haptics.subplugins.curbs import CurbsHapticSubplugin
from src.haptics.subplugins.slip import SlipHapticSubplugin
from src.haptics.subplugins.grip import TireGripHapticSubplugin
from src.haptics.subplugins import get_default_subplugins
from src.haptics.manager import HapticSubpluginManager

__all__ = [
    # Hardware Controllers
    "HapticController",
    "HapticBackendFactory",
    "SDL3HapticController",
    "WindowsHapticController",
    "MockHapticController",
    "HapticChannelMapper",
    "DirectMixMapper",
    "XInputSeparatedMapper",
    # Data Models
    "HapticMotorOutput",
    # Math & Waveforms
    "clamp",
    "lerp",
    "normalize_signal",
    "invert_signal",
    "apply_response_curve",
    "generate_waveform",
    "WaveformShape",
    # Telemetry Calculations
    "calc_abs_lockup",
    "calc_tc_wheelspin",
    "calc_oversteer_slip",
    "calc_understeer_scrub",
    "calc_engine_rev_state",
    "calc_wheel_travel_impacts",
    "calc_tire_grip_loss",
    "calc_ecu_electronics",
    # Subplugins & Manager
    "BaseHapticSubplugin",
    "MarcAbsSubplugin",
    "MarcTcSubplugin",
    "MarcEngineShiftSubplugin",
    "CurbsHapticSubplugin",
    "SlipHapticSubplugin",
    "TireGripHapticSubplugin",
    "get_default_subplugins",
    "HapticSubpluginManager",
]
