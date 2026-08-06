"""
Base HUD Widget abstract class for SimPad LMU HUD Overlay.
Each widget handles its own telemetry updates, animation smoothing, and vector drawing logic.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any
from src.telemetry.sensors import VehicleSensors


def lerp(start: float, end: float, amt: float) -> float:
    """Linear interpolation helper for smooth gauge animations."""
    return (1.0 - amt) * start + amt * end


class BaseHudWidget(ABC):
    """
    Classe de base abstraite pour les composants graphiques du LMU HUD Overlay.
    """

    @abstractmethod
    def draw(
        self,
        drawlist_tag: str,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        """
        Dessine le composant graphique dans le drawlist Dear PyGui spécifié.
        """
        pass
