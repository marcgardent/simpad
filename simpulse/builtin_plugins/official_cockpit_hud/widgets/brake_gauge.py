"""
Brake Gauge Widget — Left vertical brake pedal intensity bar in compact Qt canvas.
Displays pure driver braking percentage in Red (#ef4444 / QColor(239, 68, 68)).
"""

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QFont, QPainterPath, QLinearGradient
from .base_widget import BaseQtHudWidget, CockpitWidgetContext, lerp


class QtBrakeGaugeWidget(BaseQtHudWidget):
    """
    Pure Brake Gauge (Center-Left of compact HUD).
    Displays actual brake pedal travel with high-impact racing gradient and calibration ticks.
    """

    def __init__(self):
        self.display_brake: float = 0.0

    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        context: CockpitWidgetContext,
    ) -> None:
        raw_brake = context.sensors.unfiltered_brake * 100.0

        # Instant direct response (no LERP smoothing lag)
        self.display_brake = raw_brake

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        gauge_width = 28.0 * scale_x
        gauge_height = 245.0 * scale_y
        brake_x = center_x - (250.0 * scale_x)
        gauge_y = 15.0 * scale_y
        radius = 4.0 * min(scale_x, scale_y)

        track_rect = QRectF(brake_x, gauge_y, gauge_width, gauge_height)

        # 1. Background (Frosted dark track with subtle gradient)
        track_grad = QLinearGradient(brake_x, gauge_y, brake_x, gauge_y + gauge_height)
        track_grad.setColorAt(0.0, QColor(15, 23, 42, 210))
        track_grad.setColorAt(1.0, QColor(10, 15, 26, 230))
        painter.setBrush(QBrush(track_grad))
        painter.setPen(QPen(QColor(51, 65, 85, 200), 1.0))
        painter.drawRoundedRect(track_rect, radius, radius)

        # 2. Precision Calibration Ticks (25%, 50%, 75%)
        painter.setPen(QPen(QColor(255, 255, 255, 35), 1.0))
        for fraction in (0.25, 0.50, 0.75):
            tick_y = gauge_y + gauge_height * (1.0 - fraction)
            painter.drawLine(
                QPointF(brake_x + (3.0 * scale_x), tick_y),
                QPointF(brake_x + gauge_width - (3.0 * scale_x), tick_y)
            )

        # 3. Dynamic Fill: Multi-stage Racing Crimson -> Fire Red -> Peak Coral
        fill_height = (max(0.0, min(100.0, self.display_brake)) / 100.0) * gauge_height
        if fill_height > 0.5:
            fill_y_min = gauge_y + gauge_height - fill_height
            fill_rect = QRectF(brake_x, fill_y_min, gauge_width, fill_height)

            grad = QLinearGradient(brake_x, gauge_y + gauge_height, brake_x, gauge_y)
            grad.setColorAt(0.0, QColor(185, 28, 28, 250))   # Crimson
            grad.setColorAt(0.6, QColor(239, 68, 68, 255))   # Pure Red
            grad.setColorAt(1.0, QColor(254, 202, 202, 255)) # Peak highlight

            painter.save()
            path = QPainterPath()
            path.addRoundedRect(track_rect, radius, radius)
            painter.setClipPath(path)
            painter.fillRect(fill_rect, QBrush(grad))

            # Leading edge bright cap line (2px)
            painter.setPen(QPen(QColor(254, 226, 226, 240), 2.0))
            painter.drawLine(
                QPointF(brake_x, fill_y_min),
                QPointF(brake_x + gauge_width, fill_y_min)
            )
            painter.restore()

        # 4. Critical Braking Glow Border (> 85%)
        if self.display_brake > 85.0:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(239, 68, 68, 220), 1.5))
            painter.drawRoundedRect(track_rect, radius, radius)

        # 5. Label: "BRK" below track
        label_y = gauge_y + gauge_height + (3.0 * scale_y)
        label_h = 16.0 * scale_y
        painter.setFont(QFont("sans-serif", max(7, int(8.5 * scale_y)), QFont.Weight.Bold))
        col = QColor(239, 68, 68, 255) if self.display_brake > 1.0 else QColor(148, 163, 184, 180)
        painter.setPen(col)
        painter.drawText(
            QRectF(brake_x - 4.0 * scale_x, label_y, gauge_width + 8.0 * scale_x, label_h),
            int(Qt.AlignmentFlag.AlignCenter),
            "BRK",
        )
