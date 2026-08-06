"""
Base Dashboard class for SimPad overlay dashboards.
"""

from abc import ABC, abstractmethod
from typing import Any
from src.telemetry.sensors import VehicleSensors


class BaseDashboard(ABC):
    """
    Classe de base abstraite pour les dashboards HUD overlay de SimPad.
    Chaque dashboard gère sa propre fenêtre, sa géométrie et ses widgets.
    """

    def __init__(self, name: str):
        self.name = name
        self._visible = False

    @property
    def is_visible(self) -> bool:
        return self._visible

    @abstractmethod
    def build_ui(self) -> None:
        """Construit l'interface graphique du dashboard."""
        pass

    @abstractmethod
    def show(self) -> None:
        """Rend le dashboard visible à l'écran."""
        pass

    @abstractmethod
    def hide(self) -> None:
        """Masque le dashboard de l'écran."""
        pass

    @abstractmethod
    def update_telemetry(self, sensors: VehicleSensors) -> None:
        """Met à jour les données télémétriques affichées par le dashboard."""
        pass
