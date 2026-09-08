"""
Base HUD Widget abstract class for SimPulse Qt HUD Overlay.
Each widget handles its own telemetry updates, animation smoothing, and vector QPainter rendering logic.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from PySide6.QtGui import QPainter
from simpulse.core.telemetry import VehicleSensors


def lerp(start: float, end: float, amt: float) -> float:
    """Linear interpolation helper for smooth gauge animations."""
    return (1.0 - amt) * start + amt * end


def format_signed_delta(value: float) -> str:
    """Formats a lap/sector delta the same way VehicleSensors.delta_time_str
    does (e.g. '-0.150', '+0.240', '+0.000') — shared so QtDeltaTimerWidget
    and QtSectorTimesWidget render a smoothed value with the exact same
    convention as the raw (unsmoothed) field."""
    if value < -0.0001:
        return f"-{abs(value):.3f}"
    elif value > 0.0001:
        return f"+{value:.3f}"
    return "+0.000"


@dataclass(frozen=True)
class CockpitWidgetContext:
    """
    Strongly-typed render context propagated from the Cockpit HUD Plugin to sub-widgets.
    Provides normalized telemetry sensors and cockpit environmental configuration.
    """
    sensors: VehicleSensors
    speed_unit: str = "kmh"
    hit_count: int = 0
    is_clean_lap: bool = True
    # "delta" (live gap to reference, +/-) or "expected" (projected finish
    # time) — which value QtDeltaTimerWidget shows on-track. See
    # OfficialCockpitHudConfig.delta_display_mode.
    delta_display_mode: str = "delta"
    # Which of the two engine-provided TimeStatus instances (VehicleSensors.
    # time_status / .time_status_smoothed) QtDeltaTimerWidget and
    # QtSectorTimesWidget read their live numeric value from — "direct" or
    # "smoothed". The actual smoothing (moving average over game time) now
    # lives in DeltaEngine — see OfficialCockpitHudConfig.delta_smoothing_mode
    # and the "⚙️ Engines" tab.
    delta_smoothing_mode: str = "smoothed"


class BaseQtHudWidget(ABC):
    """
    Abstract base class for graphical components of the LMU HUD Overlay under PySide6.
    Follows SimPulse plugin data model: paints vector graphics from CockpitWidgetContext.
    """

    @abstractmethod
    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        context: CockpitWidgetContext,
    ) -> None:
        """
        Renders vector graphical component via QPainter from CockpitWidgetContext.
        """
        pass
