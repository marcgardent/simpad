"""
Rev Indicator Widget — Left/Right triangle indicators for underrev and overrev warnings, aligned with compact Gear.
"""

from typing import Dict, Any
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QPolygonF
from src.gui.overlay.base_widget import BaseQtHudWidget
from src.telemetry.sensors import VehicleSensors


class QtRevIndicatorWidget(BaseQtHudWidget):
    """
    Indicateurs de Régime Moteur (Triangles du HUD).
    - Triangle gauche (sous-régime / downshift sweet spot).
    - Triangle droit (sur-régime / upshift redline).
    """

    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        underrev = extra_data.get("underrev", sensors.underrev_intensity > 0.1)
        overrev = extra_data.get("overrev", sensors.overrev_intensity > 0.1)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        painter.setBrush(QBrush(QColor(255, 255, 255, 255)))
        painter.setPen(QPen(QColor(255, 255, 255, 255)))

        # Triangle Sous-régime (Gauche)
        if underrev:
            p1 = QPointF(center_x - (130.0 * scale_x), 110.0 * scale_y)
            p2 = QPointF(center_x - (90.0 * scale_x), 80.0 * scale_y)
            p3 = QPointF(center_x - (90.0 * scale_x), 140.0 * scale_y)
            poly_left = QPolygonF([p1, p2, p3])
            painter.drawPolygon(poly_left)

        # Triangle Sur-régime (Droite)
        if overrev:
            p1 = QPointF(center_x + (130.0 * scale_x), 110.0 * scale_y)
            p2 = QPointF(center_x + (90.0 * scale_x), 80.0 * scale_y)
            p3 = QPointF(center_x + (90.0 * scale_x), 140.0 * scale_y)
            poly_right = QPolygonF([p1, p2, p3])
            painter.drawPolygon(poly_right)
