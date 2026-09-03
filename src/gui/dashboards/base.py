"""
Base Dashboard class for SimPad overlay dashboards.
"""

from abc import ABC, abstractmethod
from typing import Any
from src.telemetry.sensors import VehicleSensors


class BaseDashboard(ABC):
    """
    Abstract base class for SimPad overlay HUD dashboards.
    Each dashboard manages its own window, geometry, and widgets.
    """

    def __init__(self, name: str):
        self.name = name
        self._visible = False

    @property
    def is_visible(self) -> bool:
        return self._visible

    @abstractmethod
    def build_ui(self) -> None:
        """Builds dashboard graphical user interface."""
        pass

    @abstractmethod
    def show(self) -> None:
        """Makes dashboard visible on screen."""
        pass

    @abstractmethod
    def hide(self) -> None:
        """Hides dashboard from screen."""
        pass

    @abstractmethod
    def update_telemetry(self, sensors: VehicleSensors) -> None:
        """Updates telemetry data displayed by dashboard."""
        pass
