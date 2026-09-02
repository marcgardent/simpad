"""
LMU HUD Overlay Board — Telemetry & Performance HUD Canvas (Borderless).
Positioned at 2nd horizontal third (middle) and 2nd vertical half (bottom) of the screen.
Composes modular HUD widgets to render a complete Dear PyGui HUD overlay.
"""

from typing import Dict, Any, List
import dearpygui.dearpygui as dpg
from src.gui.dashboards.base import BaseDashboard
from src.gui.dashboards.widgets import (
    AbsGaugeWidget,
    BrakeGaugeWidget,
    ThrottleGaugeWidget,
    TcGaugeWidget,
    TiresGaugeWidget,
    GearSpeedWidget,
    RevIndicatorWidget,
    AeroBarWidget,
    DeltaTimerWidget,
    EnergyLapsWidget,
    SectorTimesWidget,
)
from src.telemetry.sensors import VehicleSensors
from src.utils.window_utils import get_hud_rect


class LmuHudBoard(BaseDashboard):
    """
    Tableau de bord 'lmuHudBoard' : HUD Télémétrie & Chrono en overlay borderless.
    Positionné de manière fixe dans le 2ème tiers horizontal et 2ème moitié verticale de l'écran.
    Orchestre l'ensemble des composants de widgets indépendants sur un canvas Drawlist.
    """

    # TODO [SRP]: LmuHudBoard manages PyGui canvas creation, font binding, widget layout, and sensor context mapping
    def __init__(self):
        super().__init__(name="lmuHudBoard")
        self._window_tag = "lmuHudBoard"
        self._drawlist_tag = "lmu_hud_drawlist"
        self._extra_data: Dict[str, Any] = {}

        self._widgets = [
            AbsGaugeWidget(),
            BrakeGaugeWidget(),
            TiresGaugeWidget(),
            ThrottleGaugeWidget(),
            TcGaugeWidget(),
            GearSpeedWidget(),
            RevIndicatorWidget(),
            AeroBarWidget(),
            DeltaTimerWidget(),
            EnergyLapsWidget(),
            SectorTimesWidget(),
        ]

    def _get_canvas_rect(self) -> Tuple[int, int, int, int]:
        """DRY Helper: Retrieves standard HUD bounding box (col_third=1, row_half=1)."""
        return get_hud_rect(col_third=1, row_half=1)

    def build_ui(self) -> None:
        if dpg.does_item_exist(self._window_tag):
            return

        x, y, w, h = self._get_canvas_rect()

        with dpg.window(
            tag=self._window_tag,
            label="LMU HUD Overlay Board",
            pos=[x, y],
            width=w,
            height=h,
            no_title_bar=True,
            no_resize=True,
            no_move=True,
            no_collapse=True,
            no_scrollbar=True,
            no_background=True,
            show=False,
        ):
            self._visible = False
            dpg.add_drawlist(tag=self._drawlist_tag, width=w, height=h)

        self._apply_hud_font()

    def _apply_hud_font(self) -> None:
        """Applique la police Anta-Regular.ttf EXCLUSIVEMENT au tableau de bord HUD."""
        if not dpg.is_dearpygui_running() or not dpg.does_item_exist(self._window_tag):
            return
        from pathlib import Path
        from src.utils.window_utils import _PROJECT_ROOT
        anta_path = _PROJECT_ROOT / "assets" / "fonts" / "Anta-Regular.ttf"
        if anta_path.exists():
            try:
                with dpg.font_registry():
                    hud_font = dpg.add_font(str(anta_path), 20)
                dpg.bind_item_font(self._window_tag, hud_font)
                print("[LmuHudBoard] Anta-Regular.ttf liée EXCLUSIVEMENT à la fenêtre du HUD overlay.", flush=True)
            except Exception as e:
                pass

    def show(self) -> None:
        self._visible = True
        if dpg.is_dearpygui_running():
            if not dpg.does_item_exist(self._window_tag):
                self.build_ui()
            if dpg.does_item_exist(self._window_tag):
                x, y, w, h = self._get_canvas_rect()
                dpg.configure_item(self._window_tag, pos=[x, y], width=w, height=h)
                dpg.configure_item(self._drawlist_tag, width=w, height=h)
                dpg.show_item(self._window_tag)
                try:
                    dpg.focus_item(self._window_tag)
                except Exception:
                    pass
                self._redraw_canvas(VehicleSensors())

    def hide(self) -> None:
        self._visible = False
        if dpg.is_dearpygui_running() and dpg.does_item_exist(self._window_tag):
            dpg.hide_item(self._window_tag)

    def set_extra_data(self, **kwargs) -> None:
        """Met à jour les données complémentaires (delta, énergie, secteurs, aéro)."""
        self._extra_data.update(kwargs)

    def update_telemetry(self, sensors: VehicleSensors) -> None:
        if not self._visible or not dpg.does_item_exist(self._drawlist_tag):
            return
        self._redraw_canvas(sensors)

    def _build_widget_context(self, sensors: VehicleSensors) -> Dict[str, Any]:
        """SLAP Helper: Merges live sensor telemetry properties into widget context dictionary."""
        context = {
            "expectedTime": sensors.delta_time_str,
            "delta": sensors.delta_time_str,
            "estimatedLapTime": sensors.estimated_lap_time_str,
            "sectors": sensors.sectors_list,
            "energyLaps": sensors.fuel_level,
            "remainingLaps": sensors.remaining_laps,
            "aero": sensors.aero_load * 100.0,
            "brake": sensors.unfiltered_brake * 100.0,
            "throttle": sensors.unfiltered_throttle * 100.0,
            "abs": sensors.ecu_abs_active * 100.0,
            "tc": max(sensors.ecu_tc_active, sensors.spin_intensity) * 100.0,
            "overbrake": sensors.lock_intensity > 0.05,
            "wheelspin": sensors.spin_intensity > 0.05,
            "underrev": sensors.underrev_intensity > 0.1,
            "overrev": sensors.overrev_intensity > 0.1,
            "lap_flag": sensors.lap_flag,
            "is_pit_lap": sensors.is_pit_lap,
        }
        context.update(self._extra_data)
        return context

    def _redraw_canvas(self, sensors: VehicleSensors) -> None:
        # TODO [SLAP]: Canvas redraw method delegates context building and rect fetching to helpers
        if not dpg.is_dearpygui_running() or not dpg.does_item_exist(self._drawlist_tag):
            return

        w = dpg.get_item_width(self._drawlist_tag)
        h = dpg.get_item_height(self._drawlist_tag)

        if w <= 0 or h <= 0:
            _, _, w, h = self._get_canvas_rect()

        combined_extra = self._build_widget_context(sensors)

        dpg.delete_item(self._drawlist_tag, children_only=True)

        for widget in self._widgets:
            widget.draw(self._drawlist_tag, float(w), float(h), sensors, combined_extra)


