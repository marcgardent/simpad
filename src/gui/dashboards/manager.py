import os
import sys
import logging
from typing import Dict, Optional, List
from PySide6.QtWidgets import QApplication

from src.gui.dashboards.base import BaseDashboard
from src.gui.dashboards.monitoring_board import MonitoringBoard
from src.gui.overlay.lmu_hud_window import LmuHudQtWindow
from src.telemetry.sensors import VehicleSensors

import dearpygui.dearpygui as dpg

logger = logging.getLogger(__name__)


class DashboardManager:
    """
    Centralized manager for creation, positioning, visibility,
    and telemetry updates of dashboards and the Qt HUD Overlay.
    Manages display modes: 'desktop' (main console), 'ingame' (transparent Qt overlay), and 'pause'.
    """

    def __init__(self, grace_period_sec: float = 1.5):
        self._dashboards: Dict[str, BaseDashboard] = {}
        self._enabled_dashboards: Dict[str, bool] = {}
        self._display_mode = "desktop"
        self._pending_mode: Optional[str] = None
        self._pending_mode_start: float = 0.0
        self._grace_period_sec: float = grace_period_sec
        
        self._qt_app = QApplication.instance() or QApplication(sys.argv)
        self._qt_overlay = LmuHudQtWindow()
        # Dashboard registrations
        self.register_dashboard(MonitoringBoard(), enabled=False)
        self._enabled_dashboards["lmuHudBoard"] = True

    @property
    def dashboard_names(self) -> List[str]:
        """Returns list of registered dashboard names (including lmuHudBoard)."""
        names = list(self._dashboards.keys())
        if "lmuHudBoard" not in names:
            names.append("lmuHudBoard")
        return names

    @property
    def display_mode(self) -> str:
        return self._display_mode

    def is_dashboard_enabled(self, name: str) -> bool:
        """Indicates whether a specific dashboard or overlay is enabled."""
        return self._enabled_dashboards.get(name, True)

    def set_dashboard_enabled(self, name: str, enabled: bool) -> None:
        """Enables or disables a specific dashboard or Qt HUD overlay via its checkbox."""
        self._enabled_dashboards[name] = enabled
        print(f"[DashboardManager] Dashboard '{name}' enabled set to {enabled}", flush=True)
        if self._display_mode == "ingame":
            if enabled:
                self.show(name)
                if name == "lmuHudBoard":
                    self._qt_overlay.show()
            else:
                self.hide(name)
                if name == "lmuHudBoard":
                    self._qt_overlay.hide()

    def update_auto_display_state(self, is_lmu_foreground: bool, on_track: bool, now: Optional[float] = None) -> str:
        """
        Centralized reactive display decision:
        - 'ingame'  : LMU active in foreground AND driving on track (on_track=True / in_realtime=True).
        - 'pause'   : LMU active in foreground BUT in menus/garages/pits/pause (on_track=False).
        - 'desktop' : LMU not active in foreground.
        """
        if not is_lmu_foreground:
            target_mode = "desktop"
        elif on_track:
            target_mode = "ingame"
        else:
            target_mode = "pause"

        if target_mode != self._display_mode:
            self.set_display_mode(target_mode)

        return self._display_mode

    def set_display_mode(self, mode: str) -> None:
        """
        Strictly switches between the 3 display modes:
        - 'desktop': Main config console displayed. Overlay hidden.
        - 'ingame' : Transparent Qt HUD overlay displayed in foreground.
        - 'pause'  : Menus/Garages/Pause in LMU. Overlay hidden to leave game screen clear.
        """
        if mode not in ("desktop", "ingame", "pause"):
            return

        old_mode = self._display_mode
        self._display_mode = mode

        try:
            from src.telemetry.overlay_anomaly_logger import OverlayAnomalyLogger
            OverlayAnomalyLogger.get_instance().log_display_mode_change(
                old_mode=old_mode,
                new_mode=mode,
                reason="set_display_mode",
            )
        except Exception:
            pass

        if mode == "ingame":
            self.show_all()
            if self.is_dashboard_enabled("lmuHudBoard"):
                self._qt_overlay.update_geometry()
                self._qt_overlay.show()
                print("[DashboardManager] Active INGAME mode -> Qt HUD Overlay shown.", flush=True)
        else:
            self.hide_all()
            self._qt_overlay.hide()
            if mode == "pause":
                print("[DashboardManager] PAUSE / GARAGE mode -> Overlay hidden.", flush=True)
            else:
                print("[DashboardManager] DESKTOP mode -> Studio Console active.", flush=True)

    def register_dashboard(self, board: BaseDashboard, enabled: bool = True) -> None:
        """Registers a new dashboard in the manager."""
        if board.name in self._dashboards:
            logger.warning(f"[DashboardManager] Dashboard '{board.name}' is already registered. Overwriting.")
        self._dashboards[board.name] = board
        self._enabled_dashboards[board.name] = enabled
        print(f"[DashboardManager] Registered dashboard: '{board.name}' (enabled={enabled})", flush=True)

    def get_dashboard(self, name: str) -> Optional[BaseDashboard]:
        """Returns a dashboard instance by name."""
        return self._dashboards.get(name)

    def build_all_ui(self) -> None:
        """Builds user interface for all registered dashboards."""
        for board in self._dashboards.values():
            try:
                board.build_ui()
            except Exception as e:
                logger.error(f"[DashboardManager] Error build_ui on '{board.name}': {e}")

    def show_all(self) -> None:
        """Shows all registered dashboards that are enabled."""
        for name, board in self._dashboards.items():
            if self._enabled_dashboards.get(name, True):
                try:
                    board.show()
                except Exception as e:
                    logger.error(f"[DashboardManager] Error show on '{board.name}': {e}")

    def show(self, name: str) -> None:
        """Shows a specific dashboard by name."""
        board = self._dashboards.get(name)
        if board:
            board.show()

    def hide_all(self) -> None:
        """Hides all registered dashboards."""
        for board in self._dashboards.values():
            try:
                board.hide()
            except Exception as e:
                logger.error(f"[DashboardManager] Error hide on '{board.name}': {e}")

    def hide(self, name: str) -> None:
        """Hides a specific dashboard by name."""
        board = self._dashboards.get(name)
        if board:
            board.hide()

    def update_telemetry(self, sensors: VehicleSensors) -> None:
        """Transmits sensor update to all visible dashboards."""
        if not sensors.in_realtime:
            if self._display_mode == "ingame":
                self.set_display_mode("pause")
            return

        if self._display_mode == "ingame" and self.is_dashboard_enabled("lmuHudBoard"):
            try:
                self._qt_overlay.update_telemetry(sensors)
            except Exception as e:
                logger.debug(f"[DashboardManager] Error Qt Overlay update_telemetry: {e}")

        for board in self._dashboards.values():
            if board.is_visible:
                try:
                    board.update_telemetry(sensors)
                except Exception as e:
                    logger.debug(f"[DashboardManager] Error update_telemetry on '{board.name}': {e}")

    def update_history_plots(self, t_list, d_abs, d_tc, d_over, d_und, d_rpm, d_travel, d_low, d_high) -> None:
        """Transmits time-series plot histories to dashboards with graphs."""
        for board in self._dashboards.values():
            if board.is_visible and hasattr(board, "update_history_plots"):
                try:
                    board.update_history_plots(t_list, d_abs, d_tc, d_over, d_und, d_rpm, d_travel, d_low, d_high)
                except Exception as e:
                    logger.debug(f"[DashboardManager] Error update_history_plots on '{board.name}': {e}")
