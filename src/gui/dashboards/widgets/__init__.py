"""
SimPad HUD Overlay Widgets Package.
Contains individual modular widget classes for LMU HUD Overlay.
"""

from src.gui.dashboards.widgets.base_widget import BaseHudWidget
from src.gui.dashboards.widgets.abs_gauge import AbsGaugeWidget
from src.gui.dashboards.widgets.brake_gauge import BrakeGaugeWidget
from src.gui.dashboards.widgets.throttle_gauge import ThrottleGaugeWidget
from src.gui.dashboards.widgets.tc_gauge import TcGaugeWidget
from src.gui.dashboards.widgets.gear_speed import GearSpeedWidget
from src.gui.dashboards.widgets.rev_indicator import RevIndicatorWidget
from src.gui.dashboards.widgets.aero_bar import AeroBarWidget
from src.gui.dashboards.widgets.delta_timer import DeltaTimerWidget
from src.gui.dashboards.widgets.energy_laps import EnergyLapsWidget
from src.gui.dashboards.widgets.sector_times import SectorTimesWidget
from src.gui.dashboards.widgets.tires_gauge import TiresGaugeWidget

__all__ = [
    "BaseHudWidget",
    "AbsGaugeWidget",
    "BrakeGaugeWidget",
    "ThrottleGaugeWidget",
    "TcGaugeWidget",
    "TiresGaugeWidget",
    "GearSpeedWidget",
    "RevIndicatorWidget",
    "AeroBarWidget",
    "DeltaTimerWidget",
    "EnergyLapsWidget",
    "SectorTimesWidget",
]
