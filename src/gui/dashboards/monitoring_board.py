"""
monitoringBoard — Live Telemetry Curves Monitor HUD Overlay (Borderless).
Positioned at Top-Middle third of the primary monitor screen (X=Width/3, Y=0, W=Width/3, H=Height/3).
Renders real-time live telemetry signal curves (ABS, TC, Oversteer, Understeer, RPM, Curbs, Haptics).
"""

import dearpygui.dearpygui as dpg
from src.gui.dashboards.base import BaseDashboard
from src.telemetry.sensors import VehicleSensors
from src.utils.window_utils import get_3x3_grid_rect


class MonitoringBoard(BaseDashboard):
    """
    Tableau de bord 'monitoringBoard' : Graphe de courbes télémétriques temps réel en overlay borderless.
    Positionné de manière fixe dans le tiers haut / milieu de l'écran (col=1, row=0).
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
            no_title_bar=True,   # Borderless
            no_resize=True,      # Borderless
            no_move=True,        # Borderless
            no_collapse=True,    # Borderless
            show=False,
        ):
            self._visible = False

            # En-tête HUD Borderless
            with dpg.group(horizontal=True):
                dpg.add_text("SIMPAD", color=[0, 210, 255, 255])
                dpg.add_text("MONITORING BOARD", color=[255, 200, 0, 255])
                dpg.add_spacer(width=20)
                dpg.add_text("Gear:", color=[180, 180, 180, 255])
                dpg.add_text("N", tag="mb_lbl_gear", color=[46, 204, 113, 255])

            dpg.add_separator()

            # Graphe de courbes télémétriques en temps réel
            with dpg.plot(no_title=True, height=-1, width=-1, tag="mb_plot"):
                dpg.add_plot_legend()
                dpg.add_plot_axis(dpg.mvXAxis, label="Time (s)", tag="mb_xaxis")
                with dpg.plot_axis(dpg.mvYAxis, label="Intensity [0.0 - 1.0]", tag="mb_yaxis"):
                    dpg.set_axis_limits("mb_yaxis", 0, 1.05)
                    dpg.add_line_series([], [], label="ABS Lock", tag="mb_series_abs")
                    dpg.add_line_series([], [], label="TC Spin", tag="mb_series_tc")
                    dpg.add_line_series([], [], label="Oversteer", tag="mb_series_over")
                    dpg.add_line_series([], [], label="Understeer", tag="mb_series_und")
                    dpg.add_line_series([], [], label="Engine RPM", tag="mb_series_rpm")
                    dpg.add_line_series([], [], label="Curbs Travel", tag="mb_series_travel")
                    dpg.add_line_series([], [], label="Synth Low (L)", tag="mb_series_low")
                    dpg.add_line_series([], [], label="Synth High (R)", tag="mb_series_high")

    def show(self) -> None:
        if dpg.does_item_exist(self._window_tag):
            x, y, w, h = get_3x3_grid_rect(col=1, row=0)
            dpg.configure_item(self._window_tag, pos=[x, y], width=w, height=h)
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

    def update_history_plots(self, t_list, d_abs, d_tc, d_over, d_und, d_rpm, d_travel, d_low, d_high) -> None:
        if not self._visible or not dpg.does_item_exist("mb_series_abs"):
            return

        try:
            dpg.set_value("mb_series_abs", [t_list, list(d_abs)])
            dpg.set_value("mb_series_tc", [t_list, list(d_tc)])
            dpg.set_value("mb_series_over", [t_list, list(d_over)])
            dpg.set_value("mb_series_und", [t_list, list(d_und)])
            dpg.set_value("mb_series_rpm", [t_list, list(d_rpm)])
            dpg.set_value("mb_series_travel", [t_list, list(d_travel)])
            dpg.set_value("mb_series_low", [t_list, list(d_low)])
            dpg.set_value("mb_series_high", [t_list, list(d_high)])
            if t_list:
                dpg.set_axis_limits("mb_xaxis", t_list[0], t_list[-1])
        except Exception:
            pass
