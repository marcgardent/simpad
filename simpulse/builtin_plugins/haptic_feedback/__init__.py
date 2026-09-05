"""
SimPulse Builtin Plugin — XInput Haptic Feedback.
Hardware controller drivers (SDL3, XInput, Windows, Mock),
telemetry math calculations, waveform synthesizers, and modular subplugins.
"""

from .plugin import HapticFeedbackPlugin
from .base import HapticController
from .factory import HapticBackendFactory
from .sdl3_controller import SDL3HapticController
from .windows import WindowsHapticController
from .mock_controller import MockHapticController
from .mapper import HapticChannelMapper, DirectMixMapper, XInputSeparatedMapper
from .models import HapticMotorOutput
from .math_engine import (
    clamp,
    lerp,
    normalize_signal,
    invert_signal,
    apply_response_curve,
    generate_waveform,
    WaveformShape,
)
from .telemetry_math import (
    calc_abs_lockup,
    calc_tc_wheelspin,
    calc_oversteer_slip,
    calc_understeer_scrub,
    calc_engine_rev_state,
    calc_wheel_travel_impacts,
    calc_tire_grip_loss,
    calc_ecu_electronics,
)
from .subplugins.base import BaseHapticSubplugin
from .subplugins.marc_abs import MarcAbsSubplugin
from .subplugins.marc_tc import MarcTcSubplugin
from .subplugins.marc_engine_shift import MarcEngineShiftSubplugin
from .subplugins.curbs import CurbsHapticSubplugin
from .subplugins.slip import SlipHapticSubplugin
from .subplugins.grip import TireGripHapticSubplugin
from .subplugins import get_default_subplugins
from .manager import HapticSubpluginManager

__all__ = [
    # Plugin
    "HapticFeedbackPlugin",
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
    # Telemetry Math
    "calc_abs_lockup",
    "calc_tc_wheelspin",
    "calc_oversteer_slip",
    "calc_understeer_scrub",
    "calc_engine_rev_state",
    "calc_wheel_travel_impacts",
    "calc_tire_grip_loss",
    "calc_ecu_electronics",
    # Subplugins
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
