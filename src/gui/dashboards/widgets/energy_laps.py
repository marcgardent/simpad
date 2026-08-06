"""
Energy & Laps Widget — Remaining energy and laps display positioned under gear in compact canvas.
"""

from typing import Dict, Any
import dearpygui.dearpygui as dpg
from src.gui.dashboards.widgets.base_widget import BaseHudWidget
from src.telemetry.sensors import VehicleSensors


class EnergyLapsWidget(BaseHudWidget):
    """
    Énergie & Tours Restants (Positionné sur la droite sous le Gear).
    """

    def draw(
        self,
        drawlist_tag: str,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        energy = float(extra_data.get("energyLaps", 0.0))
        remaining_laps = int(extra_data.get("remainingLaps", 0))

        val_str = f"{energy:.1f} / {remaining_laps}" if (energy > 0 or remaining_laps > 0) else "-- / --"

        sub_str = "ÉNERGIE / TOURS"

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0

        val_font_size = int(round(16.0 * scale_y))
        sub_font_size = int(round(10.0 * scale_y))

        right_margin = 40.0 * scale_x
        val_x_pos = canvas_w - right_margin - (len(val_str) * val_font_size * 0.55)
        sub_x_pos = canvas_w - right_margin - (len(sub_str) * sub_font_size * 0.55)

        base_y = 170.0 * scale_y

        # Value text
        dpg.draw_text(
            pos=[val_x_pos, base_y],
            text=val_str,
            color=[255, 255, 255, 255],
            size=val_font_size,
            parent=drawlist_tag,
        )

        # Subtext label
        dpg.draw_text(
            pos=[sub_x_pos, base_y + (20.0 * scale_y)],
            text=sub_str,
            color=[148, 163, 184, 255],
            size=sub_font_size,
            parent=drawlist_tag,
        )
