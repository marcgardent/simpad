"""
SimPulse Overlay SDK — Contracts for third-party HUD widgets.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Optional, Tuple

from simpulse_sdk import HudSlot, VehicleSensors


class BaseHudWidget(ABC):
    """
    Abstract base class for third-party HUD overlay widgets.

    A developer creates a subclass of BaseHudWidget to render custom telemetry
    visualizations (e.g. delta bar, radar, tyre temps) on the SimPulse HUD overlay.

    The host compositor calls paint_hud() on every frame with the current
    VehicleSensors data and allocated painting area.
    """

    @property
    @abstractmethod
    def preferred_slot(self) -> HudSlot:
        """The preferred screen slot on the HUD canvas (e.g. HudSlot.TOP_CENTER)."""
        ...

    @abstractmethod
    def get_hud_size(self) -> Tuple[int, int]:
        """Return target rendering size as (width, height) in logical pixels."""
        ...

    def is_hud_visible(self) -> bool:
        """Return whether this HUD widget is currently enabled and visible."""
        return True

    @abstractmethod
    def paint_hud(
        self,
        painter: Any,
        width: float,
        height: float,
        sensors: VehicleSensors,
    ) -> None:
        """
        Vector rendering routine called by the HUD Compositor each frame.

        :param painter: QPainter or equivalent rendering context.
        :param width: Allocated width in logical pixels.
        :param height: Allocated height in logical pixels.
        :param sensors: Current normalized telemetry snapshot.
        """
        ...

    def on_overlay_show(self) -> None:
        """Called when the overlay transitions to visible."""
        pass

    def on_overlay_hide(self) -> None:
        """Called when the overlay transitions to hidden."""
        pass
