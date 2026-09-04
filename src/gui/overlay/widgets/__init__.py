"""
SimPad Qt HUD Overlay Widgets Module.
Exports all 8 modular telemetry & racing HUD widgets for LMU.
"""

from simpad_qt.builtin_plugins.official_cockpit_hud.widgets import (
    QtGearSpeedWidget,
    QtRevIndicatorWidget,
    QtAbsGaugeWidget,
    QtBrakeGaugeWidget,
    QtThrottleGaugeWidget,
    QtTcGaugeWidget,
    QtTiresGaugeWidget,
    QtDeltaTimerWidget,
    QtSectorTimesWidget,
    QtAeroBarWidget,
    QtLapStatusWidget,
    QtEnergyLapsWidget,
)

__all__ = [
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
