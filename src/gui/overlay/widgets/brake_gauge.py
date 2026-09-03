"""
Brake Gauge Widget — Left vertical brake pedal intensity bar in compact Qt canvas.
Displays pure driver braking percentage in Red (#ef4444 / QColor(239, 68, 68)).
"""

from typing import Dict, Any
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QBrush, QPen
from src.gui.overlay.base_widget import BaseQtHudWidget, lerp
from src.telemetry.sensors import VehicleSensors


class QtBrakeGaugeWidget(BaseQtHudWidget):
    """
    Pure Brake Gauge (Center-Left of compact HUD).
    Displays actual brake pedal travel in Red (#ef4444).
    """

    def __init__(self):
        self.display_brake: float = 0.0

    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        raw_brake = float(extra_data.get("brake", sensors.unfiltered_brake * 100.0))

        # LERP smoothing (0.65 for instant 120 Hz response)
        self.display_brake = lerp(self.display_brake, raw_brake, 0.65)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        gauge_width = 30.0 * scale_x
        gauge_height = 245.0 * scale_y
        brake_x = center_x - (250.0 * scale_x)
        gauge_y = 15.0 * scale_y

        # Background (Semi-transparent glass track)
        painter.setBrush(QBrush(QColor(17, 24, 39, 120)))
        painter.setPen(QPen(QColor(30, 41, 59, 200), 1))
        painter.drawRect(QRectF(brake_x, gauge_y, gauge_width, gauge_height))

        # Fill: Pure Red (#ef4444)
        fill_height = (max(0.0, min(100.0, self.display_brake)) / 100.0) * gauge_height
        if fill_height > 0.5:
            fill_y_min = gauge_y + gauge_height - fill_height
            painter.setBrush(QBrush(QColor(239, 68, 68, 255)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(QRectF(brake_x, fill_y_min, gauge_width, fill_height))
