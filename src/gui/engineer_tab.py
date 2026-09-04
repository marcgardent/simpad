"""
SimPad Race Engineer — Dear PyGui Graphical Tab (UI).
Allows enabling/disabling roles, reordering priorities,
visualizing real-time IDLE/BUSY status, and monitoring traffic radar.
"""

import time
import logging
from typing import Optional, Dict, Any, List
import dearpygui.dearpygui as dpg

from src.engineer.manager import RaceEngineer
from src.engineer.base import BaseRole, RoleStatus
from src.engineer.params import RoleParam, BoolParam, IntRangeParam, FloatRangeParam
from src.engineer.roles.traffic_spotter import TrafficSpotterRole, TrafficSpotterState
from src.utils.audio import AudioAnnouncer

logger = logging.getLogger(__name__)


class RaceEngineerTab:
    """
    GUI manager tab dedicated to Virtual Race Engineer.
    Supports dynamic configuration, priority sorting by buttons,
    individual role toggling, parameter form editing, and real-time visualization.
    """

    def __init__(self, race_engineer: RaceEngineer):
        self.engineer = race_engineer
        self._last_ui_refresh: float = 0.0
        self._parent_app: Optional[Any] = None

    def build_tab(self, parent_app: Any) -> None:
        """Builds Dear PyGui interface in Race Engineer tab."""
        self._parent_app = parent_app

        # ── 1. Header & Master Controls ────────────────────────────────────
        with dpg.child_window(height=52, border=True):
            with dpg.group(horizontal=True):
                dpg.add_text("Race Engineer Master:", color=[0, 210, 255, 255])
                dpg.add_checkbox(
                    label="Enabled",
                    tag="chk_engineer_master_enabled",
                    default_value=self.engineer.enabled,
                    callback=self._cb_toggle_master_enabled,
                )

                dpg.add_spacer(width=20)
                dpg.add_text("Audio Output:", color=[180, 180, 180, 255])
                dpg.add_checkbox(
                    label="Mute Voice",
                    tag="chk_engineer_mute_voice",
                    default_value=AudioAnnouncer.is_muted(),
                    callback=self._cb_toggle_mute,
                )

                dpg.add_spacer(width=20)
                dpg.add_text("Global Status:", color=[180, 180, 180, 255])
                dpg.add_text("STANDBY (All roles IDLE)", tag="lbl_engineer_global_status", color=[46, 204, 113, 255])

                dpg.add_spacer(width=20)
                dpg.add_button(
                    label="Save Config",
                    width=90,
                    callback=self._cb_save_config,
                )
                dpg.add_button(
                    label="Test Voice",
                    width=85,
                    callback=self._cb_test_voice,
                )
                dpg.add_button(
                    label="Reset Roles",
                    width=85,
                    callback=self._cb_reset_roles,
                )

        dpg.add_spacer(height=6)

        # ── 2. Main Body: Roles List & Radar ─────────────────────
        with dpg.group(horizontal=True):
            # Left Column: Role Management (Priorities & Parameters)
            with dpg.child_window(width=720, height=-1, border=True, tag="child_roles_container"):
                dpg.add_text("Active Roles & Priority Queue (Sortable):", color=[255, 200, 0, 255])
                dpg.add_text("Check/uncheck roles. Use ▲ and ▼ to reorder priorities.", color=[150, 150, 150, 255])
                dpg.add_separator()
                dpg.add_spacer(height=6)

                with dpg.group(tag="group_roles_list"):
                    self._render_roles_cards()

            # Right Column: Traffic Radar & Live Diagnostics
            with dpg.child_window(width=-1, height=-1, border=True, tag="child_radar_container"):
                dpg.add_text("Live Spotter Radar & Opponent Tracking:", color=[0, 210, 255, 255])
                dpg.add_text("Monitoring nearby vehicles, speed delta, and TTC.", color=[150, 150, 150, 255])
                dpg.add_separator()
                dpg.add_spacer(height=6)

                with dpg.child_window(height=180, border=True, tag="child_spotter_diagnostics"):
                    dpg.add_text("Spotter State Machine Diagnostics:", color=[255, 200, 0, 255])
                    dpg.add_text("FSM State: IDLE", tag="lbl_spotter_fsm_state", color=[46, 204, 113, 255])
                    dpg.add_text("Locked Target: None", tag="lbl_spotter_target", color=[220, 220, 220, 255])
                    dpg.add_text("Live TTC: --", tag="lbl_spotter_ttc", color=[220, 220, 220, 255])
                    dpg.add_text("Relative Distance: --", tag="lbl_spotter_dist", color=[220, 220, 220, 255])
                    dpg.add_text("Speed Delta: --", tag="lbl_spotter_delta_speed", color=[220, 220, 220, 255])

                dpg.add_spacer(height=8)
                dpg.add_text("Opponents on Track (Closest):", color=[255, 200, 0, 255])
                with dpg.table(
                    tag="table_radar_opponents",
                    header_row=True,
                    borders_innerH=True,
                    borders_outerH=True,
                    borders_innerV=True,
                    borders_outerV=True,
                    row_background=True,
                    height=260,
                ):
                    dpg.add_table_column(label="Driver", width_fixed=True, init_width_or_weight=140)
                    dpg.add_table_column(label="Car / Class", width_fixed=True, init_width_or_weight=130)
                    dpg.add_table_column(label="Dist (m)", width_fixed=True, init_width_or_weight=75)
                    dpg.add_table_column(label="Speed", width_fixed=True, init_width_or_weight=75)
                    dpg.add_table_column(label="TTC (s)", width_fixed=True, init_width_or_weight=70)

    def _render_roles_cards(self) -> None:
        """Regenerates the list of role cards with parameter forms."""
        if dpg.does_item_exist("group_roles_list"):
            dpg.delete_item("group_roles_list", children_only=True)

        roles = self.engineer.get_roles()

        for idx, role in enumerate(roles):
            role_id = role.role_id
            card_tag = f"card_role_{role_id}"

            with dpg.child_window(parent="group_roles_list", tag=card_tag, auto_resize_y=True, border=True):
                # Row 1: UP/DOWN buttons, Priority, Active Checkbox, Name, Status Badge
                with dpg.group(horizontal=True):
                    # Single activation checkbox
                    dpg.add_checkbox(
                        label="",
                        tag=f"chk_role_{role_id}",
                        default_value=role.enabled,
                        user_data=role_id,
                        callback=self._cb_toggle_role,
                    )
                    with dpg.tooltip(f"chk_role_{role_id}"):
                        dpg.add_text(f"Enable / Disable role {role.name}")

                    dpg.add_spacer(width=2)

                    # UP Button
                    dpg.add_button(
                        label="▲",
                        width=26,
                        user_data=role_id,
                        callback=self._cb_move_role_up,
                        enabled=(idx > 0),
                    )
                    # DOWN Button
                    dpg.add_button(
                        label="▼",
                        width=26,
                        user_data=role_id,
                        callback=self._cb_move_role_down,
                        enabled=(idx < len(roles) - 1),
                    )

                    dpg.add_spacer(width=4)

                    # Priority
                    prio_color = [255, 200, 0, 255] if role.priority >= 100 else [180, 180, 180, 255]
                    dpg.add_text(f"[{role.priority:3d}]", tag=f"lbl_prio_{role_id}", color=prio_color)

                    dpg.add_spacer(width=4)

                    # Role name
                    name_color = [0, 210, 255, 255] if role.enabled else [120, 120, 120, 255]
                    dpg.add_text(f"{role.name}", tag=f"lbl_name_{role_id}", color=name_color)

                    dpg.add_spacer(width=10)
                    # Status badge IDLE / BUSY / OFF
                    if not role.enabled:
                        status_str = "OFF"
                        status_col = [120, 120, 120, 255]
                    elif role.is_busy():
                        status_str = "BUSY"
                        status_col = [243, 156, 18, 255]
                    else:
                        status_str = "IDLE"
                        status_col = [46, 204, 113, 255]
                    dpg.add_text(f"[ {status_str} ]", tag=f"lbl_status_badge_{role_id}", color=status_col)

                # Row 2: Description
                dpg.add_text(f"{role.description}", color=[140, 140, 140, 255], wrap=680)

                dpg.add_spacer(height=2)
                # Row 3: Live details & Audio test
                with dpg.group(horizontal=True):
                    dpg.add_text("Live: ", color=[180, 180, 180, 255])
                    live_text = "Ready" if role.enabled else "Disabled"
                    dpg.add_text(live_text, tag=f"lbl_live_detail_{role_id}", color=[220, 220, 220, 255])

                    dpg.add_spacer(width=20)
                    dpg.add_button(
                        label="Test Audio",
                        width=85,
                        user_data=role_id,
                        callback=self._cb_test_role_audio,
                    )

                # Row 4: Dynamic parameter form for role
                params = role.get_parameters()
                if params:
                    dpg.add_spacer(height=2)
                    dpg.add_separator()
                    dpg.add_text("Role Parameters & Settings:", color=[255, 200, 0, 255])

                    # Separate booleans (checkboxes) and numeric sliders
                    bool_params = [p for p in params if isinstance(p, BoolParam)]
                    num_params = [p for p in params if not isinstance(p, BoolParam)]

                    # Display Booleans (Checkboxes) grouped 2 per line
                    if bool_params:
                        for i in range(0, len(bool_params), 2):
                            with dpg.group(horizontal=True):
                                for p in bool_params[i:i+2]:
                                    chk_tag = f"param_{role_id}_{p.name}"
                                    dpg.add_checkbox(
                                        label=p.label,
                                        tag=chk_tag,
                                        default_value=role.get_param_value(p.name),
                                        user_data=(role_id, p.name),
                                        callback=self._cb_param_changed,
                                    )
                                    if p.description:
                                        with dpg.tooltip(chk_tag):
                                             dpg.add_text(p.description)
                                    dpg.add_spacer(width=15)

                    # Display numeric sliders (IntRange / FloatRange)
                    if num_params:
                        for p in num_params:
                            ctrl_tag = f"param_{role_id}_{p.name}"
                            with dpg.group(horizontal=True):
                                if isinstance(p, IntRangeParam):
                                    dpg.add_slider_int(
                                        label=f"{p.label} ({p.unit})" if p.unit else p.label,
                                        tag=ctrl_tag,
                                        min_value=p.min_val,
                                        max_value=p.max_val,
                                        default_value=role.get_param_value(p.name),
                                        width=220,
                                        user_data=(role_id, p.name),
                                        callback=self._cb_param_changed,
                                    )
                                elif isinstance(p, FloatRangeParam):
                                    fmt = f"%.1f {p.unit}" if p.unit else "%.1f"
                                    dpg.add_slider_float(
                                        label=f"{p.label} ({p.unit})" if p.unit else p.label,
                                        tag=ctrl_tag,
                                        min_value=p.min_val,
                                        max_value=p.max_val,
                                        default_value=role.get_param_value(p.name),
                                        format=fmt,
                                        width=220,
                                        user_data=(role_id, p.name),
                                        callback=self._cb_param_changed,
                                    )
                                if p.description:
                                    with dpg.tooltip(ctrl_tag):
                                        dpg.add_text(p.description)

            dpg.add_spacer(parent="group_roles_list", height=4)

    def _cb_param_changed(self, sender, app_data, user_data):
        """Callback triggered upon parameter change in GUI form."""
        role_id, param_name = user_data
        role = self.engineer.get_role(role_id)
        if role:
            role.set_param_value(param_name, app_data)
            self.engineer.save_to_file()
            logger.info(f"[RaceEngineer GUI] Parameter updated: {role_id}.{param_name} = {app_data}")

    def _cb_toggle_master_enabled(self, sender, app_data):
        self.engineer.set_master_enabled(bool(app_data))
        logger.info(f"[RaceEngineer GUI] Master switch: {self.engineer.enabled}")

    def _cb_toggle_mute(self, sender, app_data):
        AudioAnnouncer.set_muted(bool(app_data))
        logger.info(f"[RaceEngineer GUI] Audio Mute: {AudioAnnouncer.is_muted()}")

    def _cb_toggle_role(self, sender, app_data, user_data):
        role_id = user_data
        enabled = bool(app_data)
        self.engineer.set_role_enabled(role_id, enabled)
        if dpg.does_item_exist(f"lbl_name_{role_id}"):
            col = [0, 210, 255, 255] if enabled else [120, 120, 120, 255]
            dpg.configure_item(f"lbl_name_{role_id}", color=col)
        badge_tag = f"lbl_status_badge_{role_id}"
        if dpg.does_item_exist(badge_tag):
            if not enabled:
                dpg.set_value(badge_tag, "[ OFF ]")
                dpg.configure_item(badge_tag, color=[120, 120, 120, 255])
            else:
                dpg.set_value(badge_tag, "[ IDLE ]")
                dpg.configure_item(badge_tag, color=[46, 204, 113, 255])
        detail_tag = f"lbl_live_detail_{role_id}"
        if dpg.does_item_exist(detail_tag) and not enabled:
            dpg.set_value(detail_tag, "Disabled")

    def _cb_move_role_up(self, sender, app_data, user_data):
        role_id = user_data
        if self.engineer.move_role_up(role_id):
            self._render_roles_cards()

    def _cb_move_role_down(self, sender, app_data, user_data):
        role_id = user_data
        if self.engineer.move_role_down(role_id):
            self._render_roles_cards()

    def _cb_save_config(self, sender, app_data):
        self.engineer.save_to_file()
        logger.info("[RaceEngineer GUI] Manual configuration saved to file.")

    def _cb_test_voice(self, sender, app_data):
        AudioAnnouncer.play_phrase("timing_in_progress")

    def _cb_reset_roles(self, sender, app_data):
        self.engineer.reset_all()

    def _cb_test_role_audio(self, sender, app_data, user_data):
        role_id = user_data
        if role_id == "lap_validity":
            AudioAnnouncer.play_timing_in_progress()
        elif role_id == "traffic_spotter":
            AudioAnnouncer.play_alongside()
        elif role_id == "pitlane_spotter":
            AudioAnnouncer.play_phrase("car")
        elif role_id == "traffic_jam":
            AudioAnnouncer.play_car()
        else:
            AudioAnnouncer.play_phrase("lap")

    # ── Periodic Refresh (UI Tick) ────────────────────────────────
    def render_tick(self) -> None:
        """Updates status badges and dynamic indicators."""
        now = time.time()
        if (now - self._last_ui_refresh) < 0.08:  # ~12 FPS for status UI
            return
        self._last_ui_refresh = now

        # 1. Global status
        any_busy = self.engineer.is_any_role_busy()
        if dpg.does_item_exist("lbl_engineer_global_status"):
            if not self.engineer.enabled:
                dpg.set_value("lbl_engineer_global_status", "DISABLED (Master switch off)")
                dpg.configure_item("lbl_engineer_global_status", color=[231, 76, 60, 255])
            elif any_busy:
                busy_names = ", ".join(r.name for r in self.engineer.get_busy_roles())
                dpg.set_value("lbl_engineer_global_status", f"ENGAGED ({busy_names})")
                dpg.configure_item("lbl_engineer_global_status", color=[243, 156, 18, 255])
            else:
                dpg.set_value("lbl_engineer_global_status", "STANDBY (All roles IDLE)")
                dpg.configure_item("lbl_engineer_global_status", color=[46, 204, 113, 255])

        # 2. Individual role status
        for role in self.engineer.get_roles():
            role_id = role.role_id
            badge_tag = f"lbl_status_badge_{role_id}"
            detail_tag = f"lbl_live_detail_{role_id}"

            if dpg.does_item_exist(badge_tag):
                if not role.enabled:
                    badge_str = "OFF"
                    badge_col = [120, 120, 120, 255]
                elif role.is_busy():
                    badge_str = "BUSY"
                    badge_col = [243, 156, 18, 255]
                else:
                    badge_str = "IDLE"
                    badge_col = [46, 204, 113, 255]
                dpg.set_value(badge_tag, f"[ {badge_str} ]")
                dpg.configure_item(badge_tag, color=badge_col)

            if dpg.does_item_exist(detail_tag):
                if not role.enabled:
                    dpg.set_value(detail_tag, "Disabled")
                else:
                    summary = role.get_state_summary()
                    detail_text = self._format_role_summary(role_id, summary)
                    dpg.set_value(detail_tag, detail_text)

        # 3. Spotter FSM & Radar Diagnostic
        self._update_radar_ui()

    def _format_role_summary(self, role_id: str, summary: Dict[str, Any]) -> str:
        """Formats a concise text line for role details."""
        if role_id == "traffic_spotter":
            state = summary.get("fsm_state", "IDLE")
            if state != "IDLE":
                target = summary.get("target_driver", "Opponent")
                ttc = summary.get("live_ttc_str", "--")
                dist = summary.get("live_distance_str", "--")
                delta = summary.get("live_speed_delta_str", "--")
                return f"[{state}] Target: {target} | TTC: {ttc} | Dist: {dist} | Delta: {delta}"
            return "IDLE — Track clear behind"

        elif role_id == "pitlane_spotter":
            pit_st = summary.get("fsm_state", "IDLE")
            info = summary.get("pit_info", "Clear")
            return f"[{pit_st}] {info}"

        elif role_id == "lap_validity":
            flag_text = summary.get("lap_status_text", "Ready")
            last_ev = summary.get("last_event", "None")
            return f"Current Lap: {flag_text} | Last Event: {last_ev}"

        elif role_id == "traffic_jam":
            slow_info = summary.get("slow_car_info", "Clear ahead")
            return f"Track Ahead: {slow_info}"

        return str(summary.get("status", "IDLE"))

    def _update_radar_ui(self) -> None:
        """Updates diagnostic panel and opponents radar table."""
        traffic_role: Optional[TrafficSpotterRole] = None
        for r in self.engineer.get_roles():
            if isinstance(r, TrafficSpotterRole):
                traffic_role = r
                break

        if traffic_role:
            summ = traffic_role.get_state_summary()
            if dpg.does_item_exist("lbl_spotter_fsm_state"):
                fsm_st = summ.get("fsm_state", "IDLE")
                fsm_col = [46, 204, 113, 255] if fsm_st == "IDLE" else [243, 156, 18, 255]
                dpg.set_value("lbl_spotter_fsm_state", f"FSM State: {fsm_st}")
                dpg.configure_item("lbl_spotter_fsm_state", color=fsm_col)

            if dpg.does_item_exist("lbl_spotter_target"):
                target = summ.get("target_driver", "None")
                car = summ.get("target_car", "")
                dpg.set_value("lbl_spotter_target", f"Locked Target: {target} ({car})")

            if dpg.does_item_exist("lbl_spotter_ttc"):
                dpg.set_value("lbl_spotter_ttc", f"Live TTC: {summ.get('live_ttc_str', '--')}")

            if dpg.does_item_exist("lbl_spotter_dist"):
                dpg.set_value("lbl_spotter_dist", f"Relative Distance: {summ.get('live_distance_str', '--')}")

            if dpg.does_item_exist("lbl_spotter_delta_speed"):
                dpg.set_value("lbl_spotter_delta_speed", f"Speed Delta: {summ.get('live_speed_delta_str', '--')}")
