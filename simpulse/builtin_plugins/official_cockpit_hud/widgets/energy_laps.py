"""
Energy & Laps Widget — Full EnergyPacket readout positioned under gear in
compact canvas: a small table of cells (pace medians, session progress,
energy vs. what's needed to finish) and a fuel-anomaly banner. All of it
gated by the single "Remaining Fuel / Energy & Laps" layer toggle
(OfficialCockpitHudConfig.show_energy) — see OfficialCockpitHudTabWidget's
"🧩 Modular Component Toggles" group.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QBrush, QPolygonF
from PySide6.QtSvg import QSvgRenderer
from simpulse_sdk import format_lap_time
from .base_widget import BaseQtHudWidget, CockpitWidgetContext

_ICONS_DIR = Path(__file__).resolve().parent.parent / "icons"

_BG_COLOR = QColor(15, 23, 42, 255)
_BORDER_COLOR = QColor(51, 65, 85, 255)
_WHITE = QColor(255, 255, 255, 255)
_GREY = QColor(148, 163, 184, 255)
_GREEN = QColor(34, 197, 94, 255)
_RED = QColor(239, 68, 68, 255)


def _fmt_pct(ratio: Optional[float]) -> str:
    """None -> '--' (session length not known yet — practice/warmup, or no
    combo resolved), otherwise a whole-percent string."""
    return "--" if ratio is None else f"{ratio * 100.0:.0f}%"


def _fmt_clock(seconds: Optional[float]) -> str:
    """Session-scale clock, MM:SS — no sub-second decimals (that's
    format_lap_time's job for an actual lap time, a different order of
    magnitude). None/negative -> '--:--'."""
    if seconds is None or seconds < 0.0:
        return "--:--"
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


def _fmt_laps(value) -> str:
    return "--" if value is None else f"{value:.0f}"


class QtEnergyLapsWidget(BaseQtHudWidget):
    """
    Energy & Laps table (Positioned on the right below Gear) — every figure
    sourced from CockpitWidgetContext.energy (EnergyPacket), never
    VehicleSensors (see its deprecated fuel_level/energy_*/session_*
    properties):

      [Energy Median] [Time Median]   — FuelEnergyEngine's 64-lap medians,
                                         never a best/PB time. No slant.
      [ELAPSED] / [MAX]               — session_energy_gauge's raw session
                                         clock (time-limited sessions;
                                         '--' otherwise).
      [DONE] / [LEFT]                 — laps done so far / laps left in the
                                         session.
      [AVAILABLE] / [NEEDED]          — current level vs. what finishing the
                                         session needs at the pace median.
                                         Flanked by fuel_error.svg (red fuel
                                         can) when FuelEnergyEngine flags a
                                         fuel anomaly (see below).

    Every row is a pair of cells with a small margin between them (see
    _draw_diagonal_pair) instead of a single cell with a plain "/" between
    the two figures. Only the bottom three rows lean that divider (a
    racing-HUD chevron look); the top row is a plain upright pair.

    Table position: right-anchored off QtTcGaugeWidget's own real geometry
    (center_x + 254 + gauge_width, gauge_y, gauge_height — see tc_gauge.py)
    instead of an independent `canvas_w - margin` guess, which used to land
    almost exactly on top of the TC bar. Vertically centered on TC's own
    gauge span.

    Below the table, an anomaly banner appears only when EnergyPacket.
    fuel_anomaly is True: not enough energy to finish the session AND the
    tank isn't topped up (FuelEnergyEngine.has_insufficient_fuel_anomaly) —
    a car that structurally can't finish on one tank even full is NOT an
    anomaly, that's just the car; this flags "you could still fix this with
    a splash-and-dash", i.e. probably forgot to refuel.
    """

    def __init__(self, font_family: str = "Anta", icons_dir: Optional[Path] = None):
        self.font_family = font_family
        self.icons_dir: Path = Path(icons_dir) if icons_dir is not None else _ICONS_DIR
        self._svg_fuel_error: Optional[QSvgRenderer] = None
        self._load_svg()

    def _load_svg(self) -> None:
        svg_path = self.icons_dir / "fuel_error.svg"
        if svg_path.exists():
            renderer = QSvgRenderer(str(svg_path))
            if renderer.isValid():
                self._svg_fuel_error = renderer
                return
        self._svg_fuel_error = None

    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        context: CockpitWidgetContext,
    ) -> None:
        e = context.energy
        unit = "%" if e.is_percentage else "L"

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0

        table_w = 95.0 * scale_x
        center_x = canvas_w / 2.0
        tc_right_edge = center_x + (254.0 * scale_x) + (14.0 * scale_x)
        table_x = tc_right_edge + (10.0 * scale_x)
        skew = 4.0 * scale_x

        gutter_x = 3.0 * scale_x
        gutter_y = 3.0 * scale_y

        label_font_size = max(7, int(round(8.5 * scale_y)))
        value_font_size = max(10, int(round(13.0 * scale_y)))

        row_h = 30.0 * scale_y
        num_rows = 4

        tc_gauge_y = 15.0 * scale_y
        tc_gauge_h = 245.0 * scale_y
        table_h = num_rows * row_h + (num_rows - 1) * gutter_y
        y = tc_gauge_y + (tc_gauge_h - table_h) / 2.0

        # ── Row 1: energy median | lap time median — no slant, this pair
        # was never a "/"-replacement (see class docstring) ──
        conso_str = f"{e.consumption_per_lap:.1f}{unit}" if e.consumption_per_lap > 0 else "--"
        lap_time_str = format_lap_time(e.lap_time_median) if e.lap_time_median > 0 else "--:--.---"
        self._draw_diagonal_pair(
            painter, table_x, y, table_w, row_h, 0.0, gutter_x,
            "Energy Median", conso_str, "Time Median", lap_time_str,
            label_font_size, value_font_size,
        )
        y += row_h + gutter_y

        # ── Row 2: session elapsed / total time ──
        self._draw_diagonal_pair(
            painter, table_x, y, table_w, row_h, skew, gutter_x,
            "ELAPSED", _fmt_clock(e.session_time_elapsed), "MAX", _fmt_clock(e.session_time_total),
            label_font_size, value_font_size,
        )
        y += row_h + gutter_y

        # ── Row 3: laps done / laps left in session ──
        self._draw_diagonal_pair(
            painter, table_x, y, table_w, row_h, skew, gutter_x,
            "DONE", str(e.session_laps_done), "LEFT", _fmt_laps(e.session_laps_left),
            label_font_size, value_font_size,
        )
        y += row_h + gutter_y

        # ── Row 4: energy available / needed to finish (+ anomaly icon) ──
        laps_val_ok = e.projected_laps if e.projected_laps > 0 else context.sensors.remaining_laps
        level_str = f"{e.level:.1f}{unit}" if (e.level > 0 or laps_val_ok > 0) else "--"
        needed_str = f"{e.session_energy_needed:.1f}{unit}" if e.session_energy_needed is not None else "--"
        energy_color = _RED if e.fuel_anomaly else (_GREEN if (e.session_energy_ratio or 0.0) >= 1.0 else _WHITE)
        icon_w = row_h if (self._svg_fuel_error and e.fuel_anomaly) else 0.0
        self._draw_diagonal_pair(
            painter, table_x, y, table_w - icon_w - (gutter_x if icon_w else 0.0), row_h, skew, gutter_x,
            "AVAILABLE", level_str, "NEEDED", needed_str,
            label_font_size, value_font_size,
            left_color=energy_color, right_color=energy_color,
        )
        if icon_w:
            icon_rect = QRectF(table_x + table_w - icon_w, y, icon_w, row_h)
            self._svg_fuel_error.render(painter, icon_rect)
        y += row_h + gutter_y

        # ── Anomaly banner ──
        if e.fuel_anomaly:
            banner_font_size = max(7, int(round(8.5 * scale_y)))
            banner_font = QFont(self.font_family)
            banner_font.setPixelSize(banner_font_size)
            banner_font.setBold(True)
            painter.setFont(banner_font)
            painter.setPen(QPen(_RED))
            painter.drawText(
                QRectF(table_x, y, table_w, banner_font_size + 20),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                "⛽ FUEL ANOMALY: not enough to finish, tank not topped up",
            )

    def _draw_diagonal_pair(
        self,
        painter: QPainter,
        x: float,
        y: float,
        w: float,
        h: float,
        skew: float,
        divider_gap: float,
        left_label: str,
        left_value: str,
        right_label: str,
        right_value: str,
        label_font_size: int,
        value_font_size: int,
        left_color: QColor = _WHITE,
        right_color: QColor = _WHITE,
    ) -> None:
        """Two cells with a `divider_gap`-wide margin between them instead of
        a single cell with a "left / right" string. `skew` is how far the
        divider leans (in canvas units) — a racing-HUD chevron look; 0 draws
        a plain upright pair (see class docstring: only some rows lean it)."""
        mid_x = x + w / 2.0
        half_gap = divider_gap / 2.0
        left_top_x = mid_x + skew - half_gap
        left_bottom_x = mid_x - skew - half_gap
        right_top_x = mid_x + skew + half_gap
        right_bottom_x = mid_x - skew + half_gap

        left_poly = QPolygonF([QPointF(x, y), QPointF(left_top_x, y), QPointF(left_bottom_x, y + h), QPointF(x, y + h)])
        right_poly = QPolygonF([QPointF(right_top_x, y), QPointF(x + w, y), QPointF(x + w, y + h), QPointF(right_bottom_x, y + h)])

        painter.setBrush(QBrush(_BG_COLOR))
        painter.setPen(QPen(_BORDER_COLOR, 1))
        painter.drawPolygon(left_poly)
        painter.drawPolygon(right_poly)

        # Left cell's usable width is capped by its edge's NARROWEST point
        # so its text never bleeds under the divider gap; symmetrically, the
        # right cell starts from its edge's WIDEST point.
        left_w = max(0.0, min(left_top_x, left_bottom_x) - x - 8.0)
        right_x = max(right_top_x, right_bottom_x) + 4.0
        right_w = max(0.0, (x + w) - right_x - 4.0)

        self._draw_cell_text(painter, x + 4.0, y, left_w, h, left_label, left_value, label_font_size, value_font_size, left_color)
        self._draw_cell_text(painter, right_x, y, right_w, h, right_label, right_value, label_font_size, value_font_size, right_color)

    def _draw_cell_text(
        self,
        painter: QPainter,
        x: float,
        y: float,
        w: float,
        h: float,
        label: str,
        value: str,
        label_font_size: int,
        value_font_size: int,
        value_color: QColor,
    ) -> None:
        label_font = QFont(self.font_family)
        label_font.setPixelSize(label_font_size)
        label_font.setBold(True)
        painter.setFont(label_font)
        painter.setPen(QPen(_GREY))
        painter.drawText(
            QRectF(x, y + 2, w, label_font_size + 4),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            label,
        )

        value_font = QFont(self.font_family)
        value_font.setPixelSize(value_font_size)
        value_font.setBold(True)
        painter.setFont(value_font)
        painter.setPen(QPen(value_color))
        painter.drawText(
            QRectF(x, y + label_font_size + 4, w, value_font_size + 4),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            value,
        )
