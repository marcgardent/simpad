"""
Aero Bar Widget — Bottom horizontal aerodynamic downforce bar in compact canvas.
Dynamically bound to vehicle speed aerodynamic load (0% to 100%).
Color lerps from Blue (0%) to Orange (100%).
"""

from typing import Dict, Any
import dearpygui.dearpygui as dpg
from src.gui.dashboards.widgets.base_widget import BaseHudWidget, lerp
from src.telemetry.sensors import VehicleSensors


def get_aero_color_ramp(a: float) -> list:
    """Calculates color ramp: Red (0%) -> Violet (33%) -> Blue (66%) -> Green (100%)."""
    a = max(0.0, min(1.0, a))
    if a <= 0.3333:
        t = a / 0.3333
        r = int(round(lerp(239.0, 168.0, t)))
        g = int(round(lerp(68.0, 85.0, t)))
        b = int(round(lerp(68.0, 247.0, t)))
    elif a <= 0.6666:
        t = (a - 0.3333) / 0.3333
        r = int(round(lerp(168.0, 59.0, t)))
        g = int(round(lerp(85.0, 130.0, t)))
        b = int(round(lerp(247.0, 246.0, t)))
    else:
        t = (a - 0.6666) / 0.3334
        r = int(round(lerp(59.0, 34.0, t)))
        g = int(round(lerp(130.0, 197.0, t)))
        b = int(round(lerp(246.0, 94.0, t)))
    return [r, g, b, 255]


class AeroBarWidget(BaseHudWidget):
    """
    Barre d'Appui Aérodynamique (Bas du HUD compact).
    Ramp de couleur : Rouge (0%) -> Violet (33%) -> Bleu (66%) -> Vert (100%).
    Indicateur 'cleanlap' positionné juste sous la jauge aérodynamique.
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

        # Fill using 4-stage color ramp: Rouge -> Violet -> Bleu -> Vert
        a = max(0.0, min(1.0, self.display_aero / 100.0))
        bar_color = get_aero_color_ramp(a)

        fill_width = a * aero_width
        if fill_width > 0.5:
            dpg.draw_rectangle(
                pmin=[aero_x, aero_y],
                pmax=[aero_x + fill_width, aero_y + aero_height],
                fill=bar_color,
                color=[0, 0, 0, 0],
                parent=drawlist_tag,
            )

        # ── Indicateur 'cleanlap' (Pastille seule, sans texte) positionné SOUS la jauge aérodynamique ──
        lap_flag = extra_data.get("lap_flag", getattr(sensors, "lap_flag", 2))
        if lap_flag == 0:
            dot_color = [239, 68, 68, 255]     # ROUGE (Invalid Lap)
        elif lap_flag == 1:
            dot_color = [249, 115, 22, 255]    # ORANGE (Out-lap)
        else:
            dot_color = [34, 197, 94, 255]     # VERT (Clean Lap)

        dot_center_x = center_x
        dot_center_y = aero_y + aero_height + (16.0 * scale_y)
        dot_radius = 9.0 * scale_y

        dpg.draw_circle(
            center=[dot_center_x, dot_center_y],
            radius=dot_radius,
            fill=dot_color,
            color=[15, 23, 42, 255],
            thickness=2,
            parent=drawlist_tag,
        )
