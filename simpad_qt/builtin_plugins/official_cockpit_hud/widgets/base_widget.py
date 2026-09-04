"""
Base HUD Widget abstract class for SimPad Qt HUD Overlay.
Each widget handles its own telemetry updates, animation smoothing, and vector QPainter rendering logic.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any
from PySide6.QtGui import QPainter
from simpad_qt.core.telemetry import VehicleSensors


def lerp(start: float, end: float, amt: float) -> float:
    """Linear interpolation helper for smooth gauge animations."""
    return (1.0 - amt) * start + amt * end


class BaseQtHudWidget(ABC):
    """
    Abstract base class for graphical components of the LMU HUD Overlay under PySide6.
    """

    @abstractmethod
    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        """
        Renders vector graphical component via QPainter.
        """
        pass
