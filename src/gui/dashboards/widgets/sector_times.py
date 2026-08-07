"""
Sector Times Widget — 3-sector time boxes (S1, S2, S3) positioned below Delta timer in compact canvas.
"""

from typing import Dict, Any, List
import dearpygui.dearpygui as dpg
from src.gui.dashboards.widgets.base_widget import BaseHudWidget
from src.telemetry.sensors import VehicleSensors


class SectorTimesWidget(BaseHudWidget):
    """
    Secteurs de Tour S1, S2, S3 (Positionnés sous le Delta et le Gear).
    """

    def draw(
        self,
        drawlist_tag: str,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        sectors: List[Dict[str, str]] = extra_data.get(
            "sectors",
            [
                {"time": "--", "status": "default"},
                {"time": "--", "status": "default"},
                {"time": "--", "status": "default"},
            ],
        )


        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        sector_w = 90.0 * scale_x

        sector_h = 28.0 * scale_y
        sector_spacing = 8.0 * scale_x

        total_width = (sector_w * 3.0) + (sector_spacing * 2.0)
        start_x = center_x - (total_width / 2.0)
        sector_y = 210.0 * scale_y

        font_size = int(round(14.0 * scale_y))

        for i in range(min(3, len(sectors))):
            s_x = start_x + (i * (sector_w + sector_spacing))
            sec = sectors[i]
            s_time = sec.get("time", "--")
            s_status = sec.get("status", "default")
            is_current = sec.get("is_current", False)
            delta_val = float(sec.get("delta", 0.0))
            delta_str = sec.get("delta_str", "--")

            # Tant que le secteur n'est pas terminé, afficher le Delta Live du secteur
            if is_current and delta_str != "--":
                disp_text = delta_str
                if delta_val < 0.0:
                    bg_color = [22, 163, 74, 255]      # Vert (Gain de temps dans le secteur)
                    border_color = [34, 197, 94, 255]
                elif delta_val > 0.0:
                    bg_color = [185, 28, 28, 255]     # Rouge (Perte de temps dans le secteur)
                    border_color = [239, 68, 68, 255]
                else:
                    bg_color = [15, 23, 42, 255]
                    border_color = [51, 65, 85, 255]
            else:
                # Secteur terminé ou en attente -> Affichage du chrono de secteur gelé
                disp_text = s_time
                if s_status == "invalid":
                    bg_color = [15, 23, 42, 255]
                    border_color = [51, 65, 85, 255]
                elif s_status == "green":
                    bg_color = [22, 163, 74, 255]
                    border_color = [34, 197, 94, 255]
                elif s_status == "purple":
                    bg_color = [147, 51, 234, 255]
                    border_color = [168, 85, 247, 255]
                else:
                    bg_color = [15, 23, 42, 255]
                    border_color = [51, 65, 85, 255]

            # Bordure blanche marquée sur le secteur en cours d'exécution
            if is_current:
                border_color = [255, 255, 255, 255]
                border_thickness = 2
            else:
                border_thickness = 1

            # Box background
            dpg.draw_rectangle(
                pmin=[s_x, sector_y],
                pmax=[s_x + sector_w, sector_y + sector_h],
                fill=bg_color,
                color=border_color,
                thickness=border_thickness,
                parent=drawlist_tag,
            )

            # Time text
            text_x = s_x + (sector_w / 2.0) - (len(disp_text) * font_size * 0.28)
            text_y = sector_y + (sector_h / 2.0) - (font_size * 0.5)

            dpg.draw_text(
                pos=[text_x, text_y],
                text=disp_text,
                color=[255, 255, 255, 255],
                size=font_size,
                parent=drawlist_tag,
            )


