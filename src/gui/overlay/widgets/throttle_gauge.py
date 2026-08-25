"""
Throttle Gauge Widget — Right vertical acceleration intensity bar in compact canvas.
Displays acceleration percentage and changes color to Yellow (#eab308) on wheelspin (patinage).
"""

from typing import Dict, Any
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QBrush, QPen
from src.gui.overlay.base_widget import BaseQtHudWidget, lerp
from src.telemetry.sensors import VehicleSensors


class QtThrottleGaugeWidget(BaseQtHudWidget):
    """
    Jauge d'Accélérateur (Côté Droit du HUD compact).
    Affiche l'intensité de l'accélération et change de couleur en cas de patinage (wheelspin).
    """

    def __init__(self):
        self.display_throttle: float = 0.0

    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        if "throttle" in extra_data:
            raw_throttle = float(extra_data["throttle"])
        elif sensors.unfiltered_throttle > 0.0:
            raw_throttle = sensors.unfiltered_throttle * 100.0
        else:
            raw_throttle = sensors.spin_intensity * 100.0

        is_spinning = extra_data.get("wheelspin", False) or (sensors.spin_intensity > 0.05)

        # LERP smoothing
        self.display_throttle = lerp(self.display_throttle, raw_throttle, 0.15)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 300.0
        center_x = canvas_w / 2.0

        gauge_width = 32.0 * scale_x
        gauge_height = 245.0 * scale_y
        throttle_x = center_x + (260.0 * scale_x) - gauge_width
        gauge_y = 15.0 * scale_y

        # Background (Semi-transparent glass track)
        painter.setBrush(QBrush(QColor(17, 24, 39, 120)))
        painter.setPen(QPen(QColor(30, 41, 59, 200), 1))
        painter.drawRect(QRectF(throttle_x, gauge_y, gauge_width, gauge_height))

        # Fill: Green (#22c55e) normally, turns Yellow (#eab308) on wheelspin
        fill_height = (max(0.0, min(100.0, self.display_throttle)) / 100.0) * gauge_height
        if fill_height > 0.5:
            fill_color = QColor(234, 179, 8, 255) if is_spinning else QColor(34, 197, 94, 255)
            fill_y_min = gauge_y + gauge_height - fill_height
            painter.setBrush(QBrush(fill_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(QRectF(throttle_x, fill_y_min, gauge_width, fill_height))
