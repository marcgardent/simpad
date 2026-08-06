"""
Gear Speed Widget — Uses digits-only in WHITE for speed, positioned at the top of the canvas.
1. Speed digits in WHITE at the top.
2. Gear display directly below the speed.
"""

from typing import Dict, Any
import dearpygui.dearpygui as dpg
from src.gui.dashboards.widgets.base_widget import BaseHudWidget, lerp
from src.telemetry.sensors import VehicleSensors


class GearSpeedWidget(BaseHudWidget):
    """
    Vitesse (Chiffres seuls en BLANC tout en haut du canvas) & Rapport de Boîte (Gear en dessous).
    """

    def __init__(self):
        self.display_speed: float = 0.0

    def draw(
        self,
        drawlist_tag: str,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        # Determine Gear string
        if "gear" in extra_data:
            gear_str = str(extra_data["gear"])
        else:
            g = sensors.gear
            gear_str = "R" if g == -1 else ("N" if g == 0 else str(g))

        # Speed calculation (convert m/s to km/h if raw telemetry speed is m/s)
        raw_speed = extra_data.get("speed", sensors.vehicle_speed * 3.6)
        self.display_speed = lerp(self.display_speed, raw_speed, 0.2)
        speed_int = max(0, int(round(self.display_speed)))

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        speed_font_size = int(round(52.0 * scale_y))
        gear_font_size = int(round(110.0 * scale_y))

        # 1. TOUT EN HAUT DU CANVAS: VITESSE (Chiffres seuls en BLANC, SANS "KM/H")
        speed_str = str(speed_int)
        speed_x_offset = len(speed_str) * (speed_font_size * 0.28)
        speed_y = 12.0 * scale_y

        # Rectangle noir sous la vitesse quand elle passe sous 60 Km/h
        if self.display_speed < 60.0:
            box_w = max(80.0 * scale_x, len(speed_str) * (speed_font_size * 0.60) + 16.0 * scale_x)
            box_h = speed_font_size + 6.0 * scale_y
            dpg.draw_rectangle(
                pmin=[center_x - (box_w / 2.0), speed_y - 2.0 * scale_y],
                pmax=[center_x + (box_w / 2.0), speed_y + box_h],
                fill=[0, 0, 0, 255],        # Rectangle Noir Opaque
                color=[30, 41, 59, 255],     # Contour sombre
                thickness=1,
                parent=drawlist_tag,
            )

        dpg.draw_text(
            pos=[center_x - speed_x_offset, speed_y],
            text=speed_str,
            color=[255, 255, 255, 255],  # White (Blanc)
            size=speed_font_size,
            parent=drawlist_tag,
        )


        # 2. EN DESSOUS: GEAR (Rapport)
        gear_x_offset = len(gear_str) * (gear_font_size * 0.28)
        dpg.draw_text(
            pos=[center_x - gear_x_offset, 58.0 * scale_y],
            text=gear_str,
            color=[255, 255, 255, 255],
            size=gear_font_size,
            parent=drawlist_tag,
        )
