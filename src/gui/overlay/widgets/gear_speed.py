"""
Gear Speed Widget — Uses digits-only in WHITE for speed, positioned at the top of the canvas.
1. Speed digits in WHITE at the top.
2. Gear display directly below the speed.
"""

from typing import Dict, Any
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QBrush
from src.gui.overlay.base_widget import BaseQtHudWidget, lerp
from src.telemetry.sensors import VehicleSensors


class QtGearSpeedWidget(BaseQtHudWidget):
    """
    Vitesse (Chiffres seuls en BLANC tout en haut) & Rapport de Boîte (Gear en dessous).
    """

    def __init__(self, font_family: str = "Anta"):
        self.display_speed: float = 0.0
        self.font_family = font_family

    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        # 1. Rapport de vitesse (Gear)
        if "gear" in extra_data:
            gear_str = str(extra_data["gear"])
        else:
            g = sensors.gear
            gear_str = "R" if g == -1 else ("N" if g == 0 else str(g))

        # 2. Vitesse en km/h avec lissage LERP réactif (0.70)
        raw_speed = extra_data.get("speed", sensors.vehicle_speed * 3.6)
        self.display_speed = lerp(self.display_speed, raw_speed, 0.70)
        speed_int = max(0, int(round(self.display_speed)))
        speed_str = str(speed_int)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        speed_font_size = max(16, int(round(52.0 * scale_y)))
        gear_font_size = max(32, int(round(110.0 * scale_y)))

        # 3. Vitesse tout en haut
        speed_y = 12.0 * scale_y

        # Rectangle noir sous la vitesse quand elle passe sous 60 km/h
        if self.display_speed < 60.0:
            box_w = max(80.0 * scale_x, len(speed_str) * (speed_font_size * 0.60) + 16.0 * scale_x)
            box_h = speed_font_size + 6.0 * scale_y
            painter.setBrush(QBrush(QColor(0, 0, 0, 255)))
            painter.setPen(QPen(QColor(30, 41, 59, 255), 1))
            painter.drawRect(QRectF(center_x - (box_w / 2.0), speed_y - 2.0 * scale_y, box_w, box_h))

        # Texte Vitesse en blanc
        speed_font = QFont(self.font_family)
        speed_font.setPixelSize(speed_font_size)
        speed_font.setBold(True)
        painter.setFont(speed_font)
        painter.setPen(QPen(QColor(255, 255, 255, 255)))
        painter.drawText(QRectF(0, speed_y, canvas_w, speed_font_size + 10 * scale_y), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, speed_str)

        # 4. Rapport de boîte (Gear) en dessous
        gear_font = QFont(self.font_family)
        gear_font.setPixelSize(gear_font_size)
        gear_font.setBold(True)
        painter.setFont(gear_font)
        painter.setPen(QPen(QColor(255, 255, 255, 255)))
        painter.drawText(QRectF(0, 58.0 * scale_y, canvas_w, gear_font_size + 20 * scale_y), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, gear_str)
