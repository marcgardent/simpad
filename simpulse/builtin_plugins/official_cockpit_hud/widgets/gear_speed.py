"""
Gear Speed Widget — Uses digits-only in WHITE for speed, positioned at the top of the canvas.
1. Speed digits in WHITE at the top.
2. Gear display directly below the speed.
"""

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QBrush
from .base_widget import BaseQtHudWidget, CockpitWidgetContext, lerp


class QtGearSpeedWidget(BaseQtHudWidget):
    """
    Speed (White digits only at top) & Gear Indicator (Gear below).
    """

    def __init__(self, font_family: str = "Anta"):
        self.display_speed: float = 0.0
        self.font_family = font_family

    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        context: CockpitWidgetContext,
    ) -> None:
        # 1. Gear indicator
        g = context.sensors.gear
        gear_str = "R" if g == -1 else ("N" if g == 0 else str(g))

        # 2. Speed with instant direct response (no LERP)
        scale = 0.621371 if context.speed_unit == "mph" else 1.0
        raw_speed = context.sensors.vehicle_speed * 3.6 * scale
        self.display_speed = raw_speed
        speed_int = max(0, int(round(self.display_speed)))
        speed_str = str(speed_int)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        speed_font_size = max(16, int(round(52.0 * scale_y)))
        gear_font_size = max(32, int(round(110.0 * scale_y)))

        # 3. Speed at top
        speed_y = 12.0 * scale_y

        # Black background box under speed when speed is below 60 km/h
        if self.display_speed < 60.0:
            box_w = max(80.0 * scale_x, len(speed_str) * (speed_font_size * 0.60) + 16.0 * scale_x)
            box_h = speed_font_size + 6.0 * scale_y
            painter.setBrush(QBrush(QColor(0, 0, 0, 255)))
            painter.setPen(QPen(QColor(30, 41, 59, 255), 1))
            painter.drawRect(QRectF(center_x - (box_w / 2.0), speed_y - 2.0 * scale_y, box_w, box_h))

        # Speed text in white
        speed_font = QFont(self.font_family)
        speed_font.setPixelSize(speed_font_size)
        speed_font.setBold(True)
        painter.setFont(speed_font)
        painter.setPen(QPen(QColor(255, 255, 255, 255)))
        painter.drawText(QRectF(0, speed_y, canvas_w, speed_font_size + 10 * scale_y), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, speed_str)

        # 4. Gear indicator below
        gear_font = QFont(self.font_family)
        gear_font.setPixelSize(gear_font_size)
        gear_font.setBold(True)
        painter.setFont(gear_font)
        painter.setPen(QPen(QColor(255, 255, 255, 255)))
        painter.drawText(QRectF(0, 58.0 * scale_y, canvas_w, gear_font_size + 20 * scale_y), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, gear_str)
