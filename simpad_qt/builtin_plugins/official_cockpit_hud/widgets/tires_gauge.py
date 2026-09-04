"""
Qt Tires Gauge Widget — Physical 4-Tire Life & Slip Representation for Compact Qt Overlay.
Displays:
- Left Tires (FL on top, RL on bottom) placed immediately to the right of the Brake gauge.
- Right Tires (FR on top, RR on bottom) placed immediately to the left of the Throttle gauge.

Physical Color Coding:
- Wheel Lockup / Over-Braking: Purple (#c084fc pastel -> #581c87 deep dark)
- Wheel Slip / Spin / Lateral Scrub: Cyan (#a5f3fc pastel -> #0e7490 deep dark)
- Neutral Grip: Dark stealth tire tread (#131822)
"""

from typing import Dict, Any, Tuple
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QFont, QPolygonF
from .base_widget import BaseQtHudWidget, lerp
from simpad_qt.core.telemetry import VehicleSensors


def get_qt_tire_colors(lock_val: float, slip_val: float) -> Tuple[QColor, QColor, str, float]:
    """
    Calculates background color, border color, event type, and intensity
    of the tire for Qt based on tire/road contact physics.
    """
    if lock_val > 0.02:
        # Wheel lockup / Critical braking -> PURPLE gradient (soft pastel to dark deep)
        t = min(1.0, max(0.0, lock_val))
        r = int(216 - t * (216 - 88))
        g = int(180 - t * (180 - 28))
        b = int(254 - t * (254 - 135))
        fill_col = QColor(r, g, b, 240)
        border_col = QColor(min(255, int(r * 1.2 + 30)), min(255, int(g * 1.2 + 30)), min(255, int(b * 1.2 + 30)), 255)
        return fill_col, border_col, "LOCK", t

    elif slip_val > 0.02:
        # Wheel slip / Spin / Scrub -> CYAN gradient (soft pastel to dark deep)
        t = min(1.0, max(0.0, slip_val))
        r = int(165 - t * (165 - 14))
        g = int(243 - t * (243 - 116))
        b = int(252 - t * (252 - 144))
        fill_col = QColor(r, g, b, 240)
        border_col = QColor(min(255, int(r * 1.2 + 30)), min(255, int(g * 1.2 + 30)), min(255, int(b * 1.2 + 30)), 255)
        return fill_col, border_col, "SLIP", t

    else:
        # Neutral tire at rest (Dark stylized rubber)
        return QColor(19, 24, 34, 180), QColor(46, 56, 77, 200), "NONE", 0.0


class QtTiresGaugeWidget(BaseQtHudWidget):
    """
    Complete Tri-Axial Physical Representation of 4 Tires in Qt Overlay:
    - TOP Section (CCCC): Vertical Cyan Gauge (Over-Acceleration / Traction ⬆️)
    - MIDDLE Section (LLRR): Horizontal Yellow Gauge (Lateral Scrub Left/Right ⬅️ ➡️ / Understeer & Oversteer)
    - BOTTOM Section (BBBB): Vertical Purple Gauge (Over-Braking / Wheel Lockup ⬇️)
    """

    def __init__(self):
        self.disp_fl_lock = 0.0
        self.disp_fr_lock = 0.0
        self.disp_rl_lock = 0.0
        self.disp_rr_lock = 0.0

        self.disp_fl_spin = 0.0
        self.disp_fr_spin = 0.0
        self.disp_rl_spin = 0.0
        self.disp_rr_spin = 0.0

        self.disp_fl_lat = 0.0
        self.disp_fr_lat = 0.0
        self.disp_rl_lat = 0.0
        self.disp_rr_lat = 0.0

        self.disp_fl_lat_s = 0.0
        self.disp_fr_lat_s = 0.0
        self.disp_rl_lat_s = 0.0
        self.disp_rr_lat_s = 0.0

    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        alpha = 0.65
        # 1. Longitudinal Lock (Over-Braking)
        self.disp_fl_lock = lerp(self.disp_fl_lock, sensors.front_left_lock, alpha)
        self.disp_fr_lock = lerp(self.disp_fr_lock, sensors.front_right_lock, alpha)
        self.disp_rl_lock = lerp(self.disp_rl_lock, sensors.rear_left_lock, alpha)
        self.disp_rr_lock = lerp(self.disp_rr_lock, sensors.rear_right_lock, alpha)

        # 2. Longitudinal Spin (Over-Acceleration)
        self.disp_fl_spin = lerp(self.disp_fl_spin, sensors.front_left_spin, alpha)
        self.disp_fr_spin = lerp(self.disp_fr_spin, sensors.front_right_spin, alpha)
        self.disp_rl_spin = lerp(self.disp_rl_spin, sensors.rear_left_spin, alpha)
        self.disp_rr_spin = lerp(self.disp_rr_spin, sensors.rear_right_spin, alpha)

        # 3. Lateral Scrub (Magnitude)
        self.disp_fl_lat = lerp(self.disp_fl_lat, sensors.front_left_lat_slip, alpha)
        self.disp_fr_lat = lerp(self.disp_fr_lat, sensors.front_right_lat_slip, alpha)
        self.disp_rl_lat = lerp(self.disp_rl_lat, sensors.rear_left_lat_slip, alpha)
        self.disp_rr_lat = lerp(self.disp_rr_lat, sensors.rear_right_lat_slip, alpha)

        # 4. Lateral Scrub Signed (Left -1.0 to Right +1.0)
        self.disp_fl_lat_s = lerp(self.disp_fl_lat_s, sensors.front_left_lat_signed, alpha)
        self.disp_fr_lat_s = lerp(self.disp_fr_lat_s, sensors.front_right_lat_signed, alpha)
        self.disp_rl_lat_s = lerp(self.disp_rl_lat_s, sensors.rear_left_lat_signed, alpha)
        self.disp_rr_lat_s = lerp(self.disp_rr_lat_s, sensors.rear_right_lat_signed, alpha)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        # Realistic racing tire aspect ratio (~ 1:1.85)
        tire_w = 40.0 * scale_x
        tire_h = 74.0 * scale_y

        # Alignment:
        # - Front Tires (FL, FR): Aligned to TOP (y = 15px)
        front_y = 15.0 * scale_y

        # - Rear Tires (RL, RR): Aligned to BOTTOM (ends at 236px, with 14px margin above aero bar at 250px)
        rear_bot_y = 236.0 * scale_y
        rear_y = rear_bot_y - tire_h  # 162.0 * scale_y

        # Horizontal positions (alongside brake and throttle gauges)
        left_tires_x = center_x - (215.0 * scale_x)
        right_tires_x = center_x + (175.0 * scale_x)

        # List of 4 tires (x, y, label, lock, spin, lat_mag, lat_signed)
        tires_info = [
            (left_tires_x, front_y, "FL", self.disp_fl_lock, self.disp_fl_spin, self.disp_fl_lat, self.disp_fl_lat_s),
            (left_tires_x, rear_y, "RL", self.disp_rl_lock, self.disp_rl_spin, self.disp_rl_lat, self.disp_rl_lat_s),
            (right_tires_x, front_y, "FR", self.disp_fr_lock, self.disp_fr_spin, self.disp_fr_lat, self.disp_fr_lat_s),
            (right_tires_x, rear_y, "RR", self.disp_rr_lock, self.disp_rr_spin, self.disp_rr_lat, self.disp_rr_lat_s),
        ]

        # Internal proportional layout: ccccccc (3) / LLL|RRR (2) / bbbbbbb (3)
        header_h = 12.0 * scale_y
        gap_y = 2.0 * scale_y
        vert_h = 21.0 * scale_y   # Vertical gauges CCCC and BBBB
        lat_h = 14.0 * scale_y    # Middle horizontal gauge LLL|RRR

        font_label = QFont("Segoe UI", max(7, int(8.0 * scale_y)), QFont.Weight.Bold)

        for x, y, label, lock_val, spin_val, lat_val, lat_s in tires_info:
            # 1. Outer tire box
            rect = QRectF(x, y, tire_w, tire_h)
            painter.setBrush(QBrush(QColor(19, 24, 34, 220)))
            painter.setPen(QPen(QColor(46, 56, 77, 240), 1.0))
            painter.drawRoundedRect(rect, 4.0 * scale_x, 4.0 * scale_y)

            # Wheel label header
            painter.setFont(font_label)
            painter.setPen(QPen(QColor(255, 255, 255, 220)))
            painter.drawText(QRectF(x + 3.0 * scale_x, y + 2.0 * scale_y, tire_w - 6.0 * scale_x, 11.0 * scale_y), Qt.AlignmentFlag.AlignLeft, label)

            # ── SECTION 1 (CCCC): Vertical Cyan Gauge (Over-Acceleration ⬆️) ──
            c_top = y + header_h + gap_y
            c_rect = QRectF(x + 2.0 * scale_x, c_top, tire_w - 4.0 * scale_x, vert_h)
            painter.setBrush(QBrush(QColor(15, 20, 30, 180)))
            painter.setPen(QPen(QColor(40, 50, 70, 150), 0.8))
            painter.drawRoundedRect(c_rect, 2.0 * scale_x, 2.0 * scale_y)

            if spin_val > 0.02:
                c_fill = max(2.0 * scale_y, vert_h * min(1.0, spin_val))
                c_fill_y = c_top + vert_h - c_fill
                c_fill_rect = QRectF(x + 2.5 * scale_x, c_fill_y, tire_w - 5.0 * scale_x, c_fill)
                painter.setBrush(QBrush(QColor(0, 220, 255, 220)))
                painter.setPen(QPen(QColor(56, 189, 248, 255), 0.8))
                painter.drawRoundedRect(c_fill_rect, 1.5 * scale_x, 1.5 * scale_y)

                painter.setPen(QPen(QColor(255, 255, 255, 240), 1.0))
                painter.drawLine(QPointF(x + 3.0 * scale_x, c_fill_y), QPointF(x + tire_w - 3.0 * scale_x, c_fill_y))

            # ── SECTION 2 (LLRR): Horizontal Yellow Gauge with Arrow (⬅️ ➡️) ──
            l_top = c_top + vert_h + gap_y
            l_rect = QRectF(x + 2.0 * scale_x, l_top, tire_w - 4.0 * scale_x, lat_h)
            painter.setBrush(QBrush(QColor(15, 20, 30, 200)))
            painter.setPen(QPen(QColor(50, 60, 80, 180), 0.8))
            painter.drawRoundedRect(l_rect, 2.0 * scale_x, 2.0 * scale_y)

            mid_x = x + tire_w / 2.0
            half_w = (tire_w - 7.0 * scale_x) / 2.0

            # Sharp central separator between Left and Right
            painter.setPen(QPen(QColor(148, 163, 184, 255), 1.5))
            painter.drawLine(QPointF(mid_x, l_top + 1.0 * scale_y), QPointF(mid_x, l_top + lat_h - 1.0 * scale_y))

            # Directional arrow based on scrub direction
            if abs(lat_s) > 0.02:
                bar_w = max(4.0 * scale_x, half_w * min(1.0, abs(lat_s)))
                head_w = min(bar_w, 5.0 * scale_x)

                if lat_s < 0:  # Slide to the Left (◄ Arrow pointing left)
                    tip_x = mid_x - 1.0 * scale_x - bar_w
                    base_x = tip_x + head_w

                    # Rectangular body
                    if bar_w > head_w:
                        body_rect = QRectF(base_x, l_top + 3.0 * scale_y, mid_x - 1.0 * scale_x - base_x, lat_h - 6.0 * scale_y)
                        painter.setBrush(QBrush(QColor(250, 204, 21, 220)))
                        painter.setPen(QPen(QColor(234, 179, 8, 255), 0.8))
                        painter.drawRect(body_rect)

                    # Triangular head
                    triangle = QPolygonF([
                        QPointF(tip_x, l_top + lat_h / 2.0),
                        QPointF(base_x, l_top + 1.5 * scale_y),
                        QPointF(base_x, l_top + lat_h - 1.5 * scale_y),
                    ])
                    painter.setBrush(QBrush(QColor(250, 204, 21, 240)))
                    painter.setPen(QPen(QColor(255, 255, 255, 240), 1.0))
                    painter.drawPolygon(triangle)

                else:  # Slide to the Right (► Arrow pointing right)
                    tip_x = mid_x + 1.0 * scale_x + bar_w
                    base_x = tip_x - head_w

                    # Rectangular body
                    if bar_w > head_w:
                        body_rect = QRectF(mid_x + 1.0 * scale_x, l_top + 3.0 * scale_y, base_x - (mid_x + 1.0 * scale_x), lat_h - 6.0 * scale_y)
                        painter.setBrush(QBrush(QColor(250, 204, 21, 220)))
                        painter.setPen(QPen(QColor(234, 179, 8, 255), 0.8))
                        painter.drawRect(body_rect)

                    # Triangular head
                    triangle = QPolygonF([
                        QPointF(tip_x, l_top + lat_h / 2.0),
                        QPointF(base_x, l_top + 1.5 * scale_y),
                        QPointF(base_x, l_top + lat_h - 1.5 * scale_y),
                    ])
                    painter.setBrush(QBrush(QColor(250, 204, 21, 240)))
                    painter.setPen(QPen(QColor(255, 255, 255, 240), 1.0))
                    painter.drawPolygon(triangle)

            elif lat_val > 0.02:  # Fallback if magnitude is unsigned
                bar_w = max(3.0 * scale_x, half_w * min(1.0, lat_val))
                lat_bar = QRectF(mid_x - bar_w / 2.0, l_top + 2.0 * scale_y, bar_w, lat_h - 4.0 * scale_y)
                painter.setBrush(QBrush(QColor(250, 204, 21, 220)))
                painter.setPen(QPen(QColor(234, 179, 8, 255), 0.8))
                painter.drawRoundedRect(lat_bar, 1.5 * scale_x, 1.5 * scale_y)

            # ── SECTION 3 (BBBB): Vertical Purple Gauge (Over-Braking ⬇️) ──
            b_top = l_top + lat_h + gap_y
            b_rect = QRectF(x + 2.0 * scale_x, b_top, tire_w - 4.0 * scale_x, vert_h)
            painter.setBrush(QBrush(QColor(15, 20, 30, 180)))
            painter.setPen(QPen(QColor(40, 50, 70, 150), 0.8))
            painter.drawRoundedRect(b_rect, 2.0 * scale_x, 2.0 * scale_y)

            if lock_val > 0.02:
                b_fill = max(2.0 * scale_y, vert_h * min(1.0, lock_val))
                b_fill_bot = b_top + b_fill
                b_fill_rect = QRectF(x + 2.5 * scale_x, b_top, tire_w - 5.0 * scale_x, b_fill)
                painter.setBrush(QBrush(QColor(168, 85, 247, 220)))
                painter.setPen(QPen(QColor(192, 132, 252, 255), 0.8))
                painter.drawRoundedRect(b_fill_rect, 1.5 * scale_x, 1.5 * scale_y)

                painter.setPen(QPen(QColor(255, 255, 255, 240), 1.0))
                painter.drawLine(QPointF(x + 3.0 * scale_x, b_fill_bot), QPointF(x + tire_w - 3.0 * scale_x, b_fill_bot))
