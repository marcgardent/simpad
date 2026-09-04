"""
Lap Status Widget — Two SVG icon badges below the aero bar:
1. Lap Validity badge: timing_in_progress (valid) vs time_deleted (invalid) from count_lap_flag
2. Clean/Dirty Lap badge: 0 hits = Clean, >0 hits = Dirty (from TelemInfo.last_impact_et)
Exclusively uses native Qt SVG rendering (QSvgRenderer) from assets/icons/*.svg.
"""

from pathlib import Path
from typing import Dict, Any, Optional, Union

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter
from PySide6.QtSvg import QSvgRenderer

from .base_widget import BaseQtHudWidget
from simpad_qt.core.telemetry import VehicleSensors

# Default location inside the Official Cockpit HUD plugin folder
_PLUGIN_ICONS_DIR = Path(__file__).resolve().parent.parent / "icons"


def _resolve_default_icons_dir() -> Path:
    return _PLUGIN_ICONS_DIR


class QtLapStatusWidget(BaseQtHudWidget):
    """
    Two SVG icon badges rendered below the aero bar (separate visual layer from aero load).
    Left badge: Lap Timing Validity (timing_in_progress / time_deleted) -> lap_valid.svg / lap_invalid.svg
    Right badge: Clean/Dirty Lap (0 hits vs >0 hits in current lap) -> clean_lap.svg / dirty_lap.svg
    """

    def __init__(self, icons_dir: Optional[Union[Path, str]] = None):
        self.icons_dir: Path = Path(icons_dir) if icons_dir is not None else _resolve_default_icons_dir()
        self._svg_lap_valid: Optional[QSvgRenderer] = None
        self._svg_lap_invalid: Optional[QSvgRenderer] = None
        self._svg_clean_lap: Optional[QSvgRenderer] = None
        self._svg_dirty_lap: Optional[QSvgRenderer] = None
        self.reload_svgs()

    def _load_svg(self, base_name: str) -> Optional[QSvgRenderer]:
        """Loads native Qt SVG icon from self.icons_dir/{base_name}.svg."""
        svg_path = self.icons_dir / f"{base_name}.svg"
        if svg_path.exists():
            renderer = QSvgRenderer(str(svg_path))
            if renderer.isValid():
                return renderer
        return None

    def reload_svgs(self) -> None:
        """Loads or refreshes the 4 SVG renderers from self.icons_dir."""
        self._svg_lap_valid = self._load_svg("lap_valid")
        self._svg_lap_invalid = self._load_svg("lap_invalid")
        self._svg_clean_lap = self._load_svg("clean_lap")
        self._svg_dirty_lap = self._load_svg("dirty_lap")

    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        # Position: directly below the aero bar (aero_y=250, aero_height=12)
        badge_size = 24.0 * min(scale_x, scale_y)
        badge_gap = 14.0 * scale_x
        badge_y = (250.0 + 12.0 + 6.0) * scale_y

        # Total width of 2 badges + gap, centered horizontally
        total_w = badge_size * 2 + badge_gap
        start_x = center_x - total_w / 2.0

        # ── Badge 1: Lap Validity (timing_in_progress vs time_deleted) ──
        lap_flag = extra_data.get("lap_flag", getattr(sensors, "lap_flag", 2))
        is_lap_valid = (lap_flag == 2)

        svg_validity = self._svg_lap_valid if is_lap_valid else self._svg_lap_invalid
        if svg_validity is None or not svg_validity.isValid():
            self.reload_svgs()
            svg_validity = self._svg_lap_valid if is_lap_valid else self._svg_lap_invalid

        rect_validity = QRectF(start_x, badge_y, badge_size, badge_size)
        if svg_validity and svg_validity.isValid():
            svg_validity.render(painter, rect_validity)
        else:
            self._paint_fallback_dot(painter, rect_validity, is_lap_valid)

        # ── Badge 2: Clean / Dirty Lap (Clean = timing_in_progress && 0 hits) ──
        hit_count = int(extra_data.get("hit_count_current_lap", 0))
        is_clean = (is_lap_valid and hit_count == 0)

        svg_clean_dirty = self._svg_clean_lap if is_clean else self._svg_dirty_lap
        if svg_clean_dirty is None or not svg_clean_dirty.isValid():
            self.reload_svgs()
            svg_clean_dirty = self._svg_clean_lap if is_clean else self._svg_dirty_lap

        rect_clean = QRectF(start_x + badge_size + badge_gap, badge_y, badge_size, badge_size)
        if svg_clean_dirty and svg_clean_dirty.isValid():
            svg_clean_dirty.render(painter, rect_clean)
        else:
            self._paint_fallback_dot(painter, rect_clean, is_clean)

    @staticmethod
    def _paint_fallback_dot(painter: QPainter, rect: QRectF, is_positive: bool) -> None:
        """Fallback circle indicator if SVG is missing or failed to parse."""
        from PySide6.QtGui import QColor, QBrush, QPen
        from PySide6.QtCore import QPointF

        color = QColor(34, 197, 94, 255) if is_positive else QColor(239, 68, 68, 255)
        cx = rect.center().x()
        cy = rect.center().y()
        radius = min(rect.width(), rect.height()) / 2.0

        painter.setBrush(QBrush(color))
        painter.setPen(QPen(QColor(15, 23, 42, 255), 1.5))
        painter.drawEllipse(QPointF(cx, cy), radius, radius)
