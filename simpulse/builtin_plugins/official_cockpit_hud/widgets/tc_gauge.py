"""
TC Gauge Widget — Far-right vertical Traction Control intervention intensity bar in compact Qt HUD canvas.
Displays TC power cuts / wheelspin percentage in Cyan (#00dcff / QColor(0, 220, 255)).
"""

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QFont, QPainterPath, QLinearGradient
from .base_widget import BaseQtHudWidget, CockpitWidgetContext


class QtTcGaugeWidget(BaseQtHudWidget):
    """
    TC Gauge (Far Right of HUD, to the right of Throttle).
    Displays TC cut intensity / wheelspin with high-impact electric cyan gradient and calibration ticks.
    """

    def __init__(self):
        self.display_tc: float = 0.0

    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        context: CockpitWidgetContext,
    ) -> None:
        sensors = context.sensors
        raw_tc = max(sensors.ecu_tc_active, sensors.spin_intensity) * 100.0

        # Instant direct response (no LERP smoothing lag)
        self.display_tc = raw_tc

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        gauge_width = 14.0 * scale_x
        gauge_height = 245.0 * scale_y
        tc_x = center_x + (254.0 * scale_x)
        gauge_y = 15.0 * scale_y
        radius = 4.0 * min(scale_x, scale_y)

        track_rect = QRectF(tc_x, gauge_y, gauge_width, gauge_height)

        # 1. Background (Frosted dark track with subtle gradient)
        track_grad = QLinearGradient(tc_x, gauge_y, tc_x, gauge_y + gauge_height)
        track_grad.setColorAt(0.0, QColor(15, 23, 42, 210))
        track_grad.setColorAt(1.0, QColor(10, 15, 26, 230))
        painter.setBrush(QBrush(track_grad))
        painter.setPen(QPen(QColor(51, 65, 85, 200), 1.0))
        painter.drawRoundedRect(track_rect, radius, radius)

        # 2. Precision Calibration Ticks (25%, 50%, 75%)
        painter.setPen(QPen(QColor(255, 255, 255, 30), 1.0))
        for fraction in (0.25, 0.50, 0.75):
            tick_y = gauge_y + gauge_height * (1.0 - fraction)
            painter.drawLine(
                QPointF(tc_x + (2.0 * scale_x), tick_y),
                QPointF(tc_x + gauge_width - (2.0 * scale_x), tick_y)
            )

        # 3. Dynamic Fill: Electric Cyan Gradient
        fill_height = (max(0.0, min(100.0, self.display_tc)) / 100.0) * gauge_height
        if fill_height > 0.5:
            fill_y_min = gauge_y + gauge_height - fill_height
            fill_rect = QRectF(tc_x, fill_y_min, gauge_width, fill_height)

            grad = QLinearGradient(tc_x, gauge_y + gauge_height, tc_x, gauge_y)
            grad.setColorAt(0.0, QColor(8, 145, 178, 250))   # Deep Cyan
            grad.setColorAt(0.6, QColor(6, 182, 212, 255))   # Electric Cyan
            grad.setColorAt(1.0, QColor(186, 230, 253, 255)) # Electric Ice Peak Glow

            painter.save()
            path = QPainterPath()
            path.addRoundedRect(track_rect, radius, radius)
            painter.setClipPath(path)
            painter.fillRect(fill_rect, QBrush(grad))

            # Leading edge bright cyan-white cap line (2px)
            painter.setPen(QPen(QColor(224, 242, 254, 240), 2.0))
            painter.drawLine(
                QPointF(tc_x, fill_y_min),
                QPointF(tc_x + gauge_width, fill_y_min)
            )
            painter.restore()

        # 4. Active TC Regulation Pulsing Glow
        if self.display_tc > 5.0:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(0, 220, 255, 220), 1.5))
            painter.drawRoundedRect(track_rect, radius, radius)

        # 5. Level Pill Badge or TC Label below track
        label_y = gauge_y + gauge_height + (3.0 * scale_y)
        label_h = 16.0 * scale_y

        if sensors.ecu.tc.level > 0:
            badge_rect = QRectF(tc_x - (1.0 * scale_x), label_y, gauge_width + (2.0 * scale_x), label_h)
            painter.setBrush(QBrush(QColor(10, 30, 45, 220)))
            painter.setPen(QPen(QColor(0, 220, 255, 220), 1.0))
            painter.drawRoundedRect(badge_rect, 3.0, 3.0)
            painter.setFont(QFont("sans-serif", max(7, int(8.5 * scale_y)), QFont.Weight.Bold))
            painter.setPen(QColor(165, 243, 252, 255))
            painter.drawText(badge_rect, int(Qt.AlignmentFlag.AlignCenter), str(sensors.ecu.tc.level))
        else:
            painter.setFont(QFont("sans-serif", max(7, int(7.5 * scale_y)), QFont.Weight.Bold))
            col = QColor(0, 220, 255, 255) if self.display_tc > 1.0 else QColor(148, 163, 184, 180)
            painter.setPen(col)
            painter.drawText(
                QRectF(tc_x - (4.0 * scale_x), label_y, gauge_width + (8.0 * scale_x), label_h),
                int(Qt.AlignmentFlag.AlignCenter),
                "TC",
            )
