"""
Throttle Gauge Widget — Right vertical throttle pedal intensity bar in compact canvas.
Displays pure driver acceleration percentage in Green (#22c55e / [34, 197, 94]).
"""

from typing import Dict, Any
import dearpygui.dearpygui as dpg
from src.gui.dashboards.widgets.base_widget import BaseHudWidget, lerp
from src.telemetry.sensors import VehicleSensors


class ThrottleGaugeWidget(BaseHudWidget):
    """
    Jauge d'Accélérateur Pure (Centre-Droit du HUD compact).
    Affiche la course réelle de la pédale d'accélérateur en Vert (#22c55e).
    """

    def __init__(self):
        self.display_throttle: float = 0.0

    def draw(
        self,
        drawlist_tag: str,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        raw_throttle = float(extra_data.get("throttle", sensors.unfiltered_throttle * 100.0))

        # LERP smoothing
        self.display_throttle = lerp(self.display_throttle, raw_throttle, 0.15)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        gauge_width = 30.0 * scale_x
        gauge_height = 245.0 * scale_y
        throttle_x = center_x + (220.0 * scale_x)
        gauge_y = 15.0 * scale_y

        # Background (Semi-transparent glass track)
        dpg.draw_rectangle(
            pmin=[throttle_x, gauge_y],
            pmax=[throttle_x + gauge_width, gauge_y + gauge_height],
            fill=[17, 24, 39, 120],
            color=[30, 41, 59, 200],
            thickness=1,
            parent=drawlist_tag,
        )

        # Fill: Pure Green (#22c55e)
        fill_height = (max(0.0, min(100.0, self.display_throttle)) / 100.0) * gauge_height
        if fill_height > 0.5:
            fill_y_min = gauge_y + gauge_height - fill_height
            dpg.draw_rectangle(
                pmin=[throttle_x, fill_y_min],
                pmax=[throttle_x + gauge_width, gauge_y + gauge_height],
                fill=[34, 197, 94, 255],
                color=[0, 0, 0, 0],
                parent=drawlist_tag,
            )
