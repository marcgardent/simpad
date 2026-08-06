"""
DashboardManager — Centralized Manager for HUD Overlay Dashboards.
Manages dashboard registration, visibility lifecycle, and telemetry updates.
"""

import logging
from typing import Dict, Optional, List
from src.gui.dashboards.base import BaseDashboard
from src.gui.dashboards.monitoring_board import MonitoringBoard
from src.telemetry.sensors import VehicleSensors

import dearpygui.dearpygui as dpg

logger = logging.getLogger(__name__)


class DashboardManager:
    """
    Gestionnaire centralisé pour la création, le positionnement, la visibilité
    et la mise à jour télémétrique des tableaux de bord (dashboards).
    Gère les modes d'affichage 'desktop' (console principale) et 'ingame' (overlays transparents).
    """

    def __init__(self):
        self._dashboards: Dict[str, BaseDashboard] = {}
        self._display_mode = "desktop"
        # Enregistrement par défaut du monitoringBoard
        self.register_dashboard(MonitoringBoard())

    @property
    def display_mode(self) -> str:
        return self._display_mode

    def set_display_mode(self, mode: str) -> None:
        """
        Bascule strictement entre les modes d'affichage :
        - 'ingame' : Masque à 100% la console de configuration (primary_window), affiche uniquement les overlays HUD (monitoringBoard).
        - 'desktop' : Masque à 100% les overlays HUD (monitoringBoard), affiche uniquement la console de configuration (primary_window).
        """
        if mode not in ("desktop", "ingame"):
            return

        self._display_mode = mode
        if mode == "ingame":
            if dpg.does_item_exist("primary_window"):
                dpg.set_primary_window("primary_window", False)
                dpg.hide_item("primary_window")
            self.show_all()
            print("[DashboardManager] Mode INGAME actif -> Overlays HUD uniquement.", flush=True)
        else:
            self.hide_all()
            if dpg.does_item_exist("primary_window"):
                dpg.show_item("primary_window")
                dpg.set_primary_window("primary_window", True)
            print("[DashboardManager] Mode DESKTOP actif -> Console de configuration uniquement.", flush=True)

    def register_dashboard(self, board: BaseDashboard) -> None:
        """Enregistre un nouveau dashboard dans le gestionnaire."""
        if board.name in self._dashboards:
            logger.warning(f"[DashboardManager] Dashboard '{board.name}' est déjà enregistré. Remplacement.")
        self._dashboards[board.name] = board
        print(f"[DashboardManager] Registered dashboard: '{board.name}'", flush=True)

    def get_dashboard(self, name: str) -> Optional[BaseDashboard]:
        """Retourne une instance de dashboard par son nom."""
        return self._dashboards.get(name)

    def build_all_ui(self) -> None:
        """Construit l'interface utilisateur de tous les dashboards enregistrés."""
        for board in self._dashboards.values():
            try:
                board.build_ui()
            except Exception as e:
                logger.error(f"[DashboardManager] Erreur build_ui sur '{board.name}': {e}")

    def show_all(self) -> None:
        """Affiche tous les dashboards enregistrés."""
        for board in self._dashboards.values():
            try:
                board.show()
            except Exception as e:
                logger.error(f"[DashboardManager] Erreur show sur '{board.name}': {e}")

    def show(self, name: str) -> None:
        """Affiche un dashboard spécifique par son nom."""
        board = self._dashboards.get(name)
        if board:
            board.show()

    def hide_all(self) -> None:
        """Masque tous les dashboards enregistrés."""
        for board in self._dashboards.values():
            try:
                board.hide()
            except Exception as e:
                logger.error(f"[DashboardManager] Erreur hide sur '{board.name}': {e}")

    def hide(self, name: str) -> None:
        """Masque un dashboard spécifique par son nom."""
        board = self._dashboards.get(name)
        if board:
            board.hide()

    def update_telemetry(self, sensors: VehicleSensors) -> None:
        """Transmet la mise à jour des capteurs à tous les dashboards visibles."""
        for board in self._dashboards.values():
            if board.is_visible:
                try:
                    board.update_telemetry(sensors)
                except Exception as e:
                    logger.debug(f"[DashboardManager] Erreur update_telemetry sur '{board.name}': {e}")

    @property
    def dashboard_names(self) -> List[str]:
        """Retourne la liste des noms des dashboards enregistrés."""
        return list(self._dashboards.keys())
