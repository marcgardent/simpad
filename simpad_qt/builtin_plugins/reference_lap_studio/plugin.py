"""
SimPad Reference Lap & Mark Editor Studio Built-in Plugin (Qt6 Pure).

Provides:
- Ultra-fast 60/120 FPS spatial telemetry curve visualizer with cached vector polygons.
- Dominant spatial graph on the left and dedicated vertical Pace Notes / Annotations table on the right.
- S1, S2, S3 Sector background bands and timing checkpoints.
- Full Track Annotations & Pace Notes Studio:
  - Add Brake (B), Turn-in (I), Virages T1..T30 (T), Rapports G1..G8 (1-8).
  - Row action buttons: [▶] Test Audio, [✕] Remove marker.
  - Interactive drag-and-drop on the plot.
  - Auto-save to <profile>.marks.json.
- Multi-reference mode switching (All-Time Best, Session Best, Stint Best, Last Lap).
"""

from __future__ import annotations
import math
import time
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from PySide6.QtCore import Qt, QSize, QRectF, QPointF, Signal
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QPolygonF, QKeySequence, QShortcut
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QComboBox, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QGroupBox, QSplitter, QFrame, QMessageBox,
    QAbstractItemView, QSizePolicy
)

from simpad_qt.plugins.contracts import (
    SimPadPlugin, PluginMetadata, PluginContext,
    ITabProvider, ITelemetrySubscriber, IDeltaSubscriber
)
from simpad_qt.core.reference_lap import (
    ReferenceLapManager, LapDeltaPacket, ReferenceLapProfile,
    TrackAnnotation, AnnotationType, DeltaReferenceMode,
    DEFAULT_REF_LAPS_DIR, format_lap_time
)
from src.telemetry.sensors import VehicleSensors
from src.utils.audio import AudioAnnouncer

logger = logging.getLogger("simpad.plugin.reference_lap_studio")


@dataclass
class ReferenceLapStudioConfig:
    """Strongly-typed config for Reference Lap Studio."""
    auto_sync_car: bool = False
    snap_step: float = 1.0


class SpatialTelemetryCanvas(QWidget):
    """
    High-performance vector rendering canvas displaying 1m spatial telemetry curves and annotations.
    Features cached polygons for 60/120 FPS zero-lag scrubbing and drag-and-drop.
    """

    cursor_moved = Signal(float)       # distance in meters
    annotation_selected = Signal(str)  # annotation id

    def __init__(self, tab_widget: ReferenceLapStudioTabWidget, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.tab_widget = tab_widget
        self.setMinimumHeight(400)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        self._cursor_dist: float = 0.0
        self._live_car_dist: float = -1.0
        self._is_dragging_cursor = False
        self._dragged_annotation_id: Optional[str] = None
        self._hovered_annotation_id: Optional[str] = None

        # Cached vector geometry for zero-lag rendering
        self._cached_poly_w: float = 0.0
        self._cached_poly_h: float = 0.0
        self._poly_speed = QPolygonF()
        self._poly_throttle = QPolygonF()
        self._poly_brake = QPolygonF()
        self._poly_steering = QPolygonF()
        self._poly_gear = QPolygonF()

    @property
    def cursor_dist(self) -> float:
        return self._cursor_dist

    @cursor_dist.setter
    def cursor_dist(self, dist: float) -> None:
        prof = self.tab_widget.active_profile
        max_dist = prof.track_length if (prof and prof.track_length > 0) else 50000.0
        new_d = max(0.0, min(max_dist, dist))
        if abs(self._cursor_dist - new_d) > 0.01:
            self._cursor_dist = new_d
            self.cursor_moved.emit(self._cursor_dist)
            self.update()

    def set_live_car_distance(self, dist: float) -> None:
        if abs(self._live_car_dist - dist) > 1.0:
            self._live_car_dist = dist
            self.update()

    def invalidate_curves_cache(self) -> None:
        self._cached_poly_w = 0.0
        self._cached_poly_h = 0.0
        self.update()

    # =========================================================================
    # Geometry & Coordinate Projections
    # =========================================================================

    def _dist_to_x(self, dist: float, width: float, track_len: float) -> float:
        if track_len <= 0:
            return 0.0
        margin = 35.0
        drawable_w = width - margin * 2
        return margin + (dist / track_len) * drawable_w

    def _x_to_dist(self, x: float, width: float, track_len: float) -> float:
        if track_len <= 0:
            return 0.0
        margin = 35.0
        drawable_w = width - margin * 2
        ratio = max(0.0, min(1.0, (x - margin) / max(1.0, drawable_w)))
        return ratio * track_len

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.invalidate_curves_cache()

    # =========================================================================
    # Mouse Interaction (Right-Click for Cursor, Left-Click for Markers)
    # =========================================================================

    def contextMenuEvent(self, event) -> None:
        """Prevent standard context menu from opening on right-click cursor scrub."""
        event.accept()

    def mousePressEvent(self, event) -> None:
        prof = self.tab_widget.active_profile
        if not prof or prof.num_points < 2:
            return

        w = float(self.width())
        track_len = prof.track_length if prof.track_length > 0 else (len(prof.t_grid) * prof.spatial_step)
        click_dist = self._x_to_dist(event.position().x(), w, track_len)

        if event.button() == Qt.MouseButton.RightButton:
            # Right Click: Move and Scrub Cursor
            self._is_dragging_cursor = True
            self.cursor_dist = click_dist
            self.update()

        elif event.button() == Qt.MouseButton.LeftButton:
            # Left Click: Select or Drag existing Marker (WITHOUT moving the cursor)
            clicked_ann: Optional[TrackAnnotation] = None
            for ann in prof.annotations:
                ann_x = self._dist_to_x(ann.distance, w, track_len)
                if abs(event.position().x() - ann_x) <= 14.0:
                    clicked_ann = ann
                    break

            if clicked_ann:
                self._dragged_annotation_id = clicked_ann.id
                self.annotation_selected.emit(clicked_ann.id)
                self.update()

    def mouseMoveEvent(self, event) -> None:
        prof = self.tab_widget.active_profile
        if not prof or prof.num_points < 2:
            return

        w = float(self.width())
        track_len = prof.track_length if prof.track_length > 0 else (len(prof.t_grid) * prof.spatial_step)
        dist = self._x_to_dist(event.position().x(), w, track_len)

        if self._dragged_annotation_id:
            # Dragging annotation with Left Click (does not move cursor)
            self.tab_widget.ref_manager.move_annotation(self._dragged_annotation_id, dist, auto_save=False)
            self.tab_widget.refresh_annotations_table()
        elif self._is_dragging_cursor:
            # Scrubbing cursor strictly with Right Click
            self.cursor_dist = dist

        # Hover detection
        prev_hover = self._hovered_annotation_id
        self._hovered_annotation_id = None
        for ann in prof.annotations:
            ann_x = self._dist_to_x(ann.distance, w, track_len)
            if abs(event.position().x() - ann_x) <= 14.0:
                self._hovered_annotation_id = ann.id
                break
        if prev_hover != self._hovered_annotation_id:
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self._is_dragging_cursor = False
        elif event.button() == Qt.MouseButton.LeftButton:
            if self._dragged_annotation_id:
                prof = self.tab_widget.active_profile
                if prof:
                    prof.save_marks_to_file()
                self._dragged_annotation_id = None
                self.tab_widget.refresh_annotations_table()
        self.update()

    # =========================================================================
    # High-Performance Cached Vector Painting
    # =========================================================================

    def _rebuild_curves_cache(self, prof: ReferenceLapProfile, w: float, h: float) -> None:
        margin_x = 35.0
        top_y = 28.0
        bottom_y = h - 22.0
        plot_h = bottom_y - top_y
        plot_w = w - margin_x * 2

        track_len = prof.track_length if prof.track_length > 0.0 else (len(prof.t_grid) * prof.spatial_step)
        max_speed_scale = 360.0

        step_pts = max(1, prof.num_points // int(max(10.0, plot_w)))
        pts_spd: List[QPointF] = []
        pts_thr: List[QPointF] = []
        pts_brk: List[QPointF] = []
        pts_str: List[QPointF] = []
        pts_gear: List[QPointF] = []

        for idx in range(0, prof.num_points, step_pts):
            d = idx * prof.spatial_step
            x = self._dist_to_x(d, w, track_len)

            spd_kmh = (prof.speed_grid[idx] * 3.6) if idx < len(prof.speed_grid) else 0.0
            y_spd = bottom_y - (min(max_speed_scale, spd_kmh) / max_speed_scale) * plot_h
            pts_spd.append(QPointF(x, y_spd))

            thr = prof.throttle_grid[idx] if idx < len(prof.throttle_grid) else 0.0
            y_thr = bottom_y - thr * (plot_h * 0.40)
            pts_thr.append(QPointF(x, y_thr))

            brk = prof.brake_grid[idx] if idx < len(prof.brake_grid) else 0.0
            y_brk = bottom_y - brk * (plot_h * 0.40)
            pts_brk.append(QPointF(x, y_brk))

            steer = prof.steering_grid[idx] if idx < len(prof.steering_grid) else 0.0
            y_str = (bottom_y - (plot_h * 0.20)) - steer * (plot_h * 0.20)
            pts_str.append(QPointF(x, y_str))

            gear = prof.gear_grid[idx] if idx < len(prof.gear_grid) else 0
            y_gear = bottom_y - (gear / 8.0) * (plot_h * 0.30)
            pts_gear.append(QPointF(x, y_gear))

        self._poly_speed = QPolygonF(pts_spd)
        self._poly_throttle = QPolygonF(pts_thr)
        self._poly_brake = QPolygonF(pts_brk)
        self._poly_steering = QPolygonF(pts_str)
        self._poly_gear = QPolygonF(pts_gear)
        self._cached_poly_w = w
        self._cached_poly_h = h

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        w = float(self.width())
        h = float(self.height())
        margin_x = 35.0
        top_y = 28.0
        bottom_y = h - 22.0
        plot_h = bottom_y - top_y
        plot_w = w - margin_x * 2

        # 1. Canvas Background
        painter.fillRect(QRectF(0, 0, w, h), QColor("#090d13"))
        painter.fillRect(QRectF(margin_x, top_y, plot_w, plot_h), QColor("#11161f"))

        prof = self.tab_widget.active_profile
        if not prof or prof.num_points < 2 or not prof.t_grid:
            painter.setPen(QPen(QColor("#6e7681"), 1))
            painter.setFont(QFont("Segoe UI", 12))
            painter.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "No Reference Lap Loaded. Waiting for flying lap on track...")
            painter.end()
            return

        track_len = prof.track_length if prof.track_length > 0.0 else (len(prof.t_grid) * prof.spatial_step)
        if track_len <= 0:
            track_len = 5000.0

        # 2. Sector Background Bands
        s1_d = prof.sector_1_dist if prof.sector_1_dist > 0 else (track_len / 3.0)
        s2_d = prof.sector_2_dist if prof.sector_2_dist > 0 else (track_len * 2.0 / 3.0)

        x_s0 = self._dist_to_x(0.0, w, track_len)
        x_s1 = self._dist_to_x(s1_d, w, track_len)
        x_s2 = self._dist_to_x(s2_d, w, track_len)
        x_s3 = self._dist_to_x(track_len, w, track_len)

        # S1 Band (Cyan)
        painter.fillRect(QRectF(x_s0, top_y, x_s1 - x_s0, plot_h), QColor(0, 180, 255, 22))
        # S2 Band (Purple)
        painter.fillRect(QRectF(x_s1, top_y, x_s2 - x_s1, plot_h), QColor(168, 85, 247, 22))
        # S3 Band (Gold)
        painter.fillRect(QRectF(x_s2, top_y, x_s3 - x_s2, plot_h), QColor(245, 158, 11, 22))

        # Sector boundary vertical dashed lines
        painter.setPen(QPen(QColor("#00d2ff"), 1.0, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(x_s1, top_y), QPointF(x_s1, bottom_y))
        painter.setPen(QPen(QColor("#a855f7"), 1.0, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(x_s2, top_y), QPointF(x_s2, bottom_y))

        # Sector labels at top
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.setPen(QPen(QColor(0, 210, 255, 200), 1))
        painter.drawText(QRectF(x_s0, top_y + 2, x_s1 - x_s0, 16), Qt.AlignmentFlag.AlignCenter, "SECTOR 1")
        painter.setPen(QPen(QColor(168, 85, 247, 200), 1))
        painter.drawText(QRectF(x_s1, top_y + 2, x_s2 - x_s1, 16), Qt.AlignmentFlag.AlignCenter, "SECTOR 2")
        painter.setPen(QPen(QColor(245, 158, 11, 200), 1))
        painter.drawText(QRectF(x_s2, top_y + 2, x_s3 - x_s2, 16), Qt.AlignmentFlag.AlignCenter, "SECTOR 3")

        # 3. Horizontal Grid Lines
        painter.setFont(QFont("Segoe UI", 8))
        grid_speeds = [0, 100, 200, 300]
        max_speed_scale = 360.0
        for spd in grid_speeds:
            y = bottom_y - (spd / max_speed_scale) * plot_h
            painter.setPen(QPen(QColor("#1e2633"), 1, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(margin_x, y), QPointF(w - margin_x, y))
            painter.setPen(QPen(QColor("#8b949e"), 1))
            painter.drawText(QRectF(0, y - 8, margin_x - 4, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{spd}")

        # 4. Check & Rebuild Cached Vector Curves if needed
        if self._cached_poly_w != w or self._cached_poly_h != h:
            self._rebuild_curves_cache(prof, w, h)

        # Draw Cached Curves (Extremely fast, <0.1ms)
        painter.setPen(QPen(QColor("#22c55e"), 1.6))
        painter.drawPolyline(self._poly_throttle)

        painter.setPen(QPen(QColor("#ef4444"), 1.6))
        painter.drawPolyline(self._poly_brake)

        painter.setPen(QPen(QColor(0, 210, 255, 120), 1.0))
        painter.drawPolyline(self._poly_steering)

        painter.setPen(QPen(QColor(255, 255, 255, 150), 1.2))
        painter.drawPolyline(self._poly_gear)

        painter.setPen(QPen(QColor("#facc15"), 2.2))
        painter.drawPolyline(self._poly_speed)

        # 5. Track Annotations & Flags
        for ann in prof.annotations:
            ann_x = self._dist_to_x(ann.distance, w, track_len)
            is_hovered = (self._hovered_annotation_id == ann.id)
            is_selected = (self.tab_widget.selected_annotation_id == ann.id)

            color = QColor("#3b82f6")
            lbl_text = prof.get_annotation_display_label(ann)

            if ann.type == AnnotationType.BRAKE:
                color = QColor("#ef4444")
            elif ann.type == AnnotationType.TURN_IN:
                color = QColor("#f97316")
            elif ann.type == AnnotationType.GEAR:
                color = QColor("#10b981")

            # Vertical marker line
            pen_w = 2.5 if (is_selected or is_hovered) else 1.5
            painter.setPen(QPen(color, pen_w, Qt.PenStyle.SolidLine if is_selected else Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(ann_x, top_y), QPointF(ann_x, bottom_y))

            # Top flag badge
            badge_w = max(40.0, float(len(lbl_text) * 8 + 12))
            badge_h = 19.0
            badge_rect = QRectF(ann_x - badge_w / 2.0, top_y + 3.0, badge_w, badge_h)

            painter.setPen(QPen(QColor("#ffffff") if is_selected else color, 1.5))
            painter.setBrush(QBrush(color.darker(130) if not is_selected else color))
            painter.drawRoundedRect(badge_rect, 4, 4)

            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.setPen(QPen(QColor("#ffffff"), 1))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, lbl_text)

        # 6. Live Car Position Line (Cyan)
        if self._live_car_dist >= 0.0:
            car_x = self._dist_to_x(self._live_car_dist, w, track_len)
            painter.setPen(QPen(QColor("#00e5ff"), 2.2))
            painter.drawLine(QPointF(car_x, top_y), QPointF(car_x, bottom_y))

            car_badge = QRectF(car_x - 24, bottom_y - 16, 48, 14)
            painter.setBrush(QBrush(QColor("#00e5ff")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(car_badge, 3, 3)
            painter.setPen(QPen(QColor("#000000"), 1))
            painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
            painter.drawText(car_badge, Qt.AlignmentFlag.AlignCenter, "CAR")

        # 7. Interactive White Cursor Line
        cursor_x = self._dist_to_x(self._cursor_dist, w, track_len)
        painter.setPen(QPen(QColor("#ffffff"), 2.0))
        painter.drawLine(QPointF(cursor_x, top_y), QPointF(cursor_x, bottom_y))

        tri = QPolygonF([
            QPointF(cursor_x - 5, top_y - 7),
            QPointF(cursor_x + 5, top_y - 7),
            QPointF(cursor_x, top_y + 1),
        ])
        painter.setBrush(QBrush(QColor("#ffffff")))
        painter.drawPolygon(tri)

        # 8. Distance Axis Labels along bottom
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QPen(QColor("#8b949e"), 1))
        dist_steps = 10
        for i in range(dist_steps + 1):
            d_val = (i / dist_steps) * track_len
            x_pos = self._dist_to_x(d_val, w, track_len)
            painter.drawText(QRectF(x_pos - 25, bottom_y + 3, 50, 16), Qt.AlignmentFlag.AlignCenter, f"{int(d_val)}m")

        painter.end()


class ReferenceLapStudioTabWidget(QWidget):
    """
    Reference Lap & Mark Editor Studio Tab with Dominant Graph on Left and Dedicated Vertical Notes Sidebar on Right.
    """

    def __init__(self, plugin: ReferenceLapStudioPlugin, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.plugin = plugin
        self.ref_manager: ReferenceLapManager = plugin.ref_manager
        self.selected_annotation_id: Optional[str] = None
        self._available_files: List[Path] = []

        self._setup_ui()
        self._setup_shortcuts()

        # Connect ReferenceLapManager signals
        self.ref_manager.reference_profile_changed.connect(self._on_profile_changed)
        self.ref_manager.annotations_changed.connect(self._on_annotations_changed)
        self.ref_manager.delta_updated.connect(self._on_delta_updated)

        self._refresh_files_list()
        self.refresh_ui()

    @property
    def active_profile(self) -> Optional[ReferenceLapProfile]:
        return self.ref_manager.get_active_profile()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # ── 1. Compact Header Bar (Strict Fixed Height 44px) ──
        header_frame = QFrame(self)
        header_frame.setFixedHeight(44)
        header_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        header_frame.setStyleSheet("""
            QFrame {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 6px;
            }
        """)
        h_layout = QHBoxLayout(header_frame)
        h_layout.setContentsMargins(8, 4, 8, 4)
        h_layout.setSpacing(8)

        # Profile selection
        h_layout.addWidget(QLabel("🗺️ Ref Lap:", header_frame))
        self.combo_files = QComboBox(header_frame)
        self.combo_files.setFixedHeight(26)
        self.combo_files.setMinimumWidth(220)
        self.combo_files.currentIndexChanged.connect(self._on_file_selected)
        h_layout.addWidget(self.combo_files)

        self.btn_refresh = QPushButton("🔄 Refresh", header_frame)
        self.btn_refresh.setFixedHeight(26)
        self.btn_refresh.clicked.connect(self._refresh_files_list)
        h_layout.addWidget(self.btn_refresh)

        h_layout.addWidget(QLabel("Mode:", header_frame))
        self.combo_mode = QComboBox(header_frame)
        self.combo_mode.setFixedHeight(26)
        for m in DeltaReferenceMode:
            self.combo_mode.addItem(m.value.replace("_", " ").title(), m)
        self.combo_mode.currentIndexChanged.connect(self._on_mode_selected)
        h_layout.addWidget(self.combo_mode)

        h_layout.addSpacing(8)

        # Metrics Badges
        self.lbl_lap_time = QLabel("Lap: --:--.---", header_frame)
        self.lbl_lap_time.setStyleSheet("font-weight: bold; color: #22c55e;")
        h_layout.addWidget(self.lbl_lap_time)

        self.lbl_track_len = QLabel("Len: -- m", header_frame)
        self.lbl_track_len.setStyleSheet("font-weight: bold; color: #facc15;")
        h_layout.addWidget(self.lbl_track_len)

        self.lbl_s1_loop = QLabel("S1: --", header_frame)
        self.lbl_s1_loop.setStyleSheet("color: #00d2ff;")
        h_layout.addWidget(self.lbl_s1_loop)

        self.lbl_s2_loop = QLabel("S2: --", header_frame)
        self.lbl_s2_loop.setStyleSheet("color: #a855f7;")
        h_layout.addWidget(self.lbl_s2_loop)

        self.lbl_num_marks = QLabel("Marks: 0", header_frame)
        self.lbl_num_marks.setStyleSheet("font-weight: bold; color: #f59e0b;")
        h_layout.addWidget(self.lbl_num_marks)

        h_layout.addStretch()

        # Quick action buttons right in header
        self.btn_add_brake = QPushButton("🔴 + Brake [B]", header_frame)
        self.btn_add_brake.setFixedHeight(26)
        self.btn_add_brake.setStyleSheet("background-color: #dc2626; color: white; font-weight: bold; padding: 2px 8px; border-radius: 4px;")
        self.btn_add_brake.clicked.connect(lambda: self.add_marker_at_cursor(AnnotationType.BRAKE))
        h_layout.addWidget(self.btn_add_brake)

        self.btn_add_turn_in = QPushButton("🟠 + Turn-in [I]", header_frame)
        self.btn_add_turn_in.setFixedHeight(26)
        self.btn_add_turn_in.setStyleSheet("background-color: #ea580c; color: white; font-weight: bold; padding: 2px 8px; border-radius: 4px;")
        self.btn_add_turn_in.clicked.connect(lambda: self.add_marker_at_cursor(AnnotationType.TURN_IN))
        h_layout.addWidget(self.btn_add_turn_in)

        self.btn_add_turn = QPushButton("🔵 + Turn [T]", header_frame)
        self.btn_add_turn.setFixedHeight(26)
        self.btn_add_turn.setStyleSheet("background-color: #2563eb; color: white; font-weight: bold; padding: 2px 8px; border-radius: 4px;")
        self.btn_add_turn.clicked.connect(lambda: self.add_marker_at_cursor(AnnotationType.TURN))
        h_layout.addWidget(self.btn_add_turn)

        self.combo_gear = QComboBox(header_frame)
        self.combo_gear.setFixedHeight(26)
        for g in range(1, 9):
            self.combo_gear.addItem(f"G{g}", g)
        self.combo_gear.setCurrentIndex(2)
        h_layout.addWidget(self.combo_gear)

        self.btn_add_gear = QPushButton("🟢 + Gear", header_frame)
        self.btn_add_gear.setFixedHeight(26)
        self.btn_add_gear.setStyleSheet("background-color: #059669; color: white; font-weight: bold; padding: 2px 8px; border-radius: 4px;")
        self.btn_add_gear.clicked.connect(self._cb_add_gear)
        h_layout.addWidget(self.btn_add_gear)

        self.btn_sync_car = QPushButton("🎯 Sync Car [C]", header_frame)
        self.btn_sync_car.setFixedHeight(26)
        self.btn_sync_car.setStyleSheet("background-color: #0891b2; color: white; padding: 2px 8px; border-radius: 4px;")
        self.btn_sync_car.clicked.connect(self._cb_sync_to_car)
        h_layout.addWidget(self.btn_sync_car)

        main_layout.addWidget(header_frame)

        # ── 2. Horizontal Splitter: Dominant Graph on Left & Annotations Table on Right ──
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #30363d;
                width: 4px;
            }
        """)

        # Left Column: Dominant Canvas (Top) + Values Ribbon (Bottom of Graph)
        left_container = QWidget(splitter)
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        # 1. Dominant Graph Canvas (Takes all remaining vertical and horizontal space)
        self.canvas = SpatialTelemetryCanvas(self, left_container)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.cursor_moved.connect(self._on_cursor_moved)
        self.canvas.annotation_selected.connect(self._on_annotation_clicked_on_canvas)
        left_layout.addWidget(self.canvas, 1)

        # 2. Values Ribbon placed AT THE BOTTOM of the graph
        self.readout_ribbon = QFrame(left_container)
        self.readout_ribbon.setFixedHeight(32)
        self.readout_ribbon.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.readout_ribbon.setStyleSheet("background-color: #0d1117; border: 1px solid #21262d; border-radius: 4px; padding: 2px 8px;")
        rib_layout = QHBoxLayout(self.readout_ribbon)
        rib_layout.setContentsMargins(6, 2, 6, 2)
        rib_layout.setSpacing(14)

        self.lbl_cur_dist = QLabel("Cursor: 0.0 m", self.readout_ribbon)
        self.lbl_cur_dist.setStyleSheet("font-weight: bold; color: #ffffff;")
        rib_layout.addWidget(self.lbl_cur_dist)

        self.lbl_cur_sector = QLabel("Sector: S1", self.readout_ribbon)
        self.lbl_cur_sector.setStyleSheet("font-weight: bold; color: #00d2ff;")
        rib_layout.addWidget(self.lbl_cur_sector)

        self.lbl_cur_speed = QLabel("Speed: 0.0 km/h", self.readout_ribbon)
        self.lbl_cur_speed.setStyleSheet("font-weight: bold; color: #facc15;")
        rib_layout.addWidget(self.lbl_cur_speed)

        self.lbl_cur_gear = QLabel("Gear: N", self.readout_ribbon)
        self.lbl_cur_gear.setStyleSheet("font-weight: bold; color: #22c55e;")
        rib_layout.addWidget(self.lbl_cur_gear)

        self.lbl_cur_thr = QLabel("Thr: 0%", self.readout_ribbon)
        self.lbl_cur_thr.setStyleSheet("color: #22c55e;")
        rib_layout.addWidget(self.lbl_cur_thr)

        self.lbl_cur_brk = QLabel("Brk: 0%", self.readout_ribbon)
        self.lbl_cur_brk.setStyleSheet("color: #ef4444;")
        rib_layout.addWidget(self.lbl_cur_brk)

        self.lbl_cur_steer = QLabel("Steer: 0.0%", self.readout_ribbon)
        self.lbl_cur_steer.setStyleSheet("color: #00d2ff;")
        rib_layout.addWidget(self.lbl_cur_steer)

        rib_layout.addStretch()
        left_layout.addWidget(self.readout_ribbon, 0)

        splitter.addWidget(left_container)

        # Right Column: Vertical Track Annotations Table
        table_container = QFrame(splitter)
        table_container.setStyleSheet("background-color: #0d1117; border: 1px solid #21262d; border-radius: 4px;")
        tc_layout = QVBoxLayout(table_container)
        tc_layout.setContentsMargins(6, 6, 6, 6)
        tc_layout.setSpacing(6)

        th_header = QHBoxLayout()
        th_header.addWidget(QLabel("📋 Track Annotations & Pace Notes", table_container))
        th_header.addStretch()
        tc_layout.addLayout(th_header)

        self.table_marks = QTableWidget(table_container)
        self.table_marks.setColumnCount(5)
        self.table_marks.setHorizontalHeaderLabels(["Type", "Label", "Distance", "Audio", "Actions"])
        self.table_marks.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_marks.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_marks.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_marks.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table_marks.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table_marks.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_marks.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_marks.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_marks.itemSelectionChanged.connect(self._on_table_selection_changed)
        tc_layout.addWidget(self.table_marks)

        splitter.addWidget(table_container)
        splitter.setStretchFactor(0, 7)  # 70%+ screen for graph
        splitter.setStretchFactor(1, 3)  # 30% for sidebar

        main_layout.addWidget(splitter)

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("B"), self, lambda: self.add_marker_at_cursor(AnnotationType.BRAKE))
        QShortcut(QKeySequence("I"), self, lambda: self.add_marker_at_cursor(AnnotationType.TURN_IN))
        QShortcut(QKeySequence("T"), self, lambda: self.add_marker_at_cursor(AnnotationType.TURN))
        QShortcut(QKeySequence("Delete"), self, self._cb_delete_selected)
        QShortcut(QKeySequence("Space"), self, self._cb_test_audio)
        QShortcut(QKeySequence("C"), self, self._cb_sync_to_car)

        for g in range(1, 9):
            QShortcut(QKeySequence(str(g)), self, lambda g_val=g: self.add_gear_marker(g_val))

    # =========================================================================
    # Data & UI Refresh Routines
    # =========================================================================

    def _refresh_files_list(self) -> None:
        self.combo_files.blockSignals(True)
        self.combo_files.clear()
        self.combo_files.addItem("(Live Session Reference Lap)", None)

        search_dir = DEFAULT_REF_LAPS_DIR
        if search_dir.exists():
            files = sorted([f for f in search_dir.glob("ref_*.json") if not f.name.endswith(".marks.json")])
            self._available_files = files
            for f in files:
                self.combo_files.addItem(f.name, f)

        self.combo_files.blockSignals(False)

    def refresh_ui(self) -> None:
        prof = self.active_profile
        if prof:
            lap_str = format_lap_time(prof.lap_time) if prof.lap_time > 0 else "--:--.---"
            self.lbl_lap_time.setText(f"Lap Time: {lap_str}")
            self.lbl_track_len.setText(f"Length: {prof.track_length:.0f} m")
            self.lbl_s1_loop.setText(f"S1: {prof.sector_1_dist:.0f} m" if prof.sector_1_dist > 0 else "S1: --")
            self.lbl_s2_loop.setText(f"S2: {prof.sector_2_dist:.0f} m" if prof.sector_2_dist > 0 else "S2: --")
            self.lbl_num_marks.setText(f"Markers: {len(prof.annotations)}")
        else:
            self.lbl_lap_time.setText("Lap Time: --:--.---")
            self.lbl_track_len.setText("Length: -- m")
            self.lbl_s1_loop.setText("S1: --")
            self.lbl_s2_loop.setText("S2: --")
            self.lbl_num_marks.setText("Markers: 0")

        self.refresh_annotations_table()
        self._update_readout(self.canvas.cursor_dist)
        self.canvas.invalidate_curves_cache()

    def refresh_annotations_table(self) -> None:
        prof = self.active_profile
        anns = prof.annotations if prof else []

        self.table_marks.blockSignals(True)
        self.table_marks.setRowCount(len(anns))

        for row, ann in enumerate(anns):
            # 1. Type Badge
            type_item = QTableWidgetItem(ann.type.value.upper())
            type_item.setData(Qt.ItemDataRole.UserRole, ann.id)
            if ann.type == AnnotationType.BRAKE:
                type_item.setForeground(QColor("#ef4444"))
            elif ann.type == AnnotationType.TURN_IN:
                type_item.setForeground(QColor("#f97316"))
            elif ann.type == AnnotationType.GEAR:
                type_item.setForeground(QColor("#10b981"))
            else:
                type_item.setForeground(QColor("#3b82f6"))
            self.table_marks.setItem(row, 0, type_item)

            # 2. Label
            lbl_item = QTableWidgetItem(prof.get_annotation_display_label(ann) if prof else ann.id)
            lbl_item.setData(Qt.ItemDataRole.UserRole, ann.id)
            self.table_marks.setItem(row, 1, lbl_item)

            # 3. Distance Button (Click to Jump Cursor)
            dist_btn = QPushButton(f"{ann.distance:.1f} m")
            dist_btn.setStyleSheet("background-color: #21262d; color: #ffffff; border: 1px solid #30363d; border-radius: 3px; padding: 2px 6px;")
            dist_btn.clicked.connect(lambda _, d=ann.distance, a_id=ann.id: self._jump_to_distance(d, a_id))
            self.table_marks.setCellWidget(row, 2, dist_btn)

            # 4. Audio Phrase Key
            audio_item = QTableWidgetItem(prof.get_annotation_phrase_key(ann) if prof else "lap")
            audio_item.setData(Qt.ItemDataRole.UserRole, ann.id)
            audio_item.setForeground(QColor("#8b949e"))
            self.table_marks.setItem(row, 3, audio_item)

            # 5. Actions Cell: [▶ Play] [✕ Remove]
            action_widget = QWidget()
            aw_layout = QHBoxLayout(action_widget)
            aw_layout.setContentsMargins(2, 2, 2, 2)
            aw_layout.setSpacing(4)

            btn_play = QPushButton("▶")
            btn_play.setFixedSize(26, 22)
            btn_play.setStyleSheet("""
                QPushButton {
                    background-color: #581c87;
                    color: #ffffff;
                    font-size: 11px;
                    font-weight: bold;
                    border: 1px solid #7e22ce;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background-color: #7e22ce;
                    border-color: #a855f7;
                }
                QPushButton:pressed {
                    background-color: #3b0764;
                }
            """)
            btn_play.setToolTip("Play audio cue (Triangle)")
            phrase_key = prof.get_annotation_phrase_key(ann) if prof else "brake"
            btn_play.clicked.connect(lambda _, pk=phrase_key: AudioAnnouncer.play_phrase(pk))
            aw_layout.addWidget(btn_play)

            btn_remove = QPushButton("✕")
            btn_remove.setFixedSize(26, 22)
            btn_remove.setStyleSheet("""
                QPushButton {
                    background-color: #7f1d1d;
                    color: #ffffff;
                    font-size: 12px;
                    font-weight: bold;
                    border: 1px solid #b91c1c;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background-color: #dc2626;
                    border-color: #ef4444;
                }
                QPushButton:pressed {
                    background-color: #450a0a;
                }
            """)
            btn_remove.setToolTip("Remove marker (Cross)")
            btn_remove.clicked.connect(lambda _, a_id=ann.id: self._remove_marker_by_id(a_id))
            aw_layout.addWidget(btn_remove)

            self.table_marks.setCellWidget(row, 4, action_widget)

            if ann.id == self.selected_annotation_id:
                self.table_marks.selectRow(row)

        self.table_marks.blockSignals(False)

    def _jump_to_distance(self, distance: float, ann_id: str) -> None:
        self.selected_annotation_id = ann_id
        self.canvas.cursor_dist = distance

    def _remove_marker_by_id(self, ann_id: str) -> None:
        ok = self.ref_manager.remove_annotation(ann_id)
        if ok:
            if self.selected_annotation_id == ann_id:
                self.selected_annotation_id = None
            self.refresh_ui()

    def _update_readout(self, dist: float) -> None:
        prof = self.active_profile
        vals = prof.get_value_at_dist(dist) if prof else {}
        sec = prof.get_sector_at_dist(dist) if prof else 1

        self.lbl_cur_dist.setText(f"Cursor: {dist:.1f} m")
        self.lbl_cur_sector.setText(f"Sector: S{sec}")
        self.lbl_cur_speed.setText(f"Speed: {vals.get("speed_kmh", 0.0):.1f} km/h")
        g = int(vals.get("gear", 0))
        gear_str = "N" if g == 0 else ("R" if g < 0 else str(g))
        self.lbl_cur_gear.setText(f"Gear: {gear_str}")
        self.lbl_cur_thr.setText(f"Thr: {int(vals.get("throttle", 0.0) * 100)}%")
        self.lbl_cur_brk.setText(f"Brk: {int(vals.get("brake", 0.0) * 100)}%")
        self.lbl_cur_steer.setText(f"Steer: {vals.get("steering", 0.0) * 100:.1f}%")

    # =========================================================================
    # Slot Callbacks & Actions
    # =========================================================================

    def _on_file_selected(self, idx: int) -> None:
        file_path = self.combo_files.currentData()
        if file_path and isinstance(file_path, Path) and file_path.exists():
            loaded = ReferenceLapProfile.load_from_file(file_path)
            if loaded:
                self.ref_manager.delta_engine._all_time_best_profile = loaded
                self.ref_manager.delta_engine._all_time_best_lap_time = loaded.lap_time
                self.ref_manager.delta_engine._apply_active_profile()
                self.refresh_ui()
        else:
            self.ref_manager.delta_engine._apply_active_profile()
            self.refresh_ui()

    def _on_mode_selected(self, idx: int) -> None:
        mode = self.combo_mode.currentData()
        if mode:
            self.ref_manager.set_reference_mode(mode)
            self.refresh_ui()

    def _on_cursor_moved(self, dist: float) -> None:
        self._update_readout(dist)

    def _on_annotation_clicked_on_canvas(self, ann_id: str) -> None:
        self.selected_annotation_id = ann_id
        for row in range(self.table_marks.rowCount()):
            item = self.table_marks.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == ann_id:
                self.table_marks.blockSignals(True)
                self.table_marks.selectRow(row)
                self.table_marks.blockSignals(False)
                break

    def _on_table_selection_changed(self) -> None:
        selected_rows = self.table_marks.selectionModel().selectedRows()
        if selected_rows:
            row = selected_rows[0].row()
            item = self.table_marks.item(row, 0)
            if item:
                ann_id = item.data(Qt.ItemDataRole.UserRole)
                self.selected_annotation_id = ann_id
                self.canvas.update()

    def add_marker_at_cursor(self, ann_type: AnnotationType) -> None:
        prof = self.active_profile
        if not prof:
            QMessageBox.information(self, "No Profile", "Please wait for a reference lap to be loaded before adding annotations.")
            return

        ann = self.ref_manager.add_annotation(ann_type, distance=self.canvas.cursor_dist)
        if ann:
            self.selected_annotation_id = ann.id
            self.refresh_ui()

    def add_gear_marker(self, gear: int) -> None:
        prof = self.active_profile
        if not prof:
            return
        ann = self.ref_manager.add_annotation(AnnotationType.GEAR, distance=self.canvas.cursor_dist, gear=gear)
        if ann:
            self.selected_annotation_id = ann.id
            self.refresh_ui()

    def _cb_add_gear(self) -> None:
        gear = self.combo_gear.currentData() or 3
        self.add_gear_marker(gear)

    def _cb_delete_selected(self) -> None:
        if self.selected_annotation_id:
            self._remove_marker_by_id(self.selected_annotation_id)

    def _cb_test_audio(self) -> None:
        prof = self.active_profile
        if not prof or not self.selected_annotation_id:
            return
        for ann in prof.annotations:
            if ann.id == self.selected_annotation_id:
                phrase = prof.get_annotation_phrase_key(ann)
                logger.info(f"Playing test audio cue: {phrase}")
                try:
                    AudioAnnouncer.play_phrase(phrase)
                except Exception as e:
                    logger.warning(f"Audio playback error: {e}")
                break

    def _cb_sync_to_car(self) -> None:
        car_d = self.ref_manager.delta_engine.last_scoring_dist
        if car_d >= 0.0:
            self.canvas.cursor_dist = car_d

    # =========================================================================
    # Telemetry Updates
    # =========================================================================

    def _on_profile_changed(self, prof: Optional[ReferenceLapProfile]) -> None:
        self.refresh_ui()

    def _on_annotations_changed(self, anns: list) -> None:
        self.refresh_annotations_table()
        self.canvas.update()

    def _on_delta_updated(self, pkt: LapDeltaPacket) -> None:
        if pkt.player_dist >= 0:
            self.canvas.set_live_car_distance(pkt.player_dist)


class ReferenceLapStudioPlugin(SimPadPlugin, ITabProvider, ITelemetrySubscriber, IDeltaSubscriber):
    """
    Reference Lap & Mark Editor Studio Built-in Plugin.
    Provides interactive Studio Tab for reference lap visualization and pace note annotations.
    """

    def __init__(self):
        super().__init__(PluginMetadata(
            id="simpad.builtin.reference_lap_studio",
            name="Reference Lap & Annotations Studio",
            version="2.0.0",
            author="SimPad Team",
            description="Interactive 1m resolution Reference Lap Telemetry Curves Visualizer & Track Annotations Editor (Brake, Turn-in, Turns, Gears).",
            icon="🗺️",
            tags=("reference_lap", "telemetry", "editor", "annotations", "pace_notes")
        ))
        self.ref_manager: ReferenceLapManager = ReferenceLapManager.get_instance()
        self.config: ReferenceLapStudioConfig = ReferenceLapStudioConfig()
        self._active_tab: Optional[ReferenceLapStudioTabWidget] = None

    def on_load(self, context: PluginContext) -> None:
        super().on_load(context)
        self.config = context.get_typed_config(ReferenceLapStudioConfig)

    # ITabProvider
    def get_tab_title(self) -> str:
        return "Reference Lap Studio"

    def get_tab_icon(self) -> str:
        return "🗺️"

    def create_tab_widget(self, parent: Optional[QWidget] = None) -> QWidget:
        self._active_tab = ReferenceLapStudioTabWidget(self, parent)
        return self._active_tab

    # ITelemetrySubscriber
    def on_telemetry_frame(self, sensors: VehicleSensors) -> None:
        pass

    # IDeltaSubscriber
    def on_delta_frame(self, delta_packet: LapDeltaPacket) -> None:
        if self._active_tab and self._active_tab.isVisible():
            self._active_tab.canvas.set_live_car_distance(delta_packet.player_dist)
