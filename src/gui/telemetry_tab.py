"""
SimPad Telemetry & Annotation Studio — Dear PyGui Graphical Tab (UI).
Meter-by-meter telemetry visualization (speed, brake, throttle, steering),
interactive driving annotation management (Brake 'B', Turn-in 'I', Turns 'T', Gear '1'..'8'),
drag & drop positioning, cursor navigation (click / arrow keys), and deletion ('Del').
SOLID architecture.
"""

import time
import math
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import dearpygui.dearpygui as dpg

from src.telemetry.reference_profile import (
    ReferenceLapProfile,
    TrackAnnotation,
    AnnotationType,
    DEFAULT_REF_LAPS_DIR,
    clean_name_identifier,
)
from src.telemetry.lmu_parser import LMUParser
from src.utils.audio import AudioAnnouncer

logger = logging.getLogger(__name__)


class TelemetryTab:
    """
    Telemetry & Track Annotations Tab (Telemetry Studio).
    Displays spatial curves meter-by-meter and enables interactive marker editing.
    """

    def __init__(self):
        self._profile: Optional[ReferenceLapProfile] = None
        self._cursor_distance: float = 0.0
        self._selected_annotation_id: Optional[str] = None
        self._parent_app: Optional[Any] = None
        self._last_loaded_file: Optional[Path] = None
        self._annotation_drag_tags: Dict[str, str] = {}
        self._available_files: List[Path] = []
        self._last_ui_tick: float = 0.0
        self._last_car_pos_tick: float = 0.0
        self._last_known_car_dist: Optional[float] = None
        self._car_track_matches: bool = False

    def build_tab(self, parent_app: Any) -> None:
        """Builds user interface in Telemetry & Annotations tab."""
        self._parent_app = parent_app

        # ── 1. Top toolbar: Profile, Load, Save ─────
        with dpg.child_window(height=54, border=True, tag="child_telem_toolbar"):
            with dpg.group(horizontal=True):
                dpg.add_text("Reference Lap Profile:", color=[0, 210, 255, 255])

                # Profile file selection combo
                dpg.add_combo(
                    items=["(Live Session Reference Lap)"],
                    default_value="(Live Session Reference Lap)",
                    tag="combo_ref_profile_files",
                    width=280,
                    callback=self._cb_select_profile_file,
                )

                dpg.add_button(
                    label="Refresh Files",
                    width=100,
                    callback=self._cb_refresh_profiles_list,
                )

                dpg.add_spacer(width=10)
                dpg.add_text("Auto-Save Marks: ON (.marks.json)", color=[46, 204, 113, 255])

                dpg.add_spacer(width=15)
                dpg.add_text("Lap Time:", color=[180, 180, 180, 255])
                dpg.add_text("--", tag="lbl_telem_lap_time", color=[46, 204, 113, 255])

                dpg.add_spacer(width=15)
                dpg.add_text("Track Length:", color=[180, 180, 180, 255])
                dpg.add_text("--", tag="lbl_telem_track_len", color=[241, 196, 15, 255])

                dpg.add_spacer(width=15)
                dpg.add_text("S1 Loop:", color=[180, 180, 180, 255])
                dpg.add_text("--", tag="lbl_telem_s1_loop", color=[0, 210, 255, 255])

                dpg.add_spacer(width=15)
                dpg.add_text("S2 Loop:", color=[180, 180, 180, 255])
                dpg.add_text("--", tag="lbl_telem_s2_loop", color=[180, 100, 255, 255])

                dpg.add_spacer(width=15)
                dpg.add_text("Markers:", color=[180, 180, 180, 255])
                dpg.add_text("0", tag="lbl_telem_num_markers", color=[255, 200, 0, 255])

        dpg.add_spacer(height=4)

        # ── 2. Quick action toolbar and keyboard shortcuts ──────────────────
        with dpg.child_window(height=46, border=True, tag="child_telem_shortcuts"):
            with dpg.group(horizontal=True):
                dpg.add_text("Add Marker at Cursor:", color=[255, 200, 0, 255])

                dpg.add_button(
                    label="+ Brake [B]",
                    width=105,
                    tag="btn_add_brake",
                    callback=lambda: self.add_annotation_at_cursor(AnnotationType.BRAKE),
                )
                dpg.add_button(
                    label="+ Turn-in [I]",
                    width=115,
                    tag="btn_add_turn_in",
                    callback=lambda: self.add_annotation_at_cursor(AnnotationType.TURN_IN),
                )
                dpg.add_button(
                    label="+ Turn (Auto T1..30) [T]",
                    width=190,
                    tag="btn_add_turn",
                    callback=lambda: self.add_annotation_at_cursor(AnnotationType.TURN),
                )

                # Gear ratio selector
                dpg.add_combo(
                    items=["1", "2", "3", "4", "5", "6", "7", "8"],
                    default_value="3",
                    tag="combo_gear_select",
                    width=45,
                )
                dpg.add_button(
                    label="+ Gear [1-8]",
                    width=100,
                    tag="btn_add_gear",
                    callback=self._cb_add_gear_from_combo,
                )

                dpg.add_spacer(width=15)
                dpg.add_button(
                    label="Delete Marker [Del]",
                    width=165,
                    tag="btn_delete_marker",
                    callback=self._cb_delete_selected_or_nearest,
                )
                dpg.add_button(
                    label="Test Audio",
                    width=90,
                    tag="btn_test_marker_audio",
                    callback=self._cb_test_selected_audio,
                )
                dpg.add_spacer(width=10)
                dpg.add_button(
                    label="Sync to Car [C]",
                    width=135,
                    tag="btn_sync_to_car",
                    callback=self._cb_sync_cursor_to_car,
                )

        dpg.add_spacer(height=4)

        # ── 3. Main Body: Spatial Meter-by-Meter Graph & Side Panel ───
        with dpg.group(horizontal=True):
            # Left Column: Large Spatial Graph (Meter-by-Meter Telemetry)
            with dpg.child_window(width=-360, height=-1, border=True, tag="child_plot_container"):
                with dpg.group(horizontal=True):
                    dpg.add_text("Spatial Telemetry Profile (1m Resolution):", color=[0, 210, 255, 255])
                    dpg.add_spacer(width=15)
                    dpg.add_text("Cursor:", color=[180, 180, 180, 255])
                    dpg.add_text("0.0 m", tag="lbl_hud_cursor_dist", color=[255, 255, 255, 255])
                    dpg.add_text("| Sector:", color=[180, 180, 180, 255])
                    dpg.add_text("S1", tag="lbl_hud_cursor_sector", color=[0, 210, 255, 255])
                    dpg.add_text("| Live Car:", color=[180, 180, 180, 255])
                    dpg.add_text("--", tag="lbl_hud_live_car_dist", color=[0, 220, 255, 255])
                    dpg.add_text("| Speed:", color=[180, 180, 180, 255])
                    dpg.add_text("0.0 km/h", tag="lbl_hud_cursor_speed", color=[241, 196, 15, 255])
                    dpg.add_text("| Gear:", color=[180, 180, 180, 255])
                    dpg.add_text("N", tag="lbl_hud_cursor_gear", color=[46, 204, 113, 255])
                    dpg.add_text("| Thr:", color=[180, 180, 180, 255])
                    dpg.add_text("0 %", tag="lbl_hud_cursor_thr", color=[46, 204, 113, 255])
                    dpg.add_text("| Brk:", color=[180, 180, 180, 255])
                    dpg.add_text("0 %", tag="lbl_hud_cursor_brk", color=[231, 76, 60, 255])
                    dpg.add_text("| Steer:", color=[180, 180, 180, 255])
                    dpg.add_text("0.0 %", tag="lbl_hud_cursor_steer", color=[0, 210, 255, 255])

                # Spatial DPG Graph
                with dpg.plot(
                    no_title=True,
                    height=-1,
                    width=-1,
                    tag="plot_telemetry_studio",
                    crosshairs=True,
                    query=False,
                ):
                    dpg.add_plot_legend()
                    dpg.add_plot_axis(dpg.mvXAxis, label="Track Distance (m)", tag="axis_telem_dist")

                    # Primary Y Axis (Left): Speed (km/h) & Inputs (0-100%)
                    with dpg.plot_axis(dpg.mvYAxis, label="Speed (km/h) / Inputs (%)", tag="axis_telem_y_inputs"):
                        dpg.set_axis_limits("axis_telem_y_inputs", -105, 360)

                        # Background shade areas per sector (shown when S1/S2 recorded)
                        dpg.add_shade_series([], [], y2=[], label="Sector 1", tag="shade_telem_s1", show=False)
                        dpg.add_shade_series([], [], y2=[], label="Sector 2", tag="shade_telem_s2", show=False)
                        dpg.add_shade_series([], [], y2=[], label="Sector 3", tag="shade_telem_s3", show=False)

                        dpg.add_line_series([], [], label="Speed (km/h)", tag="series_telem_speed")
                        dpg.add_line_series([], [], label="Throttle (%)", tag="series_telem_throttle")
                        dpg.add_line_series([], [], label="Brake (%)", tag="series_telem_brake")
                        dpg.add_line_series([], [], label="Steering (%)", tag="series_telem_steering")

                    # Secondary Y Axis (Right): Gear ratios (N, 1..8)
                    with dpg.plot_axis(dpg.mvYAxis2, label="Gear", tag="axis_telem_y_gear"):
                        dpg.set_axis_limits("axis_telem_y_gear", 0, 8.5)
                        dpg.set_axis_ticks("axis_telem_y_gear", (('N', 0), ('1', 1), ('2', 2), ('3', 3), ('4', 4), ('5', 5), ('6', 6), ('7', 7), ('8', 8)))
                        dpg.add_stair_series([], [], label="Gear", tag="series_telem_gear")

                    # Interactive vertical dragline for white edit cursor
                    dpg.add_drag_line(
                        label="Cursor",
                        tag="dragline_telem_cursor",
                        vertical=True,
                        default_value=0.0,
                        color=[255, 255, 255, 255],
                        thickness=2.0,
                        callback=self._cb_cursor_dragged,
                    )

                    # Vertical line for last known car position (Live Car)
                    dpg.add_drag_line(
                        label="Live Car",
                        tag="dragline_telem_live_car",
                        vertical=True,
                        default_value=-999.0,
                        color=[0, 220, 255, 255],
                        thickness=2.5,
                        show=False,
                    )

            # Right Column: Markers Table & Editing
            with dpg.child_window(width=-1, height=-1, border=True, tag="child_markers_table_container"):
                dpg.add_text("Track Annotations & Pace Notes:", color=[255, 200, 0, 255])
                dpg.add_text("CTRL + Click / Drag on graph to move cursor.\nDrag & drop colored markers directly.", color=[180, 180, 180, 255])
                dpg.add_separator()
                dpg.add_spacer(height=4)

                with dpg.table(
                    tag="table_telem_annotations",
                    header_row=True,
                    borders_innerH=True,
                    borders_outerH=True,
                    borders_innerV=True,
                    borders_outerV=True,
                    row_background=True,
                    resizable=True,
                    scrollX=True,
                    scrollY=True,
                    height=-1,
                ):
                    dpg.add_table_column(label="Type", width_fixed=True, init_width_or_weight=65)
                    dpg.add_table_column(label="Label", width_fixed=True, init_width_or_weight=75)
                    dpg.add_table_column(label="Dist (m)", width_fixed=True, init_width_or_weight=70)
                    dpg.add_table_column(label="Audio", width_fixed=True, init_width_or_weight=65)
                    dpg.add_table_column(label="Action", width_fixed=True, init_width_or_weight=65)

        # Background themes for sector zones S1, S2, S3
        if not dpg.does_item_exist("theme_telem_shade_s1"):
            with dpg.theme(tag="theme_telem_shade_s1"):
                with dpg.theme_component(dpg.mvShadeSeries):
                    dpg.add_theme_color(dpg.mvPlotCol_Fill, (0, 180, 255, 30), category=dpg.mvThemeCat_Plots)
                    dpg.add_theme_color(dpg.mvPlotCol_Line, (0, 0, 0, 0), category=dpg.mvThemeCat_Plots)

        if not dpg.does_item_exist("theme_telem_shade_s2"):
            with dpg.theme(tag="theme_telem_shade_s2"):
                with dpg.theme_component(dpg.mvShadeSeries):
                    dpg.add_theme_color(dpg.mvPlotCol_Fill, (175, 95, 245, 30), category=dpg.mvThemeCat_Plots)
                    dpg.add_theme_color(dpg.mvPlotCol_Line, (0, 0, 0, 0), category=dpg.mvThemeCat_Plots)

        if not dpg.does_item_exist("theme_telem_shade_s3"):
            with dpg.theme(tag="theme_telem_shade_s3"):
                with dpg.theme_component(dpg.mvShadeSeries):
                    dpg.add_theme_color(dpg.mvPlotCol_Fill, (255, 175, 0, 25), category=dpg.mvThemeCat_Plots)
                    dpg.add_theme_color(dpg.mvPlotCol_Line, (0, 0, 0, 0), category=dpg.mvThemeCat_Plots)

        if dpg.does_item_exist("shade_telem_s1") and dpg.does_item_exist("theme_telem_shade_s1"):
            dpg.bind_item_theme("shade_telem_s1", "theme_telem_shade_s1")
        if dpg.does_item_exist("shade_telem_s2") and dpg.does_item_exist("theme_telem_shade_s2"):
            dpg.bind_item_theme("shade_telem_s2", "theme_telem_shade_s2")
        if dpg.does_item_exist("shade_telem_s3") and dpg.does_item_exist("theme_telem_shade_s3"):
            dpg.bind_item_theme("shade_telem_s3", "theme_telem_shade_s3")

        # Register keyboard and mouse handlers
        self._setup_key_and_mouse_handlers()

        # Initial profile refresh
        self._refresh_profiles_list()
        self._load_active_profile()

    def _setup_key_and_mouse_handlers(self) -> None:
        """Configures keyboard shortcuts and mouse clicks in Dear PyGui."""
        # 1. Click and drag handler directly on DPG plot
        if dpg.does_item_exist("plot_telemetry_studio"):
            if not dpg.does_item_exist("handler_telem_plot_click"):
                with dpg.item_handler_registry(tag="handler_telem_plot_click"):
                    dpg.add_item_clicked_handler(
                        button=dpg.mvMouseButton_Left,
                        callback=self._cb_plot_clicked,
                    )
                    dpg.add_item_active_handler(
                        callback=self._cb_plot_active,
                    )
            dpg.bind_item_handler_registry("plot_telemetry_studio", "handler_telem_plot_click")

        # 2. Global key handlers
        with dpg.handler_registry():
            # Shortcut B: Brake
            dpg.add_key_release_handler(
                key=dpg.mvKey_B,
                callback=lambda: self.add_annotation_at_cursor(AnnotationType.BRAKE),
            )
            # Shortcut I: Turn-In
            dpg.add_key_release_handler(
                key=dpg.mvKey_I,
                callback=lambda: self.add_annotation_at_cursor(AnnotationType.TURN_IN),
            )
            # Shortcut T: Turn (T1..T30)
            dpg.add_key_release_handler(
                key=dpg.mvKey_T,
                callback=lambda: self.add_annotation_at_cursor(AnnotationType.TURN),
            )
            # Shortcut Del / Backspace: Delete selected or nearest marker
            dpg.add_key_release_handler(
                key=dpg.mvKey_Delete,
                callback=self._cb_delete_selected_or_nearest,
            )
            dpg.add_key_release_handler(
                key=dpg.mvKey_Back,
                callback=self._cb_delete_selected_or_nearest,
            )

            # Numeric shortcuts 1 to 8 for gear ratios
            for gear_num in range(1, 9):
                key_code = getattr(dpg, f"mvKey_{gear_num}", None)
                numpad_code = getattr(dpg, f"mvKey_NumPad{gear_num}", None)
                if key_code is not None:
                    dpg.add_key_release_handler(
                        key=key_code,
                        user_data=gear_num,
                        callback=lambda s, a, u: self.add_annotation_at_cursor(AnnotationType.GEAR, gear=u),
                    )
                if numpad_code is not None:
                    dpg.add_key_release_handler(
                        key=numpad_code,
                        user_data=gear_num,
                        callback=lambda s, a, u: self.add_annotation_at_cursor(AnnotationType.GEAR, gear=u),
                    )

            # Shortcut C: Synchronize editing cursor to car position
            dpg.add_key_release_handler(
                key=dpg.mvKey_C,
                callback=self._cb_sync_cursor_to_car,
            )

            # Navigation arrows to move cursor
            dpg.add_key_down_handler(
                key=dpg.mvKey_Left,
                callback=self._cb_arrow_left,
            )
            dpg.add_key_down_handler(
                key=dpg.mvKey_Right,
                callback=self._cb_arrow_right,
            )

    # ── Cursor & Navigation Management ────────────────────────────────
    def set_cursor_distance(self, distance: float) -> None:
        """Sets cursor position in meters and updates graph and readouts."""
        max_dist = self._get_max_track_dist()
        self._cursor_distance = max(0.0, min(max_dist, distance))

        if dpg.does_item_exist("dragline_telem_cursor"):
            dpg.set_value("dragline_telem_cursor", self._cursor_distance)

        self._update_cursor_hud_readouts()

    def _get_max_track_dist(self) -> float:
        """Returns maximum track distance."""
        if self._profile:
            if self._profile.track_length > 0:
                return self._profile.track_length
            if self._profile.num_points > 0:
                return float(self._profile.num_points * self._profile.spatial_step)
        return 10000.0

    def _update_cursor_hud_readouts(self) -> None:
        """Updates numeric telemetry readouts at cursor position."""
        d_val = self._cursor_distance
        if dpg.does_item_exist("lbl_hud_cursor_dist"):
            dpg.set_value("lbl_hud_cursor_dist", f"{d_val:.1f} m")

        if dpg.does_item_exist("lbl_hud_cursor_sector"):
            if self._profile:
                sec_num = self._profile.get_sector_at_dist(d_val)
                sec_str = f"S{sec_num}"
                sec_color = [0, 210, 255, 255] if sec_num == 1 else ([180, 100, 255, 255] if sec_num == 2 else [241, 196, 15, 255])
                dpg.set_value("lbl_hud_cursor_sector", sec_str)
                dpg.configure_item("lbl_hud_cursor_sector", color=sec_color)
            else:
                dpg.set_value("lbl_hud_cursor_sector", "S1")

        if self._profile:
            vals = self._profile.get_value_at_dist(d_val)
            if dpg.does_item_exist("lbl_hud_cursor_speed"):
                dpg.set_value("lbl_hud_cursor_speed", f"{vals['speed_kmh']:.1f} km/h")
            if dpg.does_item_exist("lbl_hud_cursor_gear"):
                g = int(vals.get("gear", 0))
                gear_str = "R" if g == -1 else ("N" if g == 0 else str(g))
                dpg.set_value("lbl_hud_cursor_gear", gear_str)
            if dpg.does_item_exist("lbl_hud_cursor_thr"):
                dpg.set_value("lbl_hud_cursor_thr", f"{vals['throttle'] * 100.0:.0f} %")
            if dpg.does_item_exist("lbl_hud_cursor_brk"):
                dpg.set_value("lbl_hud_cursor_brk", f"{vals['brake'] * 100.0:.0f} %")
            if dpg.does_item_exist("lbl_hud_cursor_steer"):
                dpg.set_value("lbl_hud_cursor_steer", f"{vals['steering'] * 100.0:.1f} %")

    def _is_ctrl_down(self) -> bool:
        """Checks if CTRL key (left or right) is pressed."""
        try:
            return dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
        except Exception:
            return False

    def _cb_cursor_dragged(self, sender, app_data, user_data):
        """Callback called when manually dragging white cursor line."""
        val = app_data
        if val is None and sender and dpg.does_item_exist(sender):
            val = dpg.get_value(sender)
        if val is not None:
            self.set_cursor_distance(float(val))

    def _cb_plot_clicked(self, sender=None, app_data=None, user_data=None):
        """Moves cursor on CTRL + Left Click on graph."""
        if not self._is_ctrl_down():
            return
        try:
            mouse_pos = dpg.get_plot_mouse_pos()
            if mouse_pos and len(mouse_pos) >= 1:
                self.set_cursor_distance(float(mouse_pos[0]))
        except Exception as e:
            logger.debug(f"[TelemetryTab] Plot click error: {e}")

    def _cb_plot_active(self, sender=None, app_data=None, user_data=None):
        """Moves cursor live on CTRL + Click-Drag on graph."""
        if not self._is_ctrl_down():
            return
        try:
            if dpg.is_mouse_button_down(dpg.mvMouseButton_Left):
                mouse_pos = dpg.get_plot_mouse_pos()
                if mouse_pos and len(mouse_pos) >= 1:
                    self.set_cursor_distance(float(mouse_pos[0]))
        except Exception as e:
            logger.debug(f"[TelemetryTab] Plot active drag error: {e}")

    def _cb_arrow_left(self, sender=None, app_data=None, user_data=None):
        """Moves cursor to left (-1m)."""
        self.set_cursor_distance(self._cursor_distance - 1.0)

    def _cb_arrow_right(self, sender=None, app_data=None, user_data=None):
        """Moves cursor to right (+1m)."""
        self.set_cursor_distance(self._cursor_distance + 1.0)

    def _cb_sync_cursor_to_car(self, sender=None, app_data=None, user_data=None):
        """Positions white edit cursor exactly at active/last known car location."""
        if self._last_known_car_dist is not None and self._car_track_matches:
            self.set_cursor_distance(self._last_known_car_dist)

    def _sync_profile_to_engine(self) -> None:
        """Immediately synchronizes active profile with DeltaEngine and RaceEngineer (PaceNotesRole)."""
        if not self._profile:
            return

        # 1. Update DeltaEngine
        delta_eng = getattr(LMUParser, "_delta_engine", None)
        if delta_eng:
            delta_eng.set_reference_profile(self._profile)

        # 2. Update and reset RaceEngineer PaceNotesRole
        if self._parent_app and hasattr(self._parent_app, "_race_engineer") and self._parent_app._race_engineer:
            pace_role = self._parent_app._race_engineer.get_role("pace_notes")
            if pace_role and hasattr(pace_role, "set_reference_profile"):
                pace_role.set_reference_profile(self._profile)

    # ── Marker Adding & Manipulation ─────────────────────────────────
    def add_annotation_at_cursor(
        self,
        ann_type: AnnotationType,
        gear: Optional[int] = None,
        label: Optional[str] = None,
    ) -> Optional[TrackAnnotation]:
        """Adds annotation at current cursor distance and saves it."""
        if not self._profile:
            # Create temporary default profile if missing
            self._profile = ReferenceLapProfile(
                track_name="Active Session Track",
                track_length=max(1000.0, self._cursor_distance + 500.0),
            )

        ann = self._profile.add_annotation(
            ann_type=ann_type,
            distance=self._cursor_distance,
            gear=gear,
            label=label,
            auto_save=True,
        )
        self._selected_annotation_id = ann.id

        # Update GUI
        self._render_markers_on_plot()
        self._render_markers_table()
        self._update_header_stats()

        # Synchronize immediately with DeltaEngine and RaceEngineer
        self._sync_profile_to_engine()

        # Pronounce marker immediately for user audio feedback
        phrase = self._profile.get_annotation_phrase_key(ann)
        AudioAnnouncer.play_phrase(phrase)

        return ann

    def _cb_add_gear_from_combo(self, sender=None, app_data=None):
        """Adds gear marker from value selected in combo box."""
        val_str = dpg.get_value("combo_gear_select") if dpg.does_item_exist("combo_gear_select") else "3"
        try:
            g_num = int(val_str)
        except ValueError:
            g_num = 3
        self.add_annotation_at_cursor(AnnotationType.GEAR, gear=g_num)

    def _cb_marker_dragged(self, sender, app_data, user_data):
        """Callback triggered when drag & dropping an annotation line."""
        ann_id = user_data
        if not self._profile:
            return

        val = app_data
        if val is None and sender and dpg.does_item_exist(sender):
            val = dpg.get_value(sender)

        if val is None:
            return

        new_dist = float(val)
        max_dist = self._get_max_track_dist()
        new_dist = max(0.0, min(max_dist, new_dist))

        # Update distance and automatically persist to .marks.json
        self._profile.move_annotation(ann_id, new_dist, auto_save=True)
        self._selected_annotation_id = ann_id
        self._cursor_distance = new_dist

        # Recalculate turn numbers and refresh table and labels
        self._update_marker_drag_line_labels()
        self._render_markers_table()
        self._update_cursor_hud_readouts()

        # Synchronize immediately with Race Engineer
        self._sync_profile_to_engine()

    def _cb_delete_selected_or_nearest(self, sender=None, app_data=None, user_data=None):
        """Deletes selected marker or nearest marker to cursor."""
        if not self._profile or not self._profile.annotations:
            return

        target_id = self._selected_annotation_id
        if not target_id:
            # Search nearest marker to cursor (within 25m)
            closest_ann = None
            min_dist = 25.0
            for a in self._profile.annotations:
                d = abs(a.distance - self._cursor_distance)
                if d < min_dist:
                    min_dist = d
                    closest_ann = a
            if closest_ann:
                target_id = closest_ann.id

        if target_id:
            self._profile.remove_annotation(target_id, auto_save=True)
            self._selected_annotation_id = None
            self._render_markers_on_plot()
            self._render_markers_table()
            self._update_header_stats()
            self._sync_profile_to_engine()

    def _cb_test_selected_audio(self, sender=None, app_data=None):
        """Plays audio sound for currently selected or nearest annotation."""
        if not self._profile or not self._profile.annotations:
            return
        target_ann = None
        for a in self._profile.annotations:
            if a.id == self._selected_annotation_id:
                target_ann = a
                break
        if not target_ann and self._profile.annotations:
            target_ann = self._profile.annotations[0]

        if target_ann:
            phrase = self._profile.get_annotation_phrase_key(target_ann)
            AudioAnnouncer.play_phrase(phrase)

    # ── Visual Rendering: Drag & Drop Lines on Plot ────────────────────
    def _get_marker_color(self, ann: TrackAnnotation) -> List[int]:
        """Returns distinctive color by annotation type."""
        if ann.color:
            return ann.color
        if ann.type == AnnotationType.BRAKE:
            return [231, 76, 60, 255]      # Bright red
        elif ann.type == AnnotationType.TURN_IN:
            return [241, 196, 15, 255]     # Golden yellow
        elif ann.type == AnnotationType.TURN:
            return [230, 126, 34, 255]     # Orange
        elif ann.type == AnnotationType.GEAR:
            return [46, 204, 113, 255]     # Emerald green
        return [200, 200, 200, 255]

    def _render_markers_on_plot(self) -> None:
        """Re-creates all interactive drag lines on DPG plot."""
        if not dpg.does_item_exist("plot_telemetry_studio"):
            return

        # 1. Delete old user annotation lines
        for tag in list(self._annotation_drag_tags.values()):
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)
        self._annotation_drag_tags.clear()

        if not self._profile or not self._profile.annotations:
            return

        for ann in self._profile.annotations:
            tag = f"dragline_ann_{ann.id}"
            label = self._profile.get_annotation_display_label(ann)
            color = self._get_marker_color(ann)

            dpg.add_drag_line(
                parent="plot_telemetry_studio",
                tag=tag,
                label=f"{label} ({ann.distance:.0f}m)",
                vertical=True,
                default_value=ann.distance,
                color=color,
                thickness=2.0,
                user_data=ann.id,
                callback=self._cb_marker_dragged,
            )
            self._annotation_drag_tags[ann.id] = tag

    def _update_marker_drag_line_labels(self) -> None:
        """Updates marker line labels after repositioning (recalculated T1..T30)."""
        if not self._profile:
            return
        for ann in self._profile.annotations:
            tag = self._annotation_drag_tags.get(ann.id)
            if tag and dpg.does_item_exist(tag):
                label = self._profile.get_annotation_display_label(ann)
                dpg.configure_item(tag, label=f"{label} ({ann.distance:.0f}m)")

    # ── Visual Rendering: Side Annotations Table ────────────────────────
    def _render_markers_table(self) -> None:
        """Regenerates annotation table rows."""
        if not dpg.does_item_exist("table_telem_annotations"):
            return

        # Delete previous rows
        children = dpg.get_item_children("table_telem_annotations", 1)
        if children:
            for child in children:
                dpg.delete_item(child)

        if not self._profile or not self._profile.annotations:
            return

        for ann in self._profile.annotations:
            label = self._profile.get_annotation_display_label(ann)
            phrase = self._profile.get_annotation_phrase_key(ann)
            color = self._get_marker_color(ann)

            with dpg.table_row(parent="table_telem_annotations"):
                # Type with color badge
                dpg.add_text(ann.type.value.upper(), color=color)

                # Label (e.g. T1, Brake, Gear 3)
                dpg.add_text(label, color=[255, 255, 255, 255])

                # Distance
                dpg.add_button(
                    label=f"{ann.distance:.1f} m",
                    user_data=ann.distance,
                    callback=lambda s, a, u: self.set_cursor_distance(u),
                )

                # Audio phrase
                dpg.add_text(phrase, color=[180, 180, 180, 255])

                # Action buttons (Audio / Delete)
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        label="▶",
                        width=22,
                        user_data=phrase,
                        callback=lambda s, a, u: AudioAnnouncer.play_phrase(u),
                    )
                    dpg.add_button(
                        label="X",
                        width=22,
                        user_data=ann.id,
                        callback=self._cb_delete_row,
                    )

    def _cb_delete_row(self, sender, app_data, user_data):
        """Deletes a row from table X button."""
        ann_id = user_data
        if self._profile:
            self._profile.remove_annotation(ann_id, auto_save=True)
            self._render_markers_on_plot()
            self._render_markers_table()
            self._update_header_stats()
            self._sync_profile_to_engine()

    # ── Loading, Auto-Save & Profiles ─────────────────────────
    def _refresh_profiles_list(self) -> None:
        """Scans profiles/ref_laps folder and populates combo box with lap times."""
        DEFAULT_REF_LAPS_DIR.mkdir(parents=True, exist_ok=True)
        files = [f for f in DEFAULT_REF_LAPS_DIR.glob("*.json") if not f.name.endswith(".marks.json")]
        self._available_files = files
        self._profile_file_map: Dict[str, Optional[Path]] = {}

        delta_eng = getattr(LMUParser, "_delta_engine", None)
        live_time_str = ""
        if delta_eng and 0.0 < delta_eng.ref_lap_time < 90000.0:
            lt = delta_eng.ref_lap_time
            mins = int(lt // 60)
            secs = lt % 60.0
            live_time_str = f" [{mins}:{secs:06.3f}]" if mins > 0 else f" [{secs:.3f}s]"

        live_label = f"(Live Session Reference Lap){live_time_str}"
        items = [live_label]
        self._profile_file_map[live_label] = None
        self._profile_file_map["(Live Session Reference Lap)"] = None

        for f in sorted(files, key=lambda x: x.name):
            lap_t_str = ""
            try:
                import json
                with open(f, "r", encoding="utf-8") as fp:
                    meta = json.load(fp)
                    lt = float(meta.get("lap_time", 0.0))
                    if 0.0 < lt < 90000.0:
                        mins = int(lt // 60)
                        secs = lt % 60.0
                        lap_t_str = f" [{mins}:{secs:06.3f}]" if mins > 0 else f" [{secs:.3f}s]"
            except Exception:
                pass
            item_lbl = f"{f.name}{lap_t_str}"
            items.append(item_lbl)
            self._profile_file_map[item_lbl] = f
            self._profile_file_map[f.name] = f

        if dpg.does_item_exist("combo_ref_profile_files"):
            dpg.configure_item("combo_ref_profile_files", items=items)

    def _cb_refresh_profiles_list(self, sender=None, app_data=None):
        self._refresh_profiles_list()

    def _cb_select_profile_file(self, sender, app_data):
        """Loads selected profile from disk or active session."""
        if not app_data:
            return

        target_file = getattr(self, "_profile_file_map", {}).get(app_data)
        if target_file is None:
            for k, v in getattr(self, "_profile_file_map", {}).items():
                if app_data == k or app_data.startswith(k) or (isinstance(k, str) and k.startswith(app_data)):
                    target_file = v
                    break

        if target_file is None or app_data.startswith("(Live Session Reference Lap)"):
            self._load_active_profile()
            return

        loaded = ReferenceLapProfile.load_from_file(target_file)
        if loaded:
            self._profile = loaded
            self._last_loaded_file = target_file
            self._sync_profile_to_engine()
            self._update_all_ui()

    def _load_active_profile(self) -> None:
        """Loads in-memory reference profile from DeltaEngine."""
        delta_eng = getattr(LMUParser, "_delta_engine", None)
        active_prof = delta_eng.get_reference_profile() if delta_eng else None
        if not active_prof and delta_eng:
            active_prof = delta_eng.all_time_best_profile or delta_eng.current_profile

        if active_prof:
            self._profile = active_prof
        elif delta_eng and delta_eng._ref_t_grid:
            # Create a ReferenceLapProfile from DeltaEngine fields
            num_pts = delta_eng._ref_num_points
            self._profile = ReferenceLapProfile(
                track_name=delta_eng._track_name,
                vehicle_name=delta_eng._vehicle_name,
                vehicle_class=delta_eng._vehicle_class,
                lap_time=delta_eng.ref_lap_time,
                track_length=delta_eng._track_length,
                spatial_step=delta_eng._ref_spatial_step,
                num_points=num_pts,
                t_grid=delta_eng._ref_t_grid or [],
                sector_1_dist=delta_eng.sector_1_dist,
                sector_2_dist=delta_eng.sector_2_dist,
                sector_1_time=delta_eng.sector_1_time,
                sector_2_time=delta_eng.sector_2_time,
            )
            self._sync_profile_to_engine()
        self._update_all_ui()

    def _update_all_ui(self) -> None:
        """Refreshes all plots, tables, and labels in the tab."""
        self._render_curves()
        self._render_markers_on_plot()
        self._render_markers_table()
        self._update_header_stats()
        self._update_cursor_hud_readouts()

    def _update_header_stats(self) -> None:
        """Updates header statistics (Lap Time, Length, Loops S1/S2, Markers Count)."""
        delta_eng = getattr(LMUParser, "_delta_engine", None)

        lt = 0.0
        if self._profile and 0.0 < self._profile.lap_time < 90000.0:
            lt = self._profile.lap_time
        elif delta_eng and 0.0 < delta_eng.ref_lap_time < 90000.0:
            lt = delta_eng.ref_lap_time

        if dpg.does_item_exist("lbl_telem_lap_time"):
            if 0.0 < lt < 90000.0:
                mins = int(lt // 60)
                secs = lt % 60.0
                dpg.set_value("lbl_telem_lap_time", f"{mins}:{secs:06.3f}" if mins > 0 else f"{secs:.3f}s")
            else:
                dpg.set_value("lbl_telem_lap_time", "--")

        if dpg.does_item_exist("lbl_telem_track_len"):
            tl = self._profile.track_length if self._profile else (delta_eng.track_length if delta_eng else 0.0)
            dpg.set_value("lbl_telem_track_len", f"{tl:.0f} m" if tl > 0 else "--")

        if dpg.does_item_exist("lbl_telem_s1_loop"):
            s1 = self._profile.sector_1_dist if self._profile else (delta_eng.sector_1_dist if delta_eng else 0.0)
            t1 = self._profile.sector_1_time if self._profile else (delta_eng.sector_1_time if delta_eng else 0.0)
            if s1 > 0.0:
                lbl_s1 = f"{s1:.0f} m" + (f" ({t1:.2f}s)" if t1 > 0.0 else "")
                dpg.set_value("lbl_telem_s1_loop", lbl_s1)
            else:
                dpg.set_value("lbl_telem_s1_loop", "--")

        if dpg.does_item_exist("lbl_telem_s2_loop"):
            s2 = self._profile.sector_2_dist if self._profile else (delta_eng.sector_2_dist if delta_eng else 0.0)
            t2 = self._profile.sector_2_time if self._profile else (delta_eng.sector_2_time if delta_eng else 0.0)
            if s2 > 0.0:
                lbl_s2 = f"{s2:.0f} m" + (f" ({t2:.2f}s)" if t2 > 0.0 else "")
                dpg.set_value("lbl_telem_s2_loop", lbl_s2)
            else:
                dpg.set_value("lbl_telem_s2_loop", "--")

        if dpg.does_item_exist("lbl_telem_num_markers"):
            num_marks = len(self._profile.annotations) if (self._profile and self._profile.annotations) else 0
            dpg.set_value("lbl_telem_num_markers", str(num_marks))

    def _render_curves(self) -> None:
        """Injects meter-by-meter point series into DPG plot."""
        if not self._profile or self._profile.num_points < 2:
            return

        num_pts = self._profile.num_points
        step = self._profile.spatial_step
        x_dist = [i * step for i in range(num_pts)]

        # 0. Background shade areas per sector (shown when S1 and S2 loops are recorded)
        s1_dist = self._profile.sector_1_dist if self._profile else 0.0
        s2_dist = self._profile.sector_2_dist if self._profile else 0.0
        max_x = x_dist[-1] if x_dist else (self._profile.track_length if self._profile else 0.0)
        y_min = -105.0
        y_max = 360.0

        if s1_dist > 0.0:
            if dpg.does_item_exist("shade_telem_s1"):
                dpg.configure_item("shade_telem_s1", show=True)
                dpg.set_value("shade_telem_s1", [[0.0, s1_dist], [y_min, y_min], [y_max, y_max]])
        else:
            if dpg.does_item_exist("shade_telem_s1"):
                dpg.configure_item("shade_telem_s1", show=False)

        if s1_dist > 0.0 and s2_dist > s1_dist:
            if dpg.does_item_exist("shade_telem_s2"):
                dpg.configure_item("shade_telem_s2", show=True)
                dpg.set_value("shade_telem_s2", [[s1_dist, s2_dist], [y_min, y_min], [y_max, y_max]])
        else:
            if dpg.does_item_exist("shade_telem_s2"):
                dpg.configure_item("shade_telem_s2", show=False)

        if s2_dist > 0.0 and max_x > s2_dist:
            if dpg.does_item_exist("shade_telem_s3"):
                dpg.configure_item("shade_telem_s3", show=True)
                dpg.set_value("shade_telem_s3", [[s2_dist, max_x], [y_min, y_min], [y_max, y_max]])
        else:
            if dpg.does_item_exist("shade_telem_s3"):
                dpg.configure_item("shade_telem_s3", show=False)

        # 1. Speed in km/h
        if self._profile.speed_grid and len(self._profile.speed_grid) == num_pts:
            speed_kmh = [v * 3.6 for v in self._profile.speed_grid]
        else:
            speed_kmh = [0.0] * num_pts

        # 2. Gear ratio
        if self._profile.gear_grid and len(self._profile.gear_grid) == num_pts:
            gear_data = [float(g) for g in self._profile.gear_grid]
        else:
            gear_data = [0.0] * num_pts

        # 3. Throttle (0 - 100%)
        if self._profile.throttle_grid and len(self._profile.throttle_grid) == num_pts:
            thr_pct = [t * 100.0 for t in self._profile.throttle_grid]
        else:
            thr_pct = [0.0] * num_pts

        # 4. Brake (0 - 100%)
        if self._profile.brake_grid and len(self._profile.brake_grid) == num_pts:
            brk_pct = [b * 100.0 for b in self._profile.brake_grid]
        else:
            brk_pct = [0.0] * num_pts

        # 5. Steering (-100% to +100%)
        if self._profile.steering_grid and len(self._profile.steering_grid) == num_pts:
            steer_pct = [s * 100.0 for s in self._profile.steering_grid]
        else:
            steer_pct = [0.0] * num_pts

        if dpg.does_item_exist("series_telem_speed"):
            dpg.set_value("series_telem_speed", [x_dist, speed_kmh])
        if dpg.does_item_exist("series_telem_gear"):
            dpg.set_value("series_telem_gear", [x_dist, gear_data])
        if dpg.does_item_exist("series_telem_throttle"):
            dpg.set_value("series_telem_throttle", [x_dist, thr_pct])
        if dpg.does_item_exist("series_telem_brake"):
            dpg.set_value("series_telem_brake", [x_dist, brk_pct])
        if dpg.does_item_exist("series_telem_steering"):
            dpg.set_value("series_telem_steering", [x_dist, steer_pct])

        if dpg.does_item_exist("axis_telem_dist") and len(x_dist) >= 2:
            dpg.set_axis_limits("axis_telem_dist", x_dist[0], x_dist[-1])

    # ── Periodic Refresh (UI Tick) ────────────────────────────────
    def render_tick(self) -> None:
        """Periodic update: live car position (20 Hz) and reference profile (1 Hz)."""
        now = time.time()

        # 1. Update car position on plot (20 Hz)
        if (now - self._last_car_pos_tick) >= 0.05:
            self._last_car_pos_tick = now
            self._update_live_car_position()

        # 2. Reference profile synchronization (1 Hz)
        if (now - self._last_ui_tick) >= 1.0:
            self._last_ui_tick = now
            delta_eng = getattr(LMUParser, "_delta_engine", None)
            active_prof = delta_eng.get_reference_profile() if delta_eng else None
            if not active_prof and delta_eng:
                active_prof = delta_eng.all_time_best_profile or delta_eng.current_profile
            if active_prof:
                if (
                    self._profile is None
                    or active_prof.lap_time != self._profile.lap_time
                    or active_prof.track_name != self._profile.track_name
                ):
                    self._profile = active_prof
                    self._update_all_ui()
            self._update_header_stats()

    def _update_live_car_position(self) -> None:
        """Updates cyan live car cursor if current track matches."""
        delta_eng = getattr(LMUParser, "_delta_engine", None)
        if not delta_eng:
            return

        session_track = delta_eng.track_name
        tracks_match = False
        if self._profile and self._profile.track_name and session_track:
            tracks_match = (clean_name_identifier(self._profile.track_name) == clean_name_identifier(session_track))

        self._car_track_matches = tracks_match
        if tracks_match:
            car_dist = delta_eng.get_live_car_distance()
            self._last_known_car_dist = car_dist

            if dpg.does_item_exist("dragline_telem_live_car"):
                dpg.configure_item(
                    "dragline_telem_live_car",
                    show=True,
                    default_value=car_dist,
                    label=f"Live Car ({car_dist:.0f}m)",
                )
            if dpg.does_item_exist("lbl_hud_live_car_dist"):
                dpg.set_value("lbl_hud_live_car_dist", f"{car_dist:.1f} m")
        else:
            self._last_known_car_dist = None
            if dpg.does_item_exist("dragline_telem_live_car"):
                dpg.configure_item("dragline_telem_live_car", show=False)
            if dpg.does_item_exist("lbl_hud_live_car_dist"):
                dpg.set_value("lbl_hud_live_car_dist", "--")
