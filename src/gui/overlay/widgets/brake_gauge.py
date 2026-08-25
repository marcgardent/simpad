"""
Brake Gauge Widget — Left vertical brake intensity bar in compact canvas.
Displays braking percentage and changes color to Purple (#a855f7) on wheel lockup (locking).
"""

from typing import Dict, Any
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QBrush, QPen
from src.gui.overlay.base_widget import BaseQtHudWidget, lerp
from src.telemetry.sensors import VehicleSensors


class QtBrakeGaugeWidget(BaseQtHudWidget):
    """
    Jauge de Frein (Côté Gauche du HUD compact).
    Affiche l'intensité du freinage et change de couleur en cas de blocage / surfreinage (locking).
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
        if "brake" in extra_data:
            raw_brake = float(extra_data["brake"])
        elif sensors.unfiltered_brake > 0.0:
            raw_brake = sensors.unfiltered_brake * 100.0
        else:
            raw_brake = sensors.lock_intensity * 100.0

        is_locking = extra_data.get("overbrake", False) or (sensors.lock_intensity > 0.05)

        # LERP smoothing (0.65 pour réactivité instantanée 120 Hz)
        self.display_brake = lerp(self.display_brake, raw_brake, 0.65)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        gauge_width = 32.0 * scale_x
        gauge_height = 245.0 * scale_y
        brake_x = center_x - (260.0 * scale_x)
        gauge_y = 15.0 * scale_y

        # Background (Semi-transparent glass track)
        painter.setBrush(QBrush(QColor(17, 24, 39, 120)))
        painter.setPen(QPen(QColor(30, 41, 59, 200), 1))
        painter.drawRect(QRectF(brake_x, gauge_y, gauge_width, gauge_height))

        # Fill: Red (#ef4444) normally, turns Purple (#a855f7) on locking
        fill_height = (max(0.0, min(100.0, self.display_brake)) / 100.0) * gauge_height
        if fill_height > 0.5:
            fill_color = QColor(168, 85, 247, 255) if is_locking else QColor(239, 68, 68, 255)
            fill_y_min = gauge_y + gauge_height - fill_height
            painter.setBrush(QBrush(fill_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(QRectF(brake_x, fill_y_min, gauge_width, fill_height))
