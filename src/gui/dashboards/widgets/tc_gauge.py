"""
TC Gauge Widget — Far-right vertical Traction Control intervention intensity bar in compact HUD canvas.
Displays TC power cuts / wheelspin percentage in Cyan (#00dcff / [0, 220, 255]).
"""

from typing import Dict, Any
import dearpygui.dearpygui as dpg
from src.gui.dashboards.widgets.base_widget import BaseHudWidget, lerp
from src.telemetry.sensors import VehicleSensors


class TcGaugeWidget(BaseHudWidget):
    """
    Jauge TC (Extrême Droite du HUD, à droite de l'Accélérateur).
    Affiche l'intensité de coupure TC / patinage en Cyan (#00dcff / [0, 220, 255]).
    """

    def __init__(self):
        self.display_tc: float = 0.0

    def draw(
        self,
        drawlist_tag: str,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        if "tc" in extra_data:
            raw_tc = float(extra_data["tc"])
        else:
            raw_tc = max(sensors.ecu_tc_active, sensors.spin_intensity) * 100.0

        # LERP smoothing (réactivité instantanée)
        self.display_tc = lerp(self.display_tc, raw_tc, 0.25)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        gauge_width = 15.0 * scale_x
        gauge_height = 245.0 * scale_y
        tc_x = center_x + (250.0 * scale_x)
        gauge_y = 15.0 * scale_y

        # Background (Semi-transparent glass track)
        dpg.draw_rectangle(
            pmin=[tc_x, gauge_y],
            pmax=[tc_x + gauge_width, gauge_y + gauge_height],
            fill=[17, 24, 39, 120],
            color=[30, 41, 59, 200],
            thickness=1,
            parent=drawlist_tag,
        )

        # Fill: Cyan (#00dcff / [0, 220, 255]) on TC regulation
        fill_height = (max(0.0, min(100.0, self.display_tc)) / 100.0) * gauge_height
        if fill_height > 0.5:
            fill_y_min = gauge_y + gauge_height - fill_height
            dpg.draw_rectangle(
                pmin=[tc_x, fill_y_min],
                pmax=[tc_x + gauge_width, gauge_y + gauge_height],
                fill=[0, 220, 255, 255],
                color=[0, 0, 0, 0],
                parent=drawlist_tag,
            )

        # Level Indicator: TC level from cockpit setting (e.g. "3" or "TC")
        if sensors.ecu_tc_level > 0:
            dpg.draw_text(
                pos=[tc_x + (gauge_width / 2.0) - (4.0 * scale_x), gauge_y + gauge_height + (3.0 * scale_y)],
                text=str(sensors.ecu_tc_level),
                color=[0, 220, 255, 220],
                size=11,
                parent=drawlist_tag,
            )
