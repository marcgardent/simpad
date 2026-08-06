"""
Throttle Gauge Widget — Right vertical acceleration intensity bar in compact canvas.
Displays acceleration percentage and changes color to Yellow (#eab308) on wheelspin (patinage).
"""

from typing import Dict, Any
import dearpygui.dearpygui as dpg
from src.gui.dashboards.widgets.base_widget import BaseHudWidget, lerp
from src.telemetry.sensors import VehicleSensors


class ThrottleGaugeWidget(BaseHudWidget):
    """
    Jauge d'Accélérateur (Côté Droit du HUD compact).
    Affiche l'intensité de l'accélération et change de couleur en cas de patinage (wheelspin).
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
        if "throttle" in extra_data:
            raw_throttle = float(extra_data["throttle"])
        elif sensors.unfiltered_throttle > 0.0:
            raw_throttle = sensors.unfiltered_throttle * 100.0
        else:
            raw_throttle = sensors.spin_intensity * 100.0

        is_spinning = extra_data.get("wheelspin", False) or (sensors.spin_intensity > 0.05)

        # LERP smoothing
        self.display_throttle = lerp(self.display_throttle, raw_throttle, 0.15)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        gauge_width = 32.0 * scale_x
        gauge_height = 245.0 * scale_y
        throttle_x = center_x + (260.0 * scale_x) - gauge_width
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

        # Fill: Green (#22c55e) normally, turns Yellow (#eab308) on wheelspin
        fill_height = (max(0.0, min(100.0, self.display_throttle)) / 100.0) * gauge_height
        if fill_height > 0.5:
            fill_color = [234, 179, 8, 255] if is_spinning else [34, 197, 94, 255]
            fill_y_min = gauge_y + gauge_height - fill_height
            dpg.draw_rectangle(
                pmin=[throttle_x, fill_y_min],
                pmax=[throttle_x + gauge_width, gauge_y + gauge_height],
                fill=fill_color,
                color=[0, 0, 0, 0],
                parent=drawlist_tag,
            )
