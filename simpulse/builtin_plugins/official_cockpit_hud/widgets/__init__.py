"""
SimPulse Qt HUD Overlay Widgets Module.
Exports all 12 modular telemetry & racing HUD widgets for the Official Cockpit HUD.
"""

from .gear_speed import QtGearSpeedWidget
from .rev_indicator import QtRevIndicatorWidget
from .abs_gauge import QtAbsGaugeWidget
from .brake_gauge import QtBrakeGaugeWidget
from .throttle_gauge import QtThrottleGaugeWidget
from .tc_gauge import QtTcGaugeWidget
from .delta_timer import QtDeltaTimerWidget
from .sector_times import QtSectorTimesWidget
from .aero_bar import QtAeroBarWidget
from .energy_laps import QtEnergyLapsWidget
from .tires_gauge import QtTiresGaugeWidget
from .lap_status import QtLapStatusWidget
from .base_widget import BaseQtHudWidget, CockpitWidgetContext, lerp, format_signed_delta

__all__ = [
    "BaseQtHudWidget",
    "CockpitWidgetContext",
    "lerp",
    "format_signed_delta",
    "QtGearSpeedWidget",
    "QtRevIndicatorWidget",
    "QtAbsGaugeWidget",
    "QtBrakeGaugeWidget",
    "QtThrottleGaugeWidget",
    "QtTcGaugeWidget",
    "QtTiresGaugeWidget",
    "QtDeltaTimerWidget",
    "QtSectorTimesWidget",
    "QtAeroBarWidget",
    "QtEnergyLapsWidget",
    "QtLapStatusWidget",
]
