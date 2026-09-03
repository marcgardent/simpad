"""
TC Gauge Widget — Far-right vertical Traction Control intervention intensity bar in compact Qt HUD canvas.
Displays TC power cuts / wheelspin percentage in Cyan (#00dcff / QColor(0, 220, 255)).
"""

from typing import Dict, Any
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QFont
from src.gui.overlay.base_widget import BaseQtHudWidget, lerp
from src.telemetry.sensors import VehicleSensors


class QtTcGaugeWidget(BaseQtHudWidget):
    """
    TC Gauge (Far Right of HUD, to the right of Throttle).
    Displays TC cut intensity / wheelspin in Cyan (#00dcff / QColor(0, 220, 255)).
    """

    def __init__(self):
        self.display_tc: float = 0.0

    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        if "tc" in extra_data:
            raw_tc = float(extra_data["tc"])
        else:
            raw_tc = max(sensors.ecu_tc_active, sensors.spin_intensity) * 100.0

        # LERP smoothing (0.65 for instant 120 Hz response)
        self.display_tc = lerp(self.display_tc, raw_tc, 0.65)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        gauge_width = 15.0 * scale_x
        gauge_height = 245.0 * scale_y
        tc_x = center_x + (250.0 * scale_x)
        gauge_y = 15.0 * scale_y

        # Background (Semi-transparent glass track)
        painter.setBrush(QBrush(QColor(17, 24, 39, 120)))
        painter.setPen(QPen(QColor(30, 41, 59, 200), 1))
        painter.drawRect(QRectF(tc_x, gauge_y, gauge_width, gauge_height))

        # Fill: Cyan (#00dcff / QColor(0, 220, 255)) on TC regulation
        fill_height = (max(0.0, min(100.0, self.display_tc)) / 100.0) * gauge_height
        if fill_height > 0.5:
            fill_y_min = gauge_y + gauge_height - fill_height
            painter.setBrush(QBrush(QColor(0, 220, 255, 255)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(QRectF(tc_x, fill_y_min, gauge_width, fill_height))

        # Level Indicator: TC level from cockpit setting (e.g. "3")
        if sensors.ecu_tc_level > 0:
            painter.setPen(QColor(0, 220, 255, 220))
            painter.setFont(QFont("sans-serif", max(7, int(8 * scale_y)), QFont.Weight.Bold))
            painter.drawText(
                QRectF(tc_x - 5, gauge_y + gauge_height + (2.0 * scale_y), gauge_width + 10, 16.0 * scale_y),
                int(Qt.AlignmentFlag.AlignCenter),
                str(sensors.ecu_tc_level),
            )
