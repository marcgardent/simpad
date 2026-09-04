"""
Aero Bar Widget — Bottom horizontal aerodynamic downforce bar in compact canvas.
Dynamically bound to vehicle speed aerodynamic load (0% to 100%).
Color lerps from Red (0%) -> Violet (33%) -> Blue (66%) -> Green (100%).
"""

from typing import Dict, Any
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QBrush, QPen
from .base_widget import BaseQtHudWidget, lerp
from simpad_qt.core.telemetry import VehicleSensors


def get_aero_qcolor_ramp(a: float) -> QColor:
    """Calculates color ramp: Red (0%) -> Violet (33%) -> Blue (66%) -> Green (100%)."""
    a = max(0.0, min(1.0, a))
    if a <= 0.3333:
        t = a / 0.3333
        r = int(round(lerp(239.0, 168.0, t)))
        g = int(round(lerp(68.0, 85.0, t)))
        b = int(round(lerp(68.0, 247.0, t)))
    elif a <= 0.6666:
        t = (a - 0.3333) / 0.3333
        r = int(round(lerp(168.0, 59.0, t)))
        g = int(round(lerp(85.0, 130.0, t)))
        b = int(round(lerp(247.0, 246.0, t)))
    else:
        t = (a - 0.6666) / 0.3334
        r = int(round(lerp(59.0, 34.0, t)))
        g = int(round(lerp(130.0, 197.0, t)))
        b = int(round(lerp(246.0, 94.0, t)))
    return QColor(r, g, b, 255)


class QtAeroBarWidget(BaseQtHudWidget):
    """
    Aerodynamic Downforce Bar (Bottom of compact HUD) and lap validity indicator dot.
    """

    def __init__(self):
        self.display_aero: float = 0.0

    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        if "aero" in extra_data:
            raw_aero = float(extra_data["aero"])
        else:
            raw_aero = sensors.aero_load * 100.0

        # LERP Smoothing (0.65 immediate response)
        self.display_aero = lerp(self.display_aero, raw_aero, 0.65)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        # Width (330px) sized to fit between rear tires
        aero_width = 330.0 * scale_x
        aero_height = 12.0 * scale_y
        aero_x = center_x - (aero_width / 2.0)
        aero_y = 250.0 * scale_y

        # Background track
        painter.setBrush(QBrush(QColor(17, 24, 39, 120)))
        painter.setPen(QPen(QColor(30, 41, 59, 200), 1))
        painter.drawRoundedRect(QRectF(aero_x, aero_y, aero_width, aero_height), 2.0 * scale_x, 2.0 * scale_y)

        # Fill with 4-stage color ramp
        a = max(0.0, min(1.0, self.display_aero / 100.0))
        bar_color = get_aero_qcolor_ramp(a)

        fill_width = a * aero_width
        if fill_width > 0.5:
            painter.setBrush(QBrush(bar_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(aero_x, aero_y, fill_width, aero_height), 2.0 * scale_x, 2.0 * scale_y)
