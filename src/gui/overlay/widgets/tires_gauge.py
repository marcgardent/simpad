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
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QFont
from src.gui.overlay.base_widget import BaseQtHudWidget, lerp
from src.telemetry.sensors import VehicleSensors


def get_qt_tire_colors(lock_val: float, slip_val: float) -> Tuple[QColor, QColor, str, float]:
    """
    Calcule la couleur de fond, de bordure, le type d'événement et l'intensité
    du pneu pour Qt selon la physique de contact pneu/route.
    """
    if lock_val > 0.02:
        # Blocage / Freinage critique -> Dégradé VIOLET (Pastel doux vers Foncé profond)
        t = min(1.0, max(0.0, lock_val))
        r = int(216 - t * (216 - 88))
        g = int(180 - t * (180 - 28))
        b = int(254 - t * (254 - 135))
        fill_col = QColor(r, g, b, 240)
        border_col = QColor(min(255, int(r * 1.2 + 30)), min(255, int(g * 1.2 + 30)), min(255, int(b * 1.2 + 30)), 255)
        return fill_col, border_col, "LOCK", t

    elif slip_val > 0.02:
        # Glisse / Patinage / Dérive -> Dégradé CYAN (Pastel doux vers Foncé profond)
        t = min(1.0, max(0.0, slip_val))
        r = int(165 - t * (165 - 14))
        g = int(243 - t * (243 - 116))
        b = int(252 - t * (252 - 144))
        fill_col = QColor(r, g, b, 240)
        border_col = QColor(min(255, int(r * 1.2 + 30)), min(255, int(g * 1.2 + 30)), min(255, int(b * 1.2 + 30)), 255)
        return fill_col, border_col, "SLIP", t

    else:
        # Pneu neutre au repos (Gomme sombre stylisée)
        return QColor(19, 24, 34, 180), QColor(46, 56, 77, 200), "NONE", 0.0


class QtTiresGaugeWidget(BaseQtHudWidget):
    """
    Représentation Physique de la Vie des 4 Pneus sous Qt Overlay.
    - FL & RL disposés verticalement à droite du Frein.
    - FR & RR disposés verticalement à gauche de l'Accélérateur.
    """

    def __init__(self):
        self.disp_fl_lock = 0.0
        self.disp_fr_lock = 0.0
        self.disp_rl_lock = 0.0
        self.disp_rr_lock = 0.0

        self.disp_fl_slip = 0.0
        self.disp_fr_slip = 0.0
        self.disp_rl_slip = 0.0
        self.disp_rr_slip = 0.0

    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        # LERP smoothing (0.65 pour réactivité instantanée 120 Hz)
        alpha = 0.65
        self.disp_fl_lock = lerp(self.disp_fl_lock, sensors.front_left_lock, alpha)
        self.disp_fr_lock = lerp(self.disp_fr_lock, sensors.front_right_lock, alpha)
        self.disp_rl_lock = lerp(self.disp_rl_lock, sensors.rear_left_lock, alpha)
        self.disp_rr_lock = lerp(self.disp_rr_lock, sensors.rear_right_lock, alpha)

        fl_slip_raw = max(sensors.front_left_spin, sensors.front_left_lat_slip)
        fr_slip_raw = max(sensors.front_right_spin, sensors.front_right_lat_slip)
        rl_slip_raw = max(sensors.rear_left_spin, sensors.rear_left_lat_slip)
        rr_slip_raw = max(sensors.rear_right_spin, sensors.rear_right_lat_slip)

        self.disp_fl_slip = lerp(self.disp_fl_slip, fl_slip_raw, alpha)
        self.disp_fr_slip = lerp(self.disp_fr_slip, fr_slip_raw, alpha)
        self.disp_rl_slip = lerp(self.disp_rl_slip, rl_slip_raw, alpha)
        self.disp_rr_slip = lerp(self.disp_rr_slip, rr_slip_raw, alpha)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        gauge_y = 15.0 * scale_y
        gauge_h = 245.0 * scale_y

        tire_w = 24.0 * scale_x
        tire_gap = 9.0 * scale_y
        tire_h = (gauge_h - tire_gap) / 2.0

        # Positions horizontales :
        left_tires_x = center_x - (216.0 * scale_x)
        right_tires_x = center_x + (192.0 * scale_x)

        front_y = gauge_y
        rear_y = gauge_y + tire_h + tire_gap

        tires_info = [
            (left_tires_x, front_y, "FL", self.disp_fl_lock, self.disp_fl_slip),
            (left_tires_x, rear_y, "RL", self.disp_rl_lock, self.disp_rl_slip),
            (right_tires_x, front_y, "FR", self.disp_fr_lock, self.disp_fr_slip),
            (right_tires_x, rear_y, "RR", self.disp_rr_lock, self.disp_rr_slip),
        ]

        for x, y, label, lock_val, slip_val in tires_info:
            fill_col, border_col, mode, intensity = get_qt_tire_colors(lock_val, slip_val)

            # Corps du pneu (Rectangle aux coins arrondis)
            rect = QRectF(x, y, tire_w, tire_h)
            painter.setBrush(QBrush(fill_col))
            painter.setPen(QPen(border_col, 1.5 if intensity > 0.05 else 1.0))
            painter.drawRoundedRect(rect, 4.0 * scale_x, 4.0 * scale_y)

            # Rainure de bande de roulement centrale
            groove_x = x + tire_w / 2.0
            groove_col = QColor(border_col.red(), border_col.green(), border_col.blue(), 60 if intensity <= 0.02 else 120)
            painter.setPen(QPen(groove_col, 1.0))
            painter.drawLine(QPointF(groove_x, y + 4.0 * scale_y), QPointF(groove_x, y + tire_h - 4.0 * scale_y))

            # Label de la roue
            text_col = QColor(255, 255, 255, 220) if intensity > 0.05 else QColor(148, 163, 184, 160)
            font_size = max(7, int(8.0 * scale_y))
            font = QFont("Segoe UI", font_size, QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(QPen(text_col))
            painter.drawText(QRectF(x + 2.0 * scale_x, y + 2.0 * scale_y, tire_w - 4.0 * scale_x, 14.0 * scale_y), Qt.AlignmentFlag.AlignLeft, label)

            # Affichage de l'intensité numérique
            if intensity > 0.05:
                pct_str = f"{int(round(intensity * 100))}%"
                pct_font = QFont("Segoe UI", max(6, int(7.5 * scale_y)), QFont.Weight.Bold)
                painter.setFont(pct_font)
                painter.setPen(QPen(QColor(255, 255, 255, 255)))
                painter.drawText(QRectF(x + 2.0 * scale_x, y + tire_h - 16.0 * scale_y, tire_w - 4.0 * scale_x, 14.0 * scale_y), Qt.AlignmentFlag.AlignCenter, pct_str)
