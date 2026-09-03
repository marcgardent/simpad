"""
SimPad LMU Schedule & Notifications Tab — Dear PyGui Tab (High Performance UI).
Visualization of official Le Mans Ultimate schedule (https://api.lmuschedule.com),
activation and configuration by SETUP <Level> <Classes> <Track>,
live countdowns and FIFO audio queue management.
Optimized rendering without nested child windows for smooth 60 FPS scrolling.
"""

import time
import datetime
import logging
from typing import Optional, Dict, Any, List
import dearpygui.dearpygui as dpg

from src.schedule import LMUScheduleManager, RaceSetupConfig, RaceEvent
from src.utils.audio import AudioAnnouncer

logger = logging.getLogger(__name__)

MAX_TABLE_ROWS = 16
MAX_LOG_ENTRIES = 8


class LMUScheduleTab:
    """
    GUI manager tab dedicated to LMU race schedule and voice alerts.
    Optimized for maximum smoothness (zero dynamic allocations in tick loop).
    """

    def __init__(self, schedule_manager: Optional[LMUScheduleManager] = None):
        self.schedule_mgr = schedule_manager or LMUScheduleManager()
        self._parent_app: Optional[Any] = None
        self._last_ui_tick: float = 0.0
        self._selected_category_filter: str = "All"

    def build_tab(self, parent_app: Any) -> None:
        """Builds Dear PyGui interface in LMU Schedule tab."""
        self._parent_app = parent_app

        # ── 1. Top toolbar: Master, API, Audio Queue & Actions ──
        with dpg.child_window(height=84, border=True, tag="child_schedule_toolbar"):
            with dpg.group(horizontal=True):
                dpg.add_text("LMU Schedule Engine:", color=[0, 210, 255, 255])
                dpg.add_checkbox(
                    label="Global Alerts",
                    tag="chk_sched_master_enabled",
                    default_value=self.schedule_mgr.master_enabled,
                    callback=self._cb_toggle_master_enabled,
                )

                dpg.add_spacer(width=10)
                dpg.add_checkbox(
                    label="Audio Voice (FIFO)",
                    tag="chk_sched_audio_enabled",
                    default_value=self.schedule_mgr.audio_enabled,
                    callback=self._cb_toggle_audio_enabled,
                )

                dpg.add_spacer(width=10)
                dpg.add_checkbox(
                    label="OS Notification",
                    tag="chk_sched_desktop_notif",
                    default_value=self.schedule_mgr.desktop_notifications_enabled,
                    callback=self._cb_toggle_desktop_notif,
                )

                dpg.add_spacer(width=15)
                dpg.add_text("API:", color=[180, 180, 180, 255])
                dpg.add_text(self.schedule_mgr.api_status, tag="lbl_sched_api_status", color=[46, 204, 113, 255])
                dpg.add_button(label="🔄 Sync API", width=85, callback=self._cb_refresh_api)

            dpg.add_spacer(height=3)
            with dpg.group(horizontal=True):
                dpg.add_text("Audio Queue:", color=[180, 180, 180, 255])
                dpg.add_text("0 pending (IDLE)", tag="lbl_audio_queue_status", color=[0, 210, 255, 255])
                dpg.add_button(label="⏹ Clear Queue", width=95, callback=self._cb_clear_audio_queue)

                dpg.add_spacer(width=15)
                dpg.add_button(label="❌ Uncheck All", width=125, callback=self._cb_uncheck_all)
                dpg.add_button(label="⚡ Enable All (5m)", width=140, callback=lambda: self._cb_enable_all_quick(5))
                dpg.add_button(label="Save", width=95, callback=self._cb_save_config)

        dpg.add_spacer(height=4)

        # ── 2. Main Body: Setups List & Chronological Schedule ────
        with dpg.group(horizontal=True):
            # Left Column: All configurable Setups <Level> <Classes> <Track>
            with dpg.child_window(width=780, height=-1, border=True, tag="child_sched_left_col"):
                with dpg.group(horizontal=True):
                    dpg.add_text("LMU Setups: <Level> <Classes> <Track>", color=[255, 200, 0, 255])
                    dpg.add_spacer(width=15)
                    dpg.add_text("Filter:", color=[180, 180, 180, 255])
                    dpg.add_combo(
                        items=["All", "Beginner (Bronze)", "Intermediate (Silver)", "Advanced (Gold)", "Weekly (Special)"],
                        default_value="All",
                        tag="combo_category_filter",
                        width=180,
                        callback=self._cb_change_filter,
                    )

                dpg.add_text("Enable desired Setups. All race sessions for this Setup will be monitored.", color=[150, 150, 150, 255])
                dpg.add_separator()
                dpg.add_spacer(height=4)

                with dpg.group(tag="group_races_cards_container"):
                    self._build_all_setup_cards()

            # Right Column: Chronological Grid & Audio Queue Diagnostics
            with dpg.child_window(width=-1, height=-1, border=True, tag="child_sched_right_col"):
                dpg.add_text("Upcoming Races Chronological Schedule:", color=[0, 210, 255, 255])
                dpg.add_text("All sessions from Setups sorted by start time.", color=[150, 150, 150, 255])
                dpg.add_separator()
                dpg.add_spacer(height=4)

                # Schedule table (static and performant without dynamic deletion)
                with dpg.table(
                    header_row=True,
                    resizable=True,
                    policy=dpg.mvTable_SizingStretchProp,
                    borders_outerH=True,
                    borders_innerH=True,
                    borders_innerV=True,
                    borders_outerV=True,
                    height=310,
                    tag="table_upcoming_races",
                ):
                    dpg.add_table_column(label="Time", width_fixed=True, init_width_or_weight=60)
                    dpg.add_table_column(label="Level", width_fixed=True, init_width_or_weight=75)
                    dpg.add_table_column(label="Classes", width_fixed=True, init_width_or_weight=90)
                    dpg.add_table_column(label="Track", init_width_or_weight=130)
                    dpg.add_table_column(label="Series", init_width_or_weight=120)
                    dpg.add_table_column(label="Status", width_fixed=True, init_width_or_weight=110)
                    dpg.add_table_column(label="Countdown", width_fixed=True, init_width_or_weight=95)

                    # Pre-create rows to prevent allocation in render loop
                    for i in range(MAX_TABLE_ROWS):
                        with dpg.table_row(tag=f"row_up_{i}"):
                            dpg.add_text("--:--", tag=f"lbl_up_time_{i}", color=[0, 210, 255, 255])
                            dpg.add_text("---", tag=f"lbl_up_diff_{i}")
                            dpg.add_text("---", tag=f"lbl_up_cls_{i}")
                            dpg.add_text("---", tag=f"lbl_up_track_{i}")
                            dpg.add_text("---", tag=f"lbl_up_series_{i}")
                            dpg.add_text("---", tag=f"lbl_up_status_{i}")
                            dpg.add_text("---", tag=f"lbl_up_cd_{i}", color=[255, 200, 0, 255])

                dpg.add_spacer(height=8)
                dpg.add_text("Triggered Announcements Log:", color=[255, 200, 0, 255])
                with dpg.child_window(height=130, border=True, tag="child_notif_logs"):
                    for i in range(MAX_LOG_ENTRIES):
                        with dpg.group(horizontal=True, tag=f"grp_log_{i}", show=False):
                            dpg.add_text("[--:--:--]", tag=f"lbl_log_time_{i}", color=[0, 210, 255, 255])
                            dpg.add_text("[Setup]", tag=f"lbl_log_name_{i}", color=[255, 200, 0, 255])
                            dpg.add_text("Message", tag=f"lbl_log_msg_{i}", color=[240, 240, 240, 255])
                    dpg.add_text("Waiting for notifications...", tag="lbl_notif_empty_history", color=[120, 120, 120, 255])

                dpg.add_spacer(height=6)
                dpg.add_text("Immediate Voice Test (FIFO Queue):", color=[0, 210, 255, 255])
                with dpg.group(horizontal=True):
                    dpg.add_button(label="LMGT3 Fixed", width=105, callback=lambda: AudioAnnouncer.play_phrase("lmgt3_fixed"))
                    dpg.add_button(label="ELMS Sprint", width=105, callback=lambda: AudioAnnouncer.play_phrase("elms_sprint_trophy"))
                    dpg.add_button(label="One Stint", width=85, callback=lambda: AudioAnnouncer.play_phrase("one_stint_sprint"))
                    dpg.add_button(label="WEC Weekly", width=95, callback=lambda: AudioAnnouncer.play_phrase("wec_weekly"))
                    dpg.add_button(label="Registration", width=90, callback=lambda: AudioAnnouncer.play_phrase("registration_open"))

    def _build_all_setup_cards(self) -> None:
        """Builds all Setup cards according to active filter."""
        category_colors = {
            "Beginner": [46, 204, 113, 255],      # Green (Bronze)
            "Intermediate": [0, 210, 255, 255],   # Cyan (Silver)
            "Advanced": [241, 196, 15, 255],      # Yellow / Gold
            "Weekly": [155, 89, 182, 255],        # Purple (Weekly)
        }

        filter_mapping = {
            "Beginner (Bronze)": "Beginner",
            "Intermediate (Silver)": "Intermediate",
            "Advanced (Gold)": "Advanced",
            "Weekly (Special)": "Weekly",
        }
        target_diff = filter_mapping.get(self._selected_category_filter)

        for setup_id, cfg in self.schedule_mgr.setups.items():
            if target_diff and cfg.difficulty != target_diff:
                continue

            accent = category_colors.get(cfg.difficulty, [200, 200, 200, 255])
            self._build_single_setup_card(setup_id, cfg, accent)
            dpg.add_spacer(height=10, parent="group_races_cards_container")

    def _build_single_setup_card(self, setup_id: str, cfg: RaceSetupConfig, accent_color: List[int]) -> None:
        """
        Builds an optimized Setup <Level><Classes><Track> block.
        Uses simple groups instead of nested child windows to ensure 60 FPS without lag.
        """
        with dpg.group(tag=f"card_setup_{setup_id}", parent="group_races_cards_container"):
            # Row 1: Title <Level> <Classes> @ <Track>, Series, Enable checkbox and Test Button
            with dpg.group(horizontal=True):
                dpg.add_text(f"[{cfg.difficulty.upper()}]", color=accent_color)
                dpg.add_text(f"{cfg.car_classes} @ {cfg.circuit}", color=[255, 255, 255, 255])
                dpg.add_text(f"({cfg.series_name} • {cfg.race_length_min}m)", color=[160, 160, 160, 255])
                dpg.add_spacer(width=12)
                dpg.add_checkbox(
                    label="Enable",
                    tag=f"chk_setup_enabled_{setup_id}",
                    default_value=cfg.enabled,
                    user_data=(setup_id, "enabled"),
                    callback=self._cb_toggle_setup_checkbox,
                )
                dpg.add_spacer(width=6)
                dpg.add_button(
                    label="🔊 Test",
                    width=65,
                    user_data=setup_id,
                    callback=self._cb_test_sound,
                )

            # Row 2: Dynamic live status (Start, Countdown, Registrations)
            with dpg.group(horizontal=True):
                dpg.add_text("Next start:", color=[180, 180, 180, 255])
                dpg.add_text("--:--", tag=f"lbl_next_start_{setup_id}", color=[46, 204, 113, 255])
                dpg.add_spacer(width=12)
                dpg.add_text("Countdown:", color=[180, 180, 180, 255])
                dpg.add_text("--m --s", tag=f"lbl_countdown_{setup_id}", color=[255, 200, 0, 255])
                dpg.add_spacer(width=12)
                dpg.add_text("Registration:", color=[180, 180, 180, 255])
                dpg.add_text("--:--", tag=f"lbl_reg_open_{setup_id}", color=[0, 210, 255, 255])

            # Row 3: Grid of 6 reminder checkboxes
            with dpg.group(horizontal=True):
                dpg.add_text("Reminders:", color=[180, 180, 180, 255])
                dpg.add_spacer(width=4)
                dpg.add_checkbox(
                    label="15m",
                    tag=f"chk_{setup_id}_15m",
                    default_value=cfg.notify_15m,
                    user_data=(setup_id, "notify_15m"),
                    callback=self._cb_toggle_setup_checkbox,
                )
                dpg.add_spacer(width=6)
                dpg.add_checkbox(
                    label="10m",
                    tag=f"chk_{setup_id}_10m",
                    default_value=cfg.notify_10m,
                    user_data=(setup_id, "notify_10m"),
                    callback=self._cb_toggle_setup_checkbox,
                )
                dpg.add_spacer(width=6)
                dpg.add_checkbox(
                    label="5m",
                    tag=f"chk_{setup_id}_5m",
                    default_value=cfg.notify_5m,
                    user_data=(setup_id, "notify_5m"),
                    callback=self._cb_toggle_setup_checkbox,
                )
                dpg.add_spacer(width=6)
                dpg.add_checkbox(
                    label="1m",
                    tag=f"chk_{setup_id}_1m",
                    default_value=cfg.notify_1m,
                    user_data=(setup_id, "notify_1m"),
                    callback=self._cb_toggle_setup_checkbox,
                )
                dpg.add_spacer(width=6)
                dpg.add_checkbox(
                    label="Registration",
                    tag=f"chk_{setup_id}_reg",
                    default_value=cfg.notify_reg_open,
                    user_data=(setup_id, "notify_reg_open"),
                    callback=self._cb_toggle_setup_checkbox,
                )
                dpg.add_spacer(width=6)
                dpg.add_checkbox(
                    label="Start",
                    tag=f"chk_{setup_id}_start",
                    default_value=cfg.notify_start,
                    user_data=(setup_id, "notify_start"),
                    callback=self._cb_toggle_setup_checkbox,
                )

            dpg.add_separator()

    # ── Update Callbacks ───────────────────────────────────────────────
    def _cb_change_filter(self, sender, app_data):
        self._selected_category_filter = str(app_data)
        children = dpg.get_item_children("group_races_cards_container", 1)
        if children:
            for child in children:
                dpg.delete_item(child)
        self._build_all_setup_cards()

    def _cb_uncheck_all(self, sender=None, app_data=None):
        """Unchecks all Setups and all reminder checkboxes in 1 click."""
        self.schedule_mgr.disable_all_setups_and_reminders()
        for setup_id in self.schedule_mgr.setups:
            for tag in [
                f"chk_setup_enabled_{setup_id}",
                f"chk_{setup_id}_15m",
                f"chk_{setup_id}_10m",
                f"chk_{setup_id}_5m",
                f"chk_{setup_id}_1m",
                f"chk_{setup_id}_reg",
                f"chk_{setup_id}_start",
            ]:
                if dpg.does_item_exist(tag):
                    dpg.set_value(tag, False)
        logger.info("[LMUScheduleTab] All unchecked successfully.")

    def _cb_enable_all_quick(self, notify_minutes: int = 5):
        """Enables all Setups with a 5m reminder in 1 click."""
        self.schedule_mgr.enable_all_quick(notify_minutes=notify_minutes)
        for setup_id, cfg in self.schedule_mgr.setups.items():
            if dpg.does_item_exist(f"chk_setup_enabled_{setup_id}"):
                dpg.set_value(f"chk_setup_enabled_{setup_id}", True)
            if dpg.does_item_exist(f"chk_{setup_id}_5m"):
                dpg.set_value(f"chk_{setup_id}_5m", True)
        logger.info(f"[LMUScheduleTab] All Setups enabled with reminder {notify_minutes}m.")

    def _cb_clear_audio_queue(self, sender=None, app_data=None):
        AudioAnnouncer.clear_queue()
        AudioAnnouncer.stop_current()
        logger.info("[LMUScheduleTab] Audio queue cleared.")

    def _cb_toggle_master_enabled(self, sender, app_data):
        self.schedule_mgr.master_enabled = bool(app_data)
        self.schedule_mgr.save_config()

    def _cb_toggle_audio_enabled(self, sender, app_data):
        self.schedule_mgr.audio_enabled = bool(app_data)
        self.schedule_mgr.save_config()

    def _cb_toggle_desktop_notif(self, sender, app_data):
        self.schedule_mgr.desktop_notifications_enabled = bool(app_data)
        self.schedule_mgr.save_config()

    def _cb_refresh_api(self, sender=None, app_data=None):
        if dpg.does_item_exist("lbl_sched_api_status"):
            dpg.set_value("lbl_sched_api_status", "Synchronizing...")
            dpg.configure_item("lbl_sched_api_status", color=[243, 156, 18, 255])
        self.schedule_mgr.refresh_api_async(callback=self._on_api_sync_done)

    def _on_api_sync_done(self, success: bool):
        if dpg.does_item_exist("lbl_sched_api_status"):
            dpg.set_value("lbl_sched_api_status", self.schedule_mgr.api_status)
            col = [46, 204, 113, 255] if success else [231, 76, 60, 255]
            dpg.configure_item("lbl_sched_api_status", color=col)
        children = dpg.get_item_children("group_races_cards_container", 1)
        if children:
            for child in children:
                dpg.delete_item(child)
        self._build_all_setup_cards()

    def _cb_save_config(self, sender=None, app_data=None, user_data=None):
        self.schedule_mgr.save_config()
        logger.info("[LMUScheduleTab] Setups configuration saved successfully.")

    def _cb_toggle_setup_checkbox(self, sender, app_data, user_data):
        if not user_data or not isinstance(user_data, (tuple, list)) or len(user_data) < 2:
            return
        setup_id, field_name = user_data
        cfg = self.schedule_mgr.setups.get(setup_id)
        if cfg and hasattr(cfg, field_name):
            setattr(cfg, field_name, bool(app_data))
            self.schedule_mgr.save_config()
            logger.info(f"[LMUScheduleTab] Saved {setup_id}.{field_name} = {app_data}")

    def _cb_test_sound(self, sender, app_data, user_data):
        setup_id = user_data
        if setup_id:
            self.schedule_mgr.test_announcement(str(setup_id), "main")

    # ── Render Loop Tick (High Performance) ───────────────────────────────────
    def render_tick(self) -> None:
        """Called on every render frame (~1 Hz for non-blocking UI refresh)."""
        now = time.time()
        triggered = self.schedule_mgr.update(now=now)
        if triggered:
            self._refresh_notification_logs()

        # UI refresh clocked at 1 Hz
        if now - self._last_ui_tick < 1.0:
            return
        self._last_ui_tick = now

        # Audio queue status
        q_size = AudioAnnouncer.get_queue_size()
        is_playing = AudioAnnouncer.is_playing()
        if dpg.does_item_exist("lbl_audio_queue_status"):
            if is_playing:
                dpg.set_value("lbl_audio_queue_status", f"Playing ({q_size} in queue)")
                dpg.configure_item("lbl_audio_queue_status", color=[241, 196, 15, 255])
            elif q_size > 0:
                dpg.set_value("lbl_audio_queue_status", f"{q_size} in queue")
                dpg.configure_item("lbl_audio_queue_status", color=[255, 200, 0, 255])
            else:
                dpg.set_value("lbl_audio_queue_status", "0 (Ready)")
                dpg.configure_item("lbl_audio_queue_status", color=[46, 204, 113, 255])

        if dpg.does_item_exist("lbl_sched_api_status"):
            dpg.set_value("lbl_sched_api_status", self.schedule_mgr.api_status)

        self._refresh_setup_cards(now)
        self._refresh_upcoming_table(now)

    def _refresh_setup_cards(self, now: float) -> None:
        """Updates countdowns and start times for all Setup cards."""
        for setup_id in self.schedule_mgr.setups:
            event = self.schedule_mgr.get_next_event(setup_id, now=now)
            if not event:
                continue

            lbl_start = f"lbl_next_start_{setup_id}"
            lbl_count = f"lbl_countdown_{setup_id}"
            lbl_reg = f"lbl_reg_open_{setup_id}"

            if dpg.does_item_exist(lbl_start):
                dpg.set_value(lbl_start, event.start_time_str)

            if dpg.does_item_exist(lbl_reg):
                reg_prefix = "Open!" if event.status == "REGISTRATION_OPEN" else event.reg_open_time_str
                dpg.set_value(lbl_reg, reg_prefix)
                reg_col = [46, 204, 113, 255] if event.status == "REGISTRATION_OPEN" else [0, 210, 255, 255]
                dpg.configure_item(lbl_reg, color=reg_col)

            if dpg.does_item_exist(lbl_count):
                dpg.set_value(lbl_count, event.countdown_str)
                if event.status == "REGISTRATION_OPEN":
                    col = [46, 204, 113, 255]  # Green
                elif 0 < event.time_until_start <= 300:
                    col = [231, 76, 60, 255]   # Red (<5 min)
                elif 0 < event.time_until_start <= 900:
                    col = [241, 196, 15, 255]  # Yellow (<15 min)
                elif event.status == "IN_PROGRESS":
                    col = [155, 89, 182, 255]  # Purple
                else:
                    col = [255, 200, 0, 255]
                dpg.configure_item(lbl_count, color=col)

    def _refresh_upcoming_table(self, now: float) -> None:
        """Updates chronological upcoming races table without dynamic widget recreation."""
        if not dpg.does_item_exist("table_upcoming_races"):
            return

        events = self.schedule_mgr.get_upcoming_events(horizon_hours=8.0, now=now)

        status_colors = {
            "REGISTRATION_OPEN": [46, 204, 113, 255],
            "IN_PROGRESS": [155, 89, 182, 255],
            "UPCOMING": [180, 180, 180, 255],
            "FINISHED": [100, 100, 100, 255],
        }

        status_labels = {
            "REGISTRATION_OPEN": "Registration",
            "IN_PROGRESS": "In Progress",
            "UPCOMING": "Upcoming",
            "FINISHED": "Finished",
        }

        category_colors = {
            "Beginner": [46, 204, 113, 255],
            "Intermediate": [0, 210, 255, 255],
            "Advanced": [241, 196, 15, 255],
            "Weekly": [155, 89, 182, 255],
        }

        for i in range(MAX_TABLE_ROWS):
            row_tag = f"row_up_{i}"
            if not dpg.does_item_exist(row_tag):
                continue

            if i < len(events):
                ev = events[i]
                dpg.show_item(row_tag)
                dpg.set_value(f"lbl_up_time_{i}", ev.start_time_str)
                dpg.set_value(f"lbl_up_diff_{i}", ev.difficulty)
                cat_col = category_colors.get(ev.difficulty, [200, 200, 200, 255])
                dpg.configure_item(f"lbl_up_diff_{i}", color=cat_col)

                dpg.set_value(f"lbl_up_cls_{i}", ev.car_classes)
                dpg.set_value(f"lbl_up_track_{i}", ev.track_name)
                dpg.set_value(f"lbl_up_series_{i}", ev.series_name)

                s_lbl = status_labels.get(ev.status, ev.status)
                s_col = status_colors.get(ev.status, [200, 200, 200, 255])
                dpg.set_value(f"lbl_up_status_{i}", s_lbl)
                dpg.configure_item(f"lbl_up_status_{i}", color=s_col)

                dpg.set_value(f"lbl_up_cd_{i}", ev.countdown_str)
                dpg.configure_item(f"lbl_up_cd_{i}", color=[255, 200, 0, 255] if ev.time_until_start > 0 else [180, 180, 180, 255])
            else:
                dpg.hide_item(row_tag)

    def _refresh_notification_logs(self) -> None:
        """Displays recent notifications in log box without recreating items."""
        if not dpg.does_item_exist("child_notif_logs"):
            return

        history = self.schedule_mgr.notification_history
        has_history = bool(history)

        if dpg.does_item_exist("lbl_notif_empty_history"):
            if has_history:
                dpg.hide_item("lbl_notif_empty_history")
            else:
                dpg.show_item("lbl_notif_empty_history")

        for i in range(MAX_LOG_ENTRIES):
            grp_tag = f"grp_log_{i}"
            if not dpg.does_item_exist(grp_tag):
                continue

            if i < len(history):
                entry = history[i]
                dpg.show_item(grp_tag)
                dpg.set_value(f"lbl_log_time_{i}", f"[{entry.get('time_str', '')}]")
                dpg.set_value(f"lbl_log_name_{i}", f"[{entry.get('setup_name', entry.get('race_name', ''))}]")
                dpg.set_value(f"lbl_log_msg_{i}", entry.get("message", ""))
            else:
                dpg.hide_item(grp_tag)
