"""
Base HUD Widget abstract class for SimPad Qt HUD Overlay.
Each widget handles its own telemetry updates, animation smoothing, and vector QPainter rendering logic.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from PySide6.QtGui import QPainter
from simpad_qt.core.telemetry import VehicleSensors


def lerp(start: float, end: float, amt: float) -> float:
    """Linear interpolation helper for smooth gauge animations."""
    return (1.0 - amt) * start + amt * end


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


class BaseQtHudWidget(ABC):
    """
    Abstract base class for graphical components of the LMU HUD Overlay under PySide6.
    Follows SimPad plugin data model: paints vector graphics from CockpitWidgetContext.
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
