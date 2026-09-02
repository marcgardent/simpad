"""
SimPad Qt HUD Overlay Widgets Module.
Exports all 8 modular telemetry & racing HUD widgets for LMU.
"""

from src.gui.overlay.widgets.gear_speed import QtGearSpeedWidget
from src.gui.overlay.widgets.rev_indicator import QtRevIndicatorWidget
from src.gui.overlay.widgets.abs_gauge import QtAbsGaugeWidget
from src.gui.overlay.widgets.brake_gauge import QtBrakeGaugeWidget
from src.gui.overlay.widgets.throttle_gauge import QtThrottleGaugeWidget
from src.gui.overlay.widgets.tc_gauge import QtTcGaugeWidget
from src.gui.overlay.widgets.delta_timer import QtDeltaTimerWidget
from src.gui.overlay.widgets.sector_times import QtSectorTimesWidget
from src.gui.overlay.widgets.aero_bar import QtAeroBarWidget
from src.gui.overlay.widgets.energy_laps import QtEnergyLapsWidget
from src.gui.overlay.widgets.tires_gauge import QtTiresGaugeWidget

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
]
