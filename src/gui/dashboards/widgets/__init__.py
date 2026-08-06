"""
SimPad HUD Overlay Widgets Package.
Contains individual modular widget classes for LMU HUD Overlay.
"""

from src.gui.dashboards.widgets.base_widget import BaseHudWidget
from src.gui.dashboards.widgets.brake_gauge import BrakeGaugeWidget
from src.gui.dashboards.widgets.throttle_gauge import ThrottleGaugeWidget
from src.gui.dashboards.widgets.gear_speed import GearSpeedWidget
from src.gui.dashboards.widgets.rev_indicator import RevIndicatorWidget
from src.gui.dashboards.widgets.aero_bar import AeroBarWidget
from src.gui.dashboards.widgets.delta_timer import DeltaTimerWidget
from src.gui.dashboards.widgets.energy_laps import EnergyLapsWidget
from src.gui.dashboards.widgets.sector_times import SectorTimesWidget

__all__ = [
    "BaseHudWidget",
    "BrakeGaugeWidget",
    "ThrottleGaugeWidget",
    "GearSpeedWidget",
    "RevIndicatorWidget",
    "AeroBarWidget",
    "DeltaTimerWidget",
    "EnergyLapsWidget",
    "SectorTimesWidget",
]
