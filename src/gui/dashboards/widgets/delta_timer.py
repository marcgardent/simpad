"""
Delta Timer Widget — Display expected lap delta time positioned below gear in compact canvas.
"""

from typing import Dict, Any
import dearpygui.dearpygui as dpg
from src.gui.dashboards.widgets.base_widget import BaseHudWidget
from src.telemetry.sensors import VehicleSensors


class DeltaTimerWidget(BaseHudWidget):
    """
    Chrono Delta Attendu (Positionné sous le Gear).
    """

    def draw(
        self,
        drawlist_tag: str,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        expected_str = str(extra_data.get("expectedTime", "--"))


        if expected_str.startswith("-"):
            text_color = [34, 197, 94, 255]  # Green
        elif expected_str in ("--", "0.000", "0", ""):
            text_color = [255, 255, 255, 255]  # White
        else:
            text_color = [239, 68, 68, 255]  # Red

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        font_size = int(round(32.0 * scale_y))
        y_pos = 170.0 * scale_y
        x_offset = len(expected_str) * (font_size * 0.28)

        dpg.draw_text(
            pos=[center_x - x_offset, y_pos],
            text=expected_str,
            color=text_color,
            size=font_size,
            parent=drawlist_tag,
        )
