"""
Delta Timer Widget — Display expected lap delta time positioned below gear in compact canvas.
"""

from typing import Dict, Any
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QPen
from .base_widget import BaseQtHudWidget
from simpad_qt.core.telemetry import VehicleSensors


class QtDeltaTimerWidget(BaseQtHudWidget):
    """
    Delta Timer / Lap Time (Positioned below Gear).
    - On track: Displays Live Delta (e.g. '-0.150' in Green, '+0.240' in Red).
    - Line crossing: Displays Completed Lap Time (format MM:ss.mmm)
      with color coding:
        * Purple (Session / All-Time Best)
        * Green (Personal Best)
        * Yellow (No improvement / Slower)
        * Grey (Invalid Lap)
    """

    def __init__(self, font_family: str = "Anta"):
        self.font_family = font_family

    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        is_freeze = extra_data.get("isLapFreezeActive", sensors.is_lap_freeze_active)
        lap_flag = extra_data.get("lap_flag", sensors.lap_flag)

        if is_freeze:
            # Line crossing mode: Completed Lap Time (MM:ss.mmm)
            lap_time_str = str(extra_data.get("lastLapTime", sensors.last_lap_time_str))
            disp_str = lap_time_str if lap_time_str not in ("", "--") else "--:--.---"
            lap_status = str(extra_data.get("lastLapStatus", sensors.last_lap_status))

            if lap_flag == 0 or lap_status == "invalid":
                # Invalid lap -> Grey
                text_color = QColor(156, 163, 175, 255)
            elif lap_status == "purple":
                # Overall session best -> Purple
                text_color = QColor(168, 85, 247, 255)
            elif lap_status == "green":
                # Personal improvement -> Green
                text_color = QColor(34, 197, 94, 255)
            elif lap_status in ("yellow", "red"):
                # No improvement / slower -> Yellow
                text_color = QColor(234, 179, 8, 255)
            else:
                text_color = QColor(255, 255, 255, 255)
        else:
            # On-track mode: Live Delta
            expected_str = str(extra_data.get("expectedTime", sensors.delta_time_str))
            disp_str = expected_str

            if lap_flag == 0:
                # Invalid lap -> Grey
                text_color = QColor(156, 163, 175, 255)
            elif expected_str.startswith("-"):
                # Ahead -> Green
                text_color = QColor(34, 197, 94, 255)
            elif expected_str in ("--", "0.000", "+0.000", "-0.000", "0", ""):
                text_color = QColor(255, 255, 255, 255)
            else:
                # Behind -> Red
                text_color = QColor(239, 68, 68, 255)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0

        font_size = max(14, int(round(32.0 * scale_y)))
        y_pos = 170.0 * scale_y

        font = QFont(self.font_family)
        font.setPixelSize(font_size)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(text_color))
        painter.drawText(
            QRectF(0, y_pos, canvas_w, font_size + 10 * scale_y),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            disp_str,
        )
