"""
Delta Timer Widget — Display expected lap delta time positioned below gear in compact canvas.
"""

from typing import Dict, Any
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QPen
from src.gui.overlay.base_widget import BaseQtHudWidget
from src.telemetry.sensors import VehicleSensors


class QtDeltaTimerWidget(BaseQtHudWidget):
    """
    Chrono Delta Attendu (Positionné sous le Gear).
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
        expected_str = str(extra_data.get("expectedTime", sensors.delta_time_str))

        if expected_str.startswith("-"):
            text_color = QColor(34, 197, 94, 255)  # Green
        elif expected_str in ("--", "0.000", "0", ""):
            text_color = QColor(255, 255, 255, 255)  # White
        else:
            text_color = QColor(239, 68, 68, 255)  # Red

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 300.0

        font_size = int(round(32.0 * scale_y))
        y_pos = 170.0 * scale_y

        font = QFont(self.font_family, font_size, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QPen(text_color))
        painter.drawText(QRectF(0, y_pos, canvas_w, font_size + 10), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, expected_str)
