"""
Rev Indicator Widget — Left/Right triangle indicators for underrev and overrev warnings, aligned with compact Gear.
"""

from typing import Dict, Any
import dearpygui.dearpygui as dpg
from src.gui.dashboards.widgets.base_widget import BaseHudWidget
from src.telemetry.sensors import VehicleSensors


class RevIndicatorWidget(BaseHudWidget):
    """
    Indicateurs de Régime Moteur (Triangles du HUD).
    - Triangle gauche (sous-régime / downshift sweet spot).
    - Triangle droit (sur-régime / upshift redline).
    """

    def draw(
        self,
        drawlist_tag: str,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        underrev = extra_data.get("underrev", sensors.underrev_intensity > 0.1)
        overrev = extra_data.get("overrev", sensors.overrev_intensity > 0.1)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        # Underrev Triangle (Left)
        if underrev:
            p1 = [center_x - (130.0 * scale_x), 110.0 * scale_y]
            p2 = [center_x - (90.0 * scale_x), 80.0 * scale_y]
            p3 = [center_x - (90.0 * scale_x), 140.0 * scale_y]
            dpg.draw_triangle(
                p1=p1,
                p2=p2,
                p3=p3,
                fill=[255, 255, 255, 255],
                color=[255, 255, 255, 255],
                parent=drawlist_tag,
            )

        # Overrev Triangle (Right)
        if overrev:
            p1 = [center_x + (130.0 * scale_x), 110.0 * scale_y]
            p2 = [center_x + (90.0 * scale_x), 80.0 * scale_y]
            p3 = [center_x + (90.0 * scale_x), 140.0 * scale_y]
            dpg.draw_triangle(
                p1=p1,
                p2=p2,
                p3=p3,
                fill=[255, 255, 255, 255],
                color=[255, 255, 255, 255],
                parent=drawlist_tag,
            )
