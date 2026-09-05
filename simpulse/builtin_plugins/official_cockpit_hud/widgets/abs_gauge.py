"""
ABS Gauge Widget — Far-left vertical ABS intervention intensity bar in compact Qt HUD canvas.
Displays ABS regulation / wheel lockup percentage in Purple (#a855f7 / QColor(168, 85, 247)).
"""

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QFont
from .base_widget import BaseQtHudWidget, CockpitWidgetContext, lerp


class QtAbsGaugeWidget(BaseQtHudWidget):
    """
    ABS Gauge (Far Left of HUD, to the left of Brake gauge).
    Displays ABS regulation / wheel lockup intensity in Purple (#a855f7).
    """

    def __init__(self):
        self.display_abs: float = 0.0

    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        context: CockpitWidgetContext,
    ) -> None:
        sensors = context.sensors
        raw_abs = sensors.ecu_abs_active * 100.0

        # LERP smoothing (0.65 for instant 120 Hz response)
        self.display_abs = lerp(self.display_abs, raw_abs, 0.65)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        gauge_width = 15.0 * scale_x
        gauge_height = 245.0 * scale_y
        abs_x = center_x - (265.0 * scale_x)
        gauge_y = 15.0 * scale_y

        # Background (Semi-transparent glass track)
        painter.setBrush(QBrush(QColor(17, 24, 39, 120)))
        painter.setPen(QPen(QColor(30, 41, 59, 200), 1))
        painter.drawRect(QRectF(abs_x, gauge_y, gauge_width, gauge_height))

        # Fill: Purple (#a855f7) on ABS regulation
        fill_height = (max(0.0, min(100.0, self.display_abs)) / 100.0) * gauge_height
        if fill_height > 0.5:
            fill_y_min = gauge_y + gauge_height - fill_height
            painter.setBrush(QBrush(QColor(168, 85, 247, 255)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(QRectF(abs_x, fill_y_min, gauge_width, fill_height))

        # Level Indicator: ABS level from cockpit setting (e.g. "5")
        if sensors.ecu_abs_level > 0:
            painter.setPen(QColor(168, 85, 247, 220))
            painter.setFont(QFont("sans-serif", max(7, int(8 * scale_y)), QFont.Weight.Bold))
            painter.drawText(
                QRectF(abs_x - 5, gauge_y + gauge_height + (2.0 * scale_y), gauge_width + 10, 16.0 * scale_y),
                int(Qt.AlignmentFlag.AlignCenter),
                str(sensors.ecu_abs_level),
            )
