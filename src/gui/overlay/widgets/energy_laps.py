"""
Energy & Laps Widget — Remaining energy and laps display positioned under gear in compact canvas.
"""

from typing import Dict, Any
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QPen
from src.gui.overlay.base_widget import BaseQtHudWidget
from src.telemetry.sensors import VehicleSensors


class QtEnergyLapsWidget(BaseQtHudWidget):
    """
    Energy & Remaining Laps (Positioned on the right below Gear).
    """

    def __init__(self, font_family: str = "Anta"):
        self.font_family = font_family

    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        energy = float(extra_data.get("energyLaps", sensors.fuel_level))
        remaining_laps = int(extra_data.get("remainingLaps", sensors.remaining_laps))

        val_str = f"{energy:.1f} / {remaining_laps}" if (energy > 0 or remaining_laps > 0) else "-- / --"
        sub_str = "ENERGY / LAPS"

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0

        val_font_size = max(10, int(round(16.0 * scale_y)))
        sub_font_size = max(8, int(round(10.0 * scale_y)))

        right_margin = 40.0 * scale_x
        val_x_pos = canvas_w - right_margin - (len(val_str) * val_font_size * 0.55)
        sub_x_pos = canvas_w - right_margin - (len(sub_str) * sub_font_size * 0.55)

        base_y = 170.0 * scale_y

        # Value text
        val_font = QFont(self.font_family)
        val_font.setPixelSize(val_font_size)
        val_font.setBold(True)
        painter.setFont(val_font)
        painter.setPen(QPen(QColor(255, 255, 255, 255)))
        painter.drawText(QRectF(val_x_pos, base_y, 200, val_font_size + 6), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, val_str)

        # Subtext label
        sub_font = QFont(self.font_family)
        sub_font.setPixelSize(sub_font_size)
        sub_font.setBold(True)
        painter.setFont(sub_font)
        painter.setPen(QPen(QColor(148, 163, 184, 255)))
        painter.drawText(QRectF(sub_x_pos, base_y + (20.0 * scale_y), 200, sub_font_size + 6), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, sub_str)
