"""
Sector Times Widget — 3-sector time boxes (S1, S2, S3) positioned below Delta timer in compact canvas.
"""

from typing import Dict, Any, List
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QBrush
from src.gui.overlay.base_widget import BaseQtHudWidget
from src.telemetry.sensors import VehicleSensors


class QtSectorTimesWidget(BaseQtHudWidget):
    """
    Secteurs de Tour S1, S2, S3 (Positionnés sous le Delta et le Gear).
    """

    def __init__(self, font_family: str = "Anta"):
        self.font_family = font_family
        self._last_rendered_sector: int = -1

    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        sectors: List[Dict[str, Any]] = extra_data.get("sectors", sensors.sectors_list)

        curr_sec = sensors.current_sector
        if curr_sec != self._last_rendered_sector:
            try:
                from src.telemetry.overlay_anomaly_logger import OverlayAnomalyLogger
                OverlayAnomalyLogger.get_instance().check_sector_update(
                    current_sector=curr_sec,
                    raw_sector=curr_sec,
                    source="QtSectorTimesWidget",
                    s1_time=sensors.sector1_time,
                    s2_time=sensors.sector2_time,
                    s3_time=sensors.sector3_time,
                    s1_delta=sensors.sector1_delta,
                    s2_delta=sensors.sector2_delta,
                    s3_delta=sensors.sector3_delta,
                    lap_dist=sensors.lap_dist if hasattr(sensors, "lap_dist") else 0.0,
                    speed_kmh=sensors.vehicle_speed * 3.6,
                )
            except Exception:
                pass
            self._last_rendered_sector = curr_sec

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        sector_w = 90.0 * scale_x
        sector_h = 28.0 * scale_y
        sector_spacing = 8.0 * scale_x

        total_width = (sector_w * 3.0) + (sector_spacing * 2.0)
        start_x = center_x - (total_width / 2.0)
        sector_y = 210.0 * scale_y

        font_size = max(10, int(round(14.0 * scale_y)))
        font = QFont(self.font_family)
        font.setPixelSize(font_size)
        font.setBold(True)
        painter.setFont(font)

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
                    bg_color = QColor(22, 163, 74, 255)      # Vert (Gain)
                    border_color = QColor(34, 197, 94, 255)
                elif delta_val > 0.0:
                    bg_color = QColor(185, 28, 28, 255)     # Rouge (Perte)
                    border_color = QColor(239, 68, 68, 255)
                else:
                    bg_color = QColor(15, 23, 42, 255)
                    border_color = QColor(51, 65, 85, 255)
            else:
                # Secteur terminé ou en attente -> Affichage du chrono de secteur gelé
                disp_text = s_time
                if s_status == "invalid":
                    bg_color = QColor(15, 23, 42, 255)
                    border_color = QColor(51, 65, 85, 255)
                elif s_status == "green":
                    bg_color = QColor(22, 163, 74, 255)
                    border_color = QColor(34, 197, 94, 255)
                elif s_status == "purple":
                    bg_color = QColor(147, 51, 234, 255)
                    border_color = QColor(168, 85, 247, 255)
                else:
                    bg_color = QColor(15, 23, 42, 255)
                    border_color = QColor(51, 65, 85, 255)

            # Bordure blanche marquée sur le secteur en cours
            if is_current:
                border_color = QColor(255, 255, 255, 255)
                pen_width = 2
            else:
                pen_width = 1

            # Box background
            rect = QRectF(s_x, sector_y, sector_w, sector_h)
            painter.setBrush(QBrush(bg_color))
            painter.setPen(QPen(border_color, pen_width))
            painter.drawRect(rect)

            # Time text
            painter.setPen(QPen(QColor(255, 255, 255, 255)))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, disp_text)
