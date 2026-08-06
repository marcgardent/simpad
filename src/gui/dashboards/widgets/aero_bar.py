"""
Aero Bar Widget — Bottom horizontal aerodynamic downforce bar in compact canvas.
Dynamically bound to vehicle speed aerodynamic load (0% to 100%).
Color lerps from Blue (0%) to Orange (100%).
"""

from typing import Dict, Any
import dearpygui.dearpygui as dpg
from src.gui.dashboards.widgets.base_widget import BaseHudWidget, lerp
from src.telemetry.sensors import VehicleSensors


class AeroBarWidget(BaseHudWidget):
    """
    Barre d'Appui Aérodynamique (Bas du HUD compact).
    Liée dynamiquement à la charge aérodynamique calculée depuis la vitesse véhicule.
    """

    def __init__(self):
        self.display_aero: float = 0.0

    def draw(
        self,
        drawlist_tag: str,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        if "aero" in extra_data:
            raw_aero = float(extra_data["aero"])
        else:
            raw_aero = sensors.aero_load * 100.0

        # Smoothing with LERP
        self.display_aero = lerp(self.display_aero, raw_aero, 0.15)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        aero_width = 440.0 * scale_x
        aero_height = 15.0 * scale_y
        aero_x = center_x - (aero_width / 2.0)
        aero_y = 245.0 * scale_y

        # Background (Semi-transparent track)
        dpg.draw_rectangle(
            pmin=[aero_x, aero_y],
            pmax=[aero_x + aero_width, aero_y + aero_height],
            fill=[17, 24, 39, 120],
            color=[30, 41, 59, 200],
            thickness=1,
            parent=drawlist_tag,
        )

        # Fill with lerped Blue (59, 130, 246) -> Orange (249, 115, 22)
        a = max(0.0, min(1.0, self.display_aero / 100.0))
        r = int(round(lerp(59.0, 249.0, a)))
        g = int(round(lerp(130.0, 115.0, a)))
        b = int(round(lerp(246.0, 22.0, a)))

        fill_width = a * aero_width
        if fill_width > 0.5:
            dpg.draw_rectangle(
                pmin=[aero_x, aero_y],
                pmax=[aero_x + fill_width, aero_y + aero_height],
                fill=[r, g, b, 255],
                color=[0, 0, 0, 0],
                parent=drawlist_tag,
            )
