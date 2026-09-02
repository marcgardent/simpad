"""
ABS Gauge Widget — Far-left vertical ABS intervention intensity bar in compact HUD canvas.
Displays ABS regulation / wheel lockup percentage in Purple (#a855f7 / [168, 85, 247]).
"""

from typing import Dict, Any
import dearpygui.dearpygui as dpg
from src.gui.dashboards.widgets.base_widget import BaseHudWidget, lerp
from src.telemetry.sensors import VehicleSensors


class AbsGaugeWidget(BaseHudWidget):
    """
    Jauge ABS (Extrême Gauche du HUD, à gauche du Frein).
    Affiche l'intensité de régulation ABS / blocage des roues en Violet (#a855f7).
    """

    def __init__(self):
        self.display_abs: float = 0.0

    def draw(
        self,
        drawlist_tag: str,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        if "abs" in extra_data:
            raw_abs = float(extra_data["abs"])
        else:
            raw_abs = sensors.ecu_abs_active * 100.0

        # LERP smoothing (réactivité instantanée)
        self.display_abs = lerp(self.display_abs, raw_abs, 0.25)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        gauge_width = 15.0 * scale_x
        gauge_height = 245.0 * scale_y
        abs_x = center_x - (265.0 * scale_x)
        gauge_y = 15.0 * scale_y

        # Background (Semi-transparent glass track)
        dpg.draw_rectangle(
            pmin=[abs_x, gauge_y],
            pmax=[abs_x + gauge_width, gauge_y + gauge_height],
            fill=[17, 24, 39, 120],
            color=[30, 41, 59, 200],
            thickness=1,
            parent=drawlist_tag,
        )

        # Fill: Purple (#a855f7 / [168, 85, 247]) on ABS regulation
        fill_height = (max(0.0, min(100.0, self.display_abs)) / 100.0) * gauge_height
        if fill_height > 0.5:
            fill_y_min = gauge_y + gauge_height - fill_height
            dpg.draw_rectangle(
                pmin=[abs_x, fill_y_min],
                pmax=[abs_x + gauge_width, gauge_y + gauge_height],
                fill=[168, 85, 247, 255],
                color=[0, 0, 0, 0],
                parent=drawlist_tag,
            )

        # Level Indicator: ABS level from cockpit setting (e.g. "5" or "ABS")
        if sensors.ecu_abs_level > 0:
            dpg.draw_text(
                pos=[abs_x + (gauge_width / 2.0) - (4.0 * scale_x), gauge_y + gauge_height + (3.0 * scale_y)],
                text=str(sensors.ecu_abs_level),
                color=[168, 85, 247, 220],
                size=11,
                parent=drawlist_tag,
            )
