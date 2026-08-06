"""
monitoringBoard — Pure GPU-Accelerated Dear PyGui / Dear ImGui HUD Overlay Dashboard.
Positioned at Top-Middle third of the primary monitor screen (X=Width/3, Y=0, W=Width/3, H=Height/3).
"""

import dearpygui.dearpygui as dpg
from src.gui.dashboards.base import BaseDashboard
from src.telemetry.sensors import VehicleSensors
from src.utils.window_utils import get_3x3_grid_rect


class MonitoringBoard(BaseDashboard):
    """
    Tableau de bord HUD 'monitoringBoard' sous forme de fenêtre Dear PyGui / ImGui GPU accélérée (DirectX 11).
    Positionné de manière fixe dans le tiers haut (vertical) et milieu (horizontal) de l'écran (col=1, row=0).
    """

    def __init__(self):
        super().__init__(name="monitoringBoard")
        self._window_tag = "monitoringBoard"

    def build_ui(self) -> None:
        if dpg.does_item_exist(self._window_tag):
            return

        x, y, w, h = get_3x3_grid_rect(col=1, row=0)

        with dpg.window(
            tag=self._window_tag,
            label="Monitoring Board",
            pos=[x, y],
            width=w,
            height=h,
            no_title_bar=False,
            no_resize=False,
            no_collapse=False,
            show=True,
        ):
            self._visible = True

            # En-tête HUD
            with dpg.group(horizontal=True):
                dpg.add_text("SIMPAD", color=[0, 210, 255, 255])
                dpg.add_text("MONITORING BOARD", color=[255, 200, 0, 255])
                dpg.add_spacer(width=20)
                dpg.add_text("Gear:", color=[180, 180, 180, 255])
                dpg.add_text("N", tag="mb_lbl_gear", color=[46, 204, 113, 255])

            dpg.add_separator()
            dpg.add_spacer(height=4)

            # Indicateurs de signaux télémétriques
            dpg.add_text("Engine RPM:", color=[180, 180, 180, 255])
            dpg.add_progress_bar(tag="mb_bar_rpm", default_value=0.0, width=-1, overlay="0 RPM")
            dpg.add_spacer(height=4)

            # Grille 2 colonnes (Braking & Dynamics)
            with dpg.group(horizontal=True):
                with dpg.child_window(width=(w // 2) - 14, height=max(80, h - 110), border=True):
                    dpg.add_text("Braking & Traction", color=[0, 210, 255, 255])
                    dpg.add_spacer(height=2)
                    dpg.add_text("ABS (Freinage):", color=[180, 180, 180, 255])
                    dpg.add_progress_bar(tag="mb_bar_abs", default_value=0.0, width=-1)
                    dpg.add_spacer(height=4)
                    dpg.add_text("TC (Motricité):", color=[180, 180, 180, 255])
                    dpg.add_progress_bar(tag="mb_bar_tc", default_value=0.0, width=-1)

                with dpg.child_window(width=(w // 2) - 14, height=max(80, h - 110), border=True):
                    dpg.add_text("Dynamics & Chassis", color=[0, 210, 255, 255])
                    dpg.add_spacer(height=2)
                    dpg.add_text("Sur-Virage (Over):", color=[180, 180, 180, 255])
                    dpg.add_progress_bar(tag="mb_bar_over", default_value=0.0, width=-1)
                    dpg.add_spacer(height=4)
                    dpg.add_text("Vibreurs (Curbs):", color=[180, 180, 180, 255])
                    dpg.add_progress_bar(tag="mb_bar_travel", default_value=0.0, width=-1)

    def show(self) -> None:
        if dpg.does_item_exist(self._window_tag):
            dpg.show_item(self._window_tag)
            try:
                dpg.focus_item(self._window_tag)
            except Exception:
                pass
            self._visible = True

    def hide(self) -> None:
        if dpg.does_item_exist(self._window_tag):
            dpg.hide_item(self._window_tag)
            self._visible = False

    def update_telemetry(self, sensors: VehicleSensors) -> None:
        if not self._visible or not dpg.does_item_exist(self._window_tag):
            return

        gear_str = "R" if sensors.gear == -1 else ("N" if sensors.gear == 0 else str(sensors.gear))
        if dpg.does_item_exist("mb_lbl_gear"):
            dpg.set_value("mb_lbl_gear", gear_str)

        if dpg.does_item_exist("mb_bar_rpm"):
            rpm_ratio = min(1.0, max(0.0, sensors.rpm_ratio))
            dpg.set_value("mb_bar_rpm", rpm_ratio)
            dpg.configure_item("mb_bar_rpm", overlay=f"{int(rpm_ratio * sensors.engine_max_rpm)} RPM")

        if dpg.does_item_exist("mb_bar_abs"):
            dpg.set_value("mb_bar_abs", min(1.0, max(0.0, sensors.lock_intensity)))

        if dpg.does_item_exist("mb_bar_tc"):
            dpg.set_value("mb_bar_tc", min(1.0, max(0.0, sensors.spin_intensity)))

        if dpg.does_item_exist("mb_bar_over"):
            dpg.set_value("mb_bar_over", min(1.0, max(0.0, sensors.oversteer_intensity)))

        if dpg.does_item_exist("mb_bar_travel"):
            dpg.set_value("mb_bar_travel", min(1.0, max(0.0, sensors.travel_intensity)))
