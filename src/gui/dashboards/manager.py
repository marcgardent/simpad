"""
DashboardManager — Centralized Manager for HUD Overlay Dashboards.
Manages dashboard registration, visibility lifecycle, and telemetry updates.
"""

import logging
from typing import Dict, Optional, List
from src.gui.dashboards.base import BaseDashboard
from src.gui.dashboards.monitoring_board import MonitoringBoard
from src.gui.dashboards.lmu_hud_board import LmuHudBoard
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
        self._enabled_dashboards: Dict[str, bool] = {}
        self._display_mode = "desktop"
        # Enregistrement des dashboards : LMU HUD activé par défaut (True), MonitoringBoard désactivé par défaut (False)
        self.register_dashboard(MonitoringBoard(), enabled=False)
        self.register_dashboard(LmuHudBoard(), enabled=True)

    @property
    def display_mode(self) -> str:
        return self._display_mode

    def is_dashboard_enabled(self, name: str) -> bool:
        """Indique si un dashboard spécifique est activé."""
        return self._enabled_dashboards.get(name, True)

    def set_dashboard_enabled(self, name: str, enabled: bool) -> None:
        """Active ou désactive un dashboard spécifique via sa checkbox."""
        self._enabled_dashboards[name] = enabled
        print(f"[DashboardManager] Dashboard '{name}' activation définie à {enabled}", flush=True)
        if self._display_mode == "ingame":
            if enabled:
                self.show(name)
            else:
                self.hide(name)

    def update_auto_display_state(self, is_lmu_foreground: bool, on_track: bool) -> str:
        """
        Décision d'affichage centralisée et partagée par tous les overlays HUD enregistrés :
        - 'ingame'  : LMU actif au premier plan ET conduite en piste (on_track=True / in_realtime=True).
        - 'pause'   : LMU actif au premier plan MAIS dans les menus/garages/stands/pause (on_track=False).
        - 'desktop' : LMU non actif au premier plan.
        """
        if not is_lmu_foreground:
            target_mode = "desktop"
        elif on_track:
            target_mode = "ingame"
        else:
            target_mode = "pause"

        if target_mode != self._display_mode:
            self.set_display_mode(target_mode)

        return target_mode

    def set_display_mode(self, mode: str) -> None:

        """
        Bascule strictement entre les 3 modes d'affichage :
        - 'desktop': Console de configuration principale affichée en mode fenêtré décoré. Overlays masqués.
        - 'ingame' : Overlays HUD (monitoringBoard) affichés en plein écran transparent borderless. Console masquée.
        - 'pause'  : Menus/Garages/Pause dans LMU. Console et overlays masqués pour laisser l'écran de jeu totalement dégagé.
        """
        if mode not in ("desktop", "ingame", "pause"):
            return

        from src.utils.window_utils import (
            force_viewport_fullscreen_overlay,
            restore_viewport_windowed,
        )
        viewport_title = "SimPad Haptic Middleware (Synthesizer Engine)"

        self._display_mode = mode
        if dpg.is_dearpygui_running():
            if mode == "ingame":
                if dpg.does_item_exist("primary_window"):
                    dpg.set_primary_window("primary_window", False)
                    dpg.hide_item("primary_window")

                force_viewport_fullscreen_overlay(viewport_title)
                self.show_all()
                print("[DashboardManager] Mode INGAME actif -> Overlays HUD visibles.", flush=True)

            elif mode == "pause":
                self.hide_all()
                if dpg.does_item_exist("primary_window"):
                    dpg.set_primary_window("primary_window", False)
                    dpg.hide_item("primary_window")

                force_viewport_fullscreen_overlay(viewport_title)
                print("[DashboardManager] Mode PAUSE / GARAGE actif -> Overlays masqués, écran de jeu dégagé.", flush=True)

            else:
                self.hide_all()
                restore_viewport_windowed(viewport_title)
                if dpg.does_item_exist("primary_window"):
                    dpg.show_item("primary_window")
                    dpg.set_primary_window("primary_window", True)
                print("[DashboardManager] Mode DESKTOP actif -> Console de configuration fenêtrée.", flush=True)
        else:
            if mode == "ingame":
                self.show_all()
            else:
                self.hide_all()

    def register_dashboard(self, board: BaseDashboard, enabled: bool = True) -> None:
        """Enregistre un nouveau dashboard dans le gestionnaire."""
        if board.name in self._dashboards:
            logger.warning(f"[DashboardManager] Dashboard '{board.name}' est déjà enregistré. Remplacement.")
        self._dashboards[board.name] = board
        self._enabled_dashboards[board.name] = enabled
        print(f"[DashboardManager] Registered dashboard: '{board.name}' (enabled={enabled})", flush=True)

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
        """Affiche tous les dashboards enregistrés qui sont activés."""
        for name, board in self._dashboards.items():
            if self._enabled_dashboards.get(name, True):
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

    def update_history_plots(self, t_list, d_abs, d_tc, d_over, d_und, d_rpm, d_travel, d_low, d_high) -> None:
        """Transmet les historiques de courbes temporelles aux dashboards avec graphes."""
        for board in self._dashboards.values():
            if board.is_visible and hasattr(board, "update_history_plots"):
                try:
                    board.update_history_plots(t_list, d_abs, d_tc, d_over, d_und, d_rpm, d_travel, d_low, d_high)
                except Exception as e:
                    logger.debug(f"[DashboardManager] Erreur update_history_plots sur '{board.name}': {e}")

    @property
    def dashboard_names(self) -> List[str]:
        """Retourne la liste des noms des dashboards enregistrés."""
        return list(self._dashboards.keys())
