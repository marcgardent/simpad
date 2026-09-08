"""
Delta Timer Widget — Display expected lap delta time positioned below gear in compact canvas.
"""

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QPen
from .base_widget import BaseQtHudWidget, CockpitWidgetContext


class QtDeltaTimerWidget(BaseQtHudWidget):
    """
    Delta Timer / Lap Time (Positioned below Gear).
    - On track: Displays Live Delta (e.g. '-0.150' in Green, '+0.240' in Red).
    - Line crossing: Displays Completed Lap Time (format MM:ss.mmm)

    Colour is SESSION-scoped only — no pink:
        * Purple (Session / paddock best)
        * Green  (Personal / my-session best)
        * Yellow (No improvement / slower)
        * Grey   (Invalid lap)
    Beating my all-time best ("ever") is never a colour: a "PR" tag is drawn
    next to the value instead — same convention as the sector boxes below and
    simpulse.builtin_plugins.expected_timing.
    """

    def __init__(self, font_family: str = "Anta"):
        self.font_family = font_family

    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        context: CockpitWidgetContext,
    ) -> None:
        sensors = context.sensors
        is_freeze = sensors.is_lap_freeze_active
        lap_flag = sensors.lap_flag
        lap_time_str = sensors.last_lap_time_str
        lap_status = sensors.last_lap_status
        expected_str = sensors.delta_time_str

        is_pr = False

        if is_freeze:
            # Line crossing mode: Completed Lap Time (MM:ss.mmm)
            disp_str = lap_time_str if lap_time_str not in ("", "--") else "--:--.---"
            is_pr = bool(getattr(sensors, "last_lap_is_pr", False))

            if lap_flag == 0 or lap_status == "invalid":
                # Invalid lap -> Grey
                text_color = QColor(156, 163, 175, 255)
            elif lap_status == "purple":
                # Session / paddock best -> Purple
                text_color = QColor(168, 85, 247, 255)
            elif lap_status == "green":
                # Personal improvement -> Green
                text_color = QColor(34, 197, 94, 255)
            elif lap_status == "yellow":
                # No improvement / slower -> Yellow
                text_color = QColor(234, 179, 8, 255)
            else:
                text_color = QColor(255, 255, 255, 255)
        else:
            # On-track mode: Live Delta — colour follows the EXPECTED-lap decision
            # (projection vs paddock/my-session), parsed by the engine. Session-
            # scoped only: beating my all-time-best ("ever") is never a colour
            # here, it's the expected_lap_is_pr flag below (-> "PR" tag).
            disp_str = expected_str
            expected_tok = str(getattr(sensors, "expected_status", "") or "").strip()
            is_pr = bool(getattr(sensors, "expected_lap_is_pr", False))

            if lap_flag == 0 or expected_tok == "invalid":
                # Invalid lap -> Grey
                text_color = QColor(156, 163, 175, 255)
            elif expected_tok == "purple":
                # PROJ < paddock best (other cars)
                text_color = QColor(168, 85, 247, 255)
            elif expected_tok == "green":
                # PROJ < my session best
                text_color = QColor(34, 197, 94, 255)
            elif expected_tok == "yellow":
                # PROJ slower than my session
                text_color = QColor(234, 179, 8, 255)
            else:
                # No usable reference yet (white) -> neutral, never red/green by
                # sign. Purple/green/yellow/grey is the ONE colour scale for
                # every delta display (lap or sector) — no other tier exists.
                text_color = QColor(255, 255, 255, 255)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0

        font_size = max(14, int(round(28.0 * scale_y)))
        y_pos = 166.0 * scale_y

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

        if is_pr:
            # All-time-best beaten: text tag, not a colour (see class docstring).
            pr_font = QFont(self.font_family)
            pr_font.setPixelSize(max(10, int(round(13.0 * scale_y))))
            pr_font.setBold(True)
            painter.setFont(pr_font)
            painter.setPen(QPen(QColor(255, 255, 255, 255)))
            painter.drawText(
                QRectF(0, y_pos - (15.0 * scale_y), canvas_w, 14.0 * scale_y),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                "PR",
            )
