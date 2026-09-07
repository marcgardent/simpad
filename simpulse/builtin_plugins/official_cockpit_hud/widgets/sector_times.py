"""
Sector Times Widget — 3-sector time boxes (S1, S2, S3) positioned below Delta timer in compact canvas.
"""

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QBrush
from .base_widget import BaseQtHudWidget, CockpitWidgetContext


# IHM-only presentation: the model may deliver the same frozen split under either
# '38.437' (parser seconds form) or '00:38.437' (delta engine). Both mean the same
# time. The model is not forced to a format; the widget canonicalises the drawn
# string itself so a frozen box never changes width for the same value.
_EMPTY_TIME_VALUES = ("", "--", "--:--.---")


def _present_split_time(value: str) -> str:
    """Paint helper: render a frozen sector split time in MM:ss.mmm form."""
    raw = (value or "").strip()
    if raw in _EMPTY_TIME_VALUES:
        return "--" if raw in ("", "--") else raw
    # Already in an M:ss.mmm or MM:ss.mmm spelling (minutes present) -> unchanged,
    # this spelling is stable beween both authors.
    if ":" in raw:
        try:
            head, _, tail = raw.partition(":")
            float(tail)
            int(head)
            return raw
        except ValueError:
            pass
    # Pure seconds "ss.mmm" (LMUParser compact form) -> present as MM:ss.mmm.
    try:
        total = float(raw)
    except ValueError:
        return raw  # unknown literal: pass through untouched (no width guarantee)
    if total <= 0.0:
        return "--"
    mins = int(total // 60)
    rest = total % 60.0
    if mins > 0:
        return f"{mins}:{rest:06.3f}"
    return f"00:{rest:06.3f}"


class QtSectorTimesWidget(BaseQtHudWidget):
    """
    Lap Sectors S1, S2, S3 (Positioned below Delta and Gear).

    Colour is aligned with the Delta Timer widget above it — SESSION-scoped
    only, sourced from sensors.expected_sectorN_status (never the sign of the
    live delta, never pink):
        * Purple (sector projection beats paddock / other cars this session)
        * Green  (beats my session best for this sector)
        * Yellow (valid, slower than my session)
        * Grey   (invalid / no reference)
    Beating my all-time-best split ("ever") is a "PR" tag drawn on the box,
    not a colour — see sensors.expected_sectorN_is_pr.
    """

    def __init__(self, font_family: str = "Anta"):
        self.font_family = font_family
        self._last_rendered_sector: int = -1

    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        context: CockpitWidgetContext,
    ) -> None:
        sensors = context.sensors
        sectors = sensors.sectors_list

        _cap_text: list = []   # exact strings painted, per box 0..2 (diagnostic)
        _cap_mode: list = []   # 'live' | 'frozen' per box (diagnostic)
        _cap_bg: list = []     # (r,g,b) background painted per box (diagnostic)

        curr_sec = sensors.current_sector
        if curr_sec != self._last_rendered_sector:
            try:
                from simpulse.core.telemetry.overlay_anomaly_logger import OverlayAnomalyLogger
                OverlayAnomalyLogger.get_instance().check_sector_update(
                    current_sector=curr_sec,
                    raw_sector=curr_sec,
                    source="QtSectorTimesWidget",
                    s1_time=sensors.sector1_time,
                    s2_time=sensors.sector2_time,
                    s3_time=sensors.sector3_time,
                    s1_delta=sensors.sector1_delta,
                    s2_delta=sensors.sector2_delta,
                    s3_delta=sensors.sector3_delta,
                    lap_dist=sensors.lap_dist if hasattr(sensors, "lap_dist") else 0.0,
                    speed_kmh=sensors.vehicle_speed * 3.6,
                )
            except Exception:
                pass
            self._last_rendered_sector = curr_sec

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        sector_w = 90.0 * scale_x
        sector_h = 24.0 * scale_y
        sector_spacing = 8.0 * scale_x

        total_width = (sector_w * 3.0) + (sector_spacing * 2.0)
        start_x = center_x - (total_width / 2.0)
        sector_y = 198.0 * scale_y

        font_size = max(9, int(round(13.0 * scale_y)))
        font = QFont(self.font_family)
        font.setPixelSize(font_size)
        font.setBold(True)
        painter.setFont(font)

        for i in range(min(3, len(sectors))):
            s_x = start_x + (i * (sector_w + sector_spacing))
            sec = sectors[i]
            s_time = sec.time
            is_current = sec.is_current
            delta_str = sec.delta_str

            # Colour is aligned with the Delta Timer above: SESSION-scoped
            # expected_sectorN_status only (purple/green/yellow/grey), the
            # same field whether the sector is still live or already frozen.
            expected_tok = str(getattr(sensors, f"expected_sector{i + 1}_status", "white") or "white").strip()
            is_pr = bool(getattr(sensors, f"expected_sector{i + 1}_is_pr", False))

            # Text: live sector delta while ongoing, else frozen split time
            # presented in a stable IHM format whatever the model spelling
            # ('38.437' or '00:38.437').
            if is_current and delta_str != "--":
                disp_text = delta_str
            else:
                disp_text = _present_split_time(s_time)

            if expected_tok in ("invalid", "white"):
                bg_color = QColor(15, 23, 42, 255)
                border_color = QColor(51, 65, 85, 255)
            elif expected_tok == "purple":
                bg_color = QColor(147, 51, 234, 255)
                border_color = QColor(168, 85, 247, 255)
            elif expected_tok == "green":
                bg_color = QColor(22, 163, 74, 255)
                border_color = QColor(34, 197, 94, 255)
            elif expected_tok == "yellow":
                bg_color = QColor(161, 98, 7, 255)
                border_color = QColor(234, 179, 8, 255)
            else:
                bg_color = QColor(15, 23, 42, 255)
                border_color = QColor(51, 65, 85, 255)

            # Marked white border for current active sector
            _cap_text.append(disp_text)
            _cap_mode.append("live" if (is_current and delta_str != "--") else "frozen")
            _cap_bg.append((int(bg_color.red()), int(bg_color.green()), int(bg_color.blue())))
            if is_current:
                border_color = QColor(255, 255, 255, 255)
                pen_width = 2
            else:
                pen_width = 1

            # Box background
            rect = QRectF(s_x, sector_y, sector_w, sector_h)
            painter.setBrush(QBrush(bg_color))
            painter.setPen(QPen(border_color, pen_width))
            painter.drawRect(rect)

            # Time text
            painter.setPen(QPen(QColor(255, 255, 255, 255)))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, disp_text)

            # All-time-best beaten for this sector: "PR" tag, not a colour.
            if is_pr:
                pr_font = QFont(self.font_family)
                pr_font.setPixelSize(max(8, int(round(9.0 * scale_y))))
                pr_font.setBold(True)
                painter.setFont(pr_font)
                painter.setPen(QPen(QColor(255, 105, 180, 255)))
                painter.drawText(
                    QRectF(s_x, sector_y - (11.0 * scale_y), sector_w, 10.0 * scale_y),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    "PR",
                )
                painter.setFont(font)

        # --- diagnostic paint logger (opt-in, no behaviour change) ---
        try:
            if _cap_text:
                from simpulse.builtin_plugins.official_cockpit_hud.widgets.sector_paint_recorder import record
                record(int(sensors.current_sector), tuple(_cap_text), tuple(_cap_mode), tuple(_cap_bg))
        except Exception:
            pass
