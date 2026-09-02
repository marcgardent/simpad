"""
Brake Gauge Widget — Left vertical brake pedal intensity bar in compact canvas.
Displays pure driver brake percentage in Red (#ef4444 / [239, 68, 68]).
"""

from typing import Dict, Any
import dearpygui.dearpygui as dpg
from src.gui.dashboards.widgets.base_widget import BaseHudWidget, lerp
from src.telemetry.sensors import VehicleSensors


class BrakeGaugeWidget(BaseHudWidget):
    """
    Jauge de Frein Pure (Centre-Gauche du HUD compact).
    Affiche la course réelle de la pédale de frein en Rouge (#ef4444).
    """

    def __init__(self):
        self.display_brake: float = 0.0

    def draw(
        self,
        drawlist_tag: str,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        raw_brake = float(extra_data.get("brake", sensors.unfiltered_brake * 100.0))

        # LERP smoothing
        self.display_brake = lerp(self.display_brake, raw_brake, 0.15)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        gauge_width = 30.0 * scale_x
        gauge_height = 245.0 * scale_y
        brake_x = center_x - (250.0 * scale_x)
        gauge_y = 15.0 * scale_y

        # Background (Semi-transparent glass track)
        dpg.draw_rectangle(
            pmin=[brake_x, gauge_y],
            pmax=[brake_x + gauge_width, gauge_y + gauge_height],
            fill=[17, 24, 39, 120],
            color=[30, 41, 59, 200],
            thickness=1,
            parent=drawlist_tag,
        )

        # Fill: Pure Red (#ef4444)
        fill_height = (max(0.0, min(100.0, self.display_brake)) / 100.0) * gauge_height
        if fill_height > 0.5:
            fill_y_min = gauge_y + gauge_height - fill_height
            dpg.draw_rectangle(
                pmin=[brake_x, fill_y_min],
                pmax=[brake_x + gauge_width, gauge_y + gauge_height],
                fill=[239, 68, 68, 255],
                color=[0, 0, 0, 0],
                parent=drawlist_tag,
            )
