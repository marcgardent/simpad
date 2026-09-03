"""
Delta Timer Widget — Display expected lap delta time positioned below gear in compact canvas.
"""

from typing import Dict, Any
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QPen
from src.gui.overlay.base_widget import BaseQtHudWidget
from src.telemetry.sensors import VehicleSensors


class QtDeltaTimerWidget(BaseQtHudWidget):
    """
    Chrono Delta / Temps au Tour (Positionné sous le Gear).
    - En piste : Affiche le Delta Live (ex: '-0.150' en Vert, '+0.240' en Rouge).
    - Passage de ligne : Affiche le Temps au Tour complété (format MM:ss.mmm)
      avec code couleur cohérent :
        * Violet (Session / All-Time Best)
        * Vert (Amélioration Personnelle)
        * Jaune (Non amélioré / Plus lent)
        * Gris (Tour Invalide / Dirty)
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
        is_freeze = extra_data.get("isLapFreezeActive", getattr(sensors, "is_lap_freeze_active", False))
        lap_flag = extra_data.get("lap_flag", getattr(sensors, "lap_flag", 2))

        if is_freeze:
            # ── Mode Passage de Ligne : Temps au Tour complété (MM:ss.mmm) ──
            lap_time_str = str(extra_data.get("lastLapTime", getattr(sensors, "last_lap_time_str", "--:--.---")))
            disp_str = lap_time_str if lap_time_str not in ("", "--") else "--:--.---"
            lap_status = str(extra_data.get("lastLapStatus", getattr(sensors, "last_lap_status", "default")))

            if lap_flag == 0 or lap_status == "invalid":
                # Tour Dirty / Invalide -> Gris
                text_color = QColor(156, 163, 175, 255)
            elif lap_status == "purple":
                # Meilleur tour absolu / session -> Violet
                text_color = QColor(168, 85, 247, 255)
            elif lap_status == "green":
                # Amélioration personnelle -> Vert
                text_color = QColor(34, 197, 94, 255)
            elif lap_status in ("yellow", "red"):
                # Non amélioré / plus lent -> Jaune
                text_color = QColor(234, 179, 8, 255)
            else:
                text_color = QColor(255, 255, 255, 255)
        else:
            # ── Mode En Piste : Delta Live ──
            expected_str = str(extra_data.get("expectedTime", sensors.delta_time_str))
            disp_str = expected_str

            if lap_flag == 0:
                # Tour Dirty / Invalide -> Gris
                text_color = QColor(156, 163, 175, 255)
            elif expected_str.startswith("-"):
                # En avance -> Vert
                text_color = QColor(34, 197, 94, 255)
            elif expected_str in ("--", "0.000", "+0.000", "-0.000", "0", ""):
                text_color = QColor(255, 255, 255, 255)
            else:
                # En retard -> Rouge
                text_color = QColor(239, 68, 68, 255)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0

        font_size = max(14, int(round(32.0 * scale_y)))
        y_pos = 170.0 * scale_y

        font = QFont(self.font_family)
        font.setPixelSize(font_size)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(text_color))
        painter.drawText(
            QRectF(0, y_pos, canvas_w, font_size + 10 * scale_y),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            disp_str,
        )
