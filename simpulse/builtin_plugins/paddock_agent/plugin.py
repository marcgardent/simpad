"""
SimPulse Plugin — LMU Paddock Agent & Race Announcer (Qt6 Pure).
Fetches official Le Mans Ultimate online racing schedules, announces upcoming race departures
with high-definition voice alerts (FIFO queue), and provides persistent category and skill level filters.
"""

from __future__ import annotations
import time
import datetime
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, List

from PySide6.QtCore import Qt, QSize, Signal, QTimer, QThread
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QGroupBox, QScrollArea, QFrame, QProgressBar,
    QComboBox, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QTabWidget, QMessageBox
)

from simpulse_sdk import (
    SimPulsePlugin, PluginMetadata, PluginContext,
    ITabProvider, ITelemetrySubscriber,
    TelemetryChannel, ChannelRequirement
)
try:
    from simpulse.builtin_plugins.paddock_agent.schedule import (
        LMUScheduleManager, RaceSetupConfig, RaceEvent, DEFAULT_RACE_SETUPS, clean_series_key, SetupConfigScalar
    )
except ImportError:
    from .schedule import (
        LMUScheduleManager, RaceSetupConfig, RaceEvent, DEFAULT_RACE_SETUPS, clean_series_key, SetupConfigScalar
    )
from simpulse.core.utils.audio import AudioAnnouncer

logger = logging.getLogger("simpulse.plugin.paddock_agent")


@dataclass
class PaddockAgentConfig:
    """Strongly-typed configuration schema for Paddock Agent Plugin."""
    master_enabled: bool = True
    voice_enabled: bool = True
    desktop_notif: bool = True
    sync_interval_min: int = 15

    # Persistent Display Filters
    filter_difficulty: str = "All"       # All, Beginner, Intermediate, Advanced, Weekly
    filter_car_class: str = "All"        # All, GT3, LMP2, Hypercar, LMP3, GTE, Multi-Class
    filter_race_type: str = "All"        # All, Daily Races, Weekly Races, Fixed Setup, Open Setup
    filter_active_only: bool = False     # Only show subscribed series
    search_query: str = ""

    # Per-Series Setups and Notification preferences
    setup_configs: Dict[str, Dict[str, SetupConfigScalar]] = field(default_factory=dict)


# =============================================================================
# Background Worker for LMU Schedule API Sync
# =============================================================================

class ApiSyncWorker(QThread):
    """Background worker to fetch LMU schedule without freezing the UI."""
    sync_finished = Signal(bool, str)  # success, status_message

    def __init__(self, schedule_mgr: LMUScheduleManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.schedule_mgr = schedule_mgr

    def run(self) -> None:
        try:
            ok = self.schedule_mgr.sync_api()
            msg = f"Online ({len(self.schedule_mgr.setups)} Series)" if ok else "Offline (Cache Used)"
            self.sync_finished.emit(ok, msg)
        except Exception as e:
            logger.warning(f"Error syncing LMU schedule API: {e}")
            self.sync_finished.emit(False, str(e))


# =============================================================================
# Series Setup Card Widget (Subscriptions Configuration Pane)
# =============================================================================

class SeriesSetupCardWidget(QFrame):
    """Card widget representing a single LMU race series with toggleable notification alerts."""

    setup_updated = Signal(str)

    def __init__(self, setup: RaceSetupConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setup = setup
        self._init_ui()

    def _init_ui(self) -> None:
        self.setStyleSheet(
            "SeriesSetupCardWidget { background-color: #0f172a; border: 1px solid #1e293b; "
            "border-radius: 8px; padding: 6px; } "
            "SeriesSetupCardWidget:hover { border-color: #38bdf8; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # Header Row: Checkbox, Title, Difficulty Badge, Length
        h_row = QHBoxLayout()

        self.chk_enable = QCheckBox(self)
        self.chk_enable.setChecked(self.setup.enabled)
        self.chk_enable.toggled.connect(self._on_enable_toggled)
        h_row.addWidget(self.chk_enable)

        title_txt = f"<b>{self.setup.series_name}</b> <span style='color:#94a3b8;'>({self.setup.car_classes} @ {self.setup.circuit})</span>"
        lbl_title = QLabel(title_txt, self)
        lbl_title.setStyleSheet("font-size: 13px; color: #f8fafc;")
        h_row.addWidget(lbl_title, 1)

        # Difficulty Badge
        diff_color = {
            "Beginner": "#cd7f32",      # Bronze
            "Intermediate": "#94a3b8",  # Silver
            "Advanced": "#f59e0b",      # Gold
            "Weekly": "#a855f7",        # Purple
        }.get(self.setup.difficulty, "#38bdf8")

        lbl_diff = QLabel(self.setup.difficulty.upper(), self)
        lbl_diff.setStyleSheet(
            f"background-color: #1e293b; color: {diff_color}; font-weight: bold; "
            f"font-size: 10px; padding: 2px 6px; border-radius: 4px; border: 1px solid {diff_color};"
        )
        h_row.addWidget(lbl_diff)

        lbl_dur = QLabel(f"⏱️ {self.setup.race_length_min} min ({self.setup.setup_type.capitalize()})", self)
        lbl_dur.setStyleSheet("color: #64748b; font-size: 11px;")
        h_row.addWidget(lbl_dur)

        layout.addLayout(h_row)

        # Notification Toggles Row
        notif_row = QHBoxLayout()
        notif_row.setSpacing(12)

        lbl_alerts = QLabel("Alertes Vocales :", self)
        lbl_alerts.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 500;")
        notif_row.addWidget(lbl_alerts)

        self.chk_15m = QCheckBox("15 min (Inscriptions)", self)
        self.chk_15m.setChecked(self.setup.notify_15m)
        self.chk_15m.toggled.connect(lambda c: self._set_attr("notify_15m", c))
        notif_row.addWidget(self.chk_15m)

        self.chk_10m = QCheckBox("10 min", self)
        self.chk_10m.setChecked(self.setup.notify_10m)
        self.chk_10m.toggled.connect(lambda c: self._set_attr("notify_10m", c))
        notif_row.addWidget(self.chk_10m)

        self.chk_5m = QCheckBox("5 min (Appel Final)", self)
        self.chk_5m.setChecked(self.setup.notify_5m)
        self.chk_5m.toggled.connect(lambda c: self._set_attr("notify_5m", c))
        notif_row.addWidget(self.chk_5m)

        self.chk_1m = QCheckBox("1 min", self)
        self.chk_1m.setChecked(self.setup.notify_1m)
        self.chk_1m.toggled.connect(lambda c: self._set_attr("notify_1m", c))
        notif_row.addWidget(self.chk_1m)

        self.chk_start = QCheckBox("Race Start", self)
        self.chk_start.setChecked(self.setup.notify_start)
        self.chk_start.toggled.connect(lambda c: self._set_attr("notify_start", c))
        notif_row.addWidget(self.chk_start)

        notif_row.addStretch()

        # Test Voice Button
        btn_test = QPushButton("▶ Test Voice", self)
        btn_test.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        btn_test.clicked.connect(self._test_voice)
        notif_row.addWidget(btn_test)

        layout.addLayout(notif_row)

    def _on_enable_toggled(self, checked: bool) -> None:
        self.setup.enabled = checked
        if checked and not (self.setup.notify_15m or self.setup.notify_10m or self.setup.notify_5m or self.setup.notify_1m or self.setup.notify_start):
            # Activate 5m reminder by default upon selection
            self.setup.notify_5m = True
            self.chk_5m.blockSignals(True)
            self.chk_5m.setChecked(True)
            self.chk_5m.blockSignals(False)
        self.setup_updated.emit(self.setup.setup_id)

    def _set_attr(self, attr_name: str, value: bool) -> None:
        setattr(self.setup, attr_name, value)
        if value and not self.setup.enabled:
            self.setup.enabled = True
            self.chk_enable.blockSignals(True)
            self.chk_enable.setChecked(True)
            self.chk_enable.blockSignals(False)
        self.setup_updated.emit(self.setup.setup_id)

    def _test_voice(self) -> None:
        sound_key = self.setup.sound_key or clean_series_key(self.setup.series_name)
        AudioAnnouncer.play_phrase(sound_key, interrupt=True, text=self.setup.series_name)


# =============================================================================
# LMU Paddock Studio Tab Widget
# =============================================================================

class PaddockAgentWidget(QWidget):
    """Studio Console Tab for LMU Paddock Agent with persistent filters and live countdown schedule."""

    def __init__(self, plugin: "PaddockAgentPlugin", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.plugin = plugin
        self.schedule_mgr = plugin.schedule_mgr

        self._init_ui()
        self._load_saved_filters()
        self._refresh_schedule_view()

        # Real-time countdown timer (1 Hz)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_timer_tick)
        self._timer.start()

    def _init_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(12)

        # ── 1. Top Header & Master Controls ──
        top_group = QGroupBox("📢 LMU Paddock Agent — Voice Announcer & Official Race Schedules", self)
        top_layout = QVBoxLayout(top_group)

        row1 = QHBoxLayout()

        # Master Toggle
        self.chk_master = QCheckBox("Paddock Agent Active", top_group)
        self.chk_master.setStyleSheet("font-weight: bold; font-size: 14px; color: #38bdf8;")
        self.chk_master.setChecked(self.plugin.config.master_enabled)
        self.chk_master.toggled.connect(self._on_master_toggled)
        row1.addWidget(self.chk_master)

        row1.addSpacing(15)

        # Voice audio toggle
        self.chk_voice = QCheckBox("Voice Alerts (FIFO)", top_group)
        self.chk_voice.setChecked(self.plugin.config.voice_enabled)
        self.chk_voice.toggled.connect(self._on_voice_toggled)
        row1.addWidget(self.chk_voice)

        row1.addSpacing(15)

        # OS Notification toggle
        self.chk_os_notif = QCheckBox("Desktop Notifications", top_group)
        self.chk_os_notif.setChecked(self.plugin.config.desktop_notif)
        self.chk_os_notif.toggled.connect(self._on_os_notif_toggled)
        row1.addWidget(self.chk_os_notif)

        row1.addSpacing(20)

        # API Status Badge
        self.lbl_api_status = QLabel("🟢 API : Online", top_group)
        self.lbl_api_status.setStyleSheet("color: #34d399; font-size: 12px; font-weight: bold;")
        row1.addWidget(self.lbl_api_status)

        self.btn_sync = QPushButton("🔄 Sync API", top_group)
        self.btn_sync.clicked.connect(self._sync_api)
        row1.addWidget(self.btn_sync)

        row1.addStretch()

        # Quick Actions
        btn_enable_all = QPushButton("⚡ Enable All (5m)", top_group)
        btn_enable_all.clicked.connect(self._enable_all_5m)
        row1.addWidget(btn_enable_all)

        btn_clear_all = QPushButton("❌ Clear All", top_group)
        btn_clear_all.clicked.connect(self._clear_all_setups)
        row1.addWidget(btn_clear_all)

        btn_clear_audio = QPushButton("⏹ Clear Audio Queue", top_group)
        btn_clear_audio.setStyleSheet("background-color: #7f1d1d; border: 1px solid #ef4444;")
        btn_clear_audio.clicked.connect(AudioAnnouncer.clear_queue)
        row1.addWidget(btn_clear_audio)

        top_layout.addLayout(row1)
        root_layout.addWidget(top_group)

        # ── 2. Persistent Filter Bar ──
        filter_group = QGroupBox("🔍 Persisted View Filters", self)
        f_layout = QHBoxLayout(filter_group)
        f_layout.setSpacing(12)

        # 1. Driver Level / Difficulty
        f_layout.addWidget(QLabel("Driver Level :", filter_group))
        self.combo_diff = QComboBox(filter_group)
        self.combo_diff.addItem("All Levels", "All")
        self.combo_diff.addItem("Beginner (Bronze)", "Beginner")
        self.combo_diff.addItem("Intermediate (Silver)", "Intermediate")
        self.combo_diff.addItem("Advanced (Gold)", "Advanced")
        self.combo_diff.addItem("Weekly (Special)", "Weekly")
        self.combo_diff.currentIndexChanged.connect(self._on_filter_changed)
        f_layout.addWidget(self.combo_diff)

        # 2. Car Category
        f_layout.addWidget(QLabel("Category :", filter_group))
        self.combo_car = QComboBox(filter_group)
        self.combo_car.addItem("All Categories", "All")
        self.combo_car.addItem("GT3 / LMGT3", "GT3")
        self.combo_car.addItem("LMP2 (ELMS)", "LMP2")
        self.combo_car.addItem("Hypercar (HYP)", "Hypercar")
        self.combo_car.addItem("LMP3", "LMP3")
        self.combo_car.addItem("GTE", "GTE")
        self.combo_car.addItem("Multi-Class", "Multi-Class")
        self.combo_car.currentIndexChanged.connect(self._on_filter_changed)
        f_layout.addWidget(self.combo_car)

        # 3. Race Type / Setup
        f_layout.addWidget(QLabel("Format :", filter_group))
        self.combo_type = QComboBox(filter_group)
        self.combo_type.addItem("All Formats", "All")
        self.combo_type.addItem("Daily Races", "Daily Races")
        self.combo_type.addItem("Weekly Races", "Weekly Races")
        self.combo_type.addItem("Setup Fixed", "Fixed Setup")
        self.combo_type.addItem("Setup Open", "Open Setup")
        self.combo_type.currentIndexChanged.connect(self._on_filter_changed)
        f_layout.addWidget(self.combo_type)

        # 4. Only Subscribed
        self.chk_active_only = QCheckBox("Subscribed Only", filter_group)
        self.chk_active_only.setChecked(self.plugin.config.filter_active_only)
        self.chk_active_only.toggled.connect(self._on_filter_changed)
        f_layout.addWidget(self.chk_active_only)

        # 5. Search Box
        self.search_box = QLineEdit(filter_group)
        self.search_box.setPlaceholderText("Search circuit or series...")
        self.search_box.setText(self.plugin.config.search_query)
        self.search_box.textChanged.connect(self._on_filter_changed)
        f_layout.addWidget(self.search_box, 1)

        # Reset filters button
        btn_reset_filters = QPushButton("Reset Filters", filter_group)
        btn_reset_filters.clicked.connect(self._reset_filters)
        f_layout.addWidget(btn_reset_filters)

        root_layout.addWidget(filter_group)

        # ── 3. Sub-Tabs: Live Schedule Table vs Subscriptions Setup Manager ──
        self.sub_tabs = QTabWidget(self)

        # Tab 1: Live Departures Schedule
        self.tab_schedule = QWidget()
        sched_layout = QVBoxLayout(self.tab_schedule)
        sched_layout.setContentsMargins(4, 8, 4, 4)

        self.table_events = QTableWidget(self.tab_schedule)
        self.table_events.setColumnCount(8)
        self.table_events.setHorizontalHeaderLabels([
            "Status & Countdown", "Level", "Series & Format", "Classes",
            "Circuit", "Duration", "Schedule (Reg / Start)", "Alert"
        ])
        self.table_events.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_events.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_events.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table_events.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_events.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table_events.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table_events.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.table_events.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        self.table_events.setStyleSheet(
            "QTableWidget { background-color: #0b0f19; color: #f8fafc; gridline-color: #1e293b; } "
            "QTableWidget::item { padding: 4px; }"
        )
        sched_layout.addWidget(self.table_events)
        self.sub_tabs.addTab(self.tab_schedule, "📅 Upcoming Departures & Live Countdowns")

        # Tab 2: Series Setup Subscriptions & Alert Preferences
        self.tab_setups = QWidget()
        setups_root_layout = QVBoxLayout(self.tab_setups)
        setups_root_layout.setContentsMargins(4, 8, 4, 4)

        self.setups_scroll = QScrollArea(self.tab_setups)
        self.setups_scroll.setWidgetResizable(True)
        self.setups_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.setups_content = QWidget()
        self.setups_layout = QVBoxLayout(self.setups_content)
        self.setups_layout.setSpacing(8)
        self.setups_scroll.setWidget(self.setups_content)
        setups_root_layout.addWidget(self.setups_scroll)

        self.sub_tabs.addTab(self.tab_setups, "⚙️ Series Manager & Voice Alerts")

        root_layout.addWidget(self.sub_tabs, 1)

    def _load_saved_filters(self) -> None:
        """Restores persisted filter selections from typed configuration."""
        cfg = self.plugin.config

        # Difficulty
        idx = self.combo_diff.findData(cfg.filter_difficulty)
        if idx != -1:
            self.combo_diff.setCurrentIndex(idx)

        # Car Class
        idx = self.combo_car.findData(cfg.filter_car_class)
        if idx != -1:
            self.combo_car.setCurrentIndex(idx)

        # Race Type
        idx = self.combo_type.findData(cfg.filter_race_type)
        if idx != -1:
            self.combo_type.setCurrentIndex(idx)

        # Active Only
        self.chk_active_only.setChecked(cfg.filter_active_only)
        self.search_box.setText(cfg.search_query)

    def _on_filter_changed(self) -> None:
        """Persists filter preferences and immediately filters table and setups view."""
        self.plugin.config.filter_difficulty = self.combo_diff.currentData() or "All"
        self.plugin.config.filter_car_class = self.combo_car.currentData() or "All"
        self.plugin.config.filter_race_type = self.combo_type.currentData() or "All"
        self.plugin.config.filter_active_only = self.chk_active_only.isChecked()
        self.plugin.config.search_query = self.search_box.text().strip()
        self.plugin.save_config()

        self._refresh_schedule_view()
        self._refresh_setups_view()

    def _reset_filters(self) -> None:
        self.combo_diff.setCurrentIndex(0)
        self.combo_car.setCurrentIndex(0)
        self.combo_type.setCurrentIndex(0)
        self.chk_active_only.setChecked(False)
        self.search_box.clear()

    def _matches_filters(self, difficulty: str, car_classes: str, race_type: str, setup_type: str, series_name: str, circuit: str, enabled: bool) -> bool:
        """Evaluates whether an event or setup matches all active persisted filters."""
        f_diff = self.plugin.config.filter_difficulty
        f_car = self.plugin.config.filter_car_class
        f_type = self.plugin.config.filter_race_type
        f_act = self.plugin.config.filter_active_only
        f_query = self.plugin.config.search_query.lower()

        # 1. Active Only
        if f_act and not enabled:
            return False

        # 2. Difficulty Filter
        if f_diff != "All":
            if f_diff.lower() not in difficulty.lower() and not (f_diff == "Weekly" and "weekly" in race_type.lower()):
                return False

        # 3. Car Class Filter
        if f_car != "All":
            car_lower = car_classes.lower()
            if f_car == "GT3" and "gt3" not in car_lower:
                return False
            elif f_car == "LMP2" and "lmp2" not in car_lower:
                return False
            elif f_car == "Hypercar" and ("hyp" not in car_lower and "hypercar" not in car_lower):
                return False
            elif f_car == "LMP3" and "lmp3" not in car_lower:
                return False
            elif f_car == "GTE" and "gte" not in car_lower:
                return False
            elif f_car == "Multi-Class" and ("," not in car_classes and "/" not in car_classes):
                return False

        # 4. Race Type Filter
        if f_type != "All":
            if f_type == "Daily Races" and "daily" not in race_type.lower():
                return False
            elif f_type == "Weekly Races" and "weekly" not in race_type.lower():
                return False
            elif f_type == "Fixed Setup" and setup_type.lower() != "fixed":
                return False
            elif f_type == "Open Setup" and setup_type.lower() != "open":
                return False

        # 5. Search Text Query
        if f_query:
            combined_txt = f"{series_name} {circuit} {car_classes} {difficulty}".lower()
            if f_query not in combined_txt:
                return False

        return True

    def _refresh_schedule_view(self) -> None:
        """Updates chronological events table based on current time and filters."""
        events = self.schedule_mgr.get_upcoming_events()
        now = time.time()

        # Filter events
        filtered: List[RaceEvent] = []
        for ev in events:
            setup = self.schedule_mgr.setups.get(ev.setup_id)
            is_enabled = setup.enabled if setup else False
            ev_race_type = ev.race_type
            if self._matches_filters(
                ev.difficulty, ev.car_classes, ev_race_type, ev.setup_type,
                ev.series_name, ev.track_name, is_enabled
            ):
                filtered.append(ev)


        self.table_events.setRowCount(len(filtered))

        for row, ev in enumerate(filtered):
            setup = self.schedule_mgr.setups.get(ev.setup_id)
            is_subbed = setup.enabled if setup else False

            # 1. Status & Countdown
            item_cd = QTableWidgetItem(f"⏳ {ev.countdown_str}")
            if ev.time_until_start <= 900 and ev.time_until_start > 0:
                item_cd.setForeground(QColor("#22c55e"))  # Green (Registration Open)
            elif ev.time_until_start > 900:
                item_cd.setForeground(QColor("#38bdf8"))  # Blue (Upcoming)
            else:
                item_cd.setForeground(QColor("#f59e0b"))  # Orange (In Progress)
            item_cd.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_cd.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            self.table_events.setItem(row, 0, item_cd)

            # 2. Level Badge
            diff_color = {
                "Beginner": "#cd7f32",
                "Intermediate": "#94a3b8",
                "Advanced": "#f59e0b",
                "Weekly": "#a855f7",
            }.get(ev.difficulty, "#38bdf8")
            item_diff = QTableWidgetItem(ev.difficulty)
            item_diff.setForeground(QColor(diff_color))
            item_diff.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_diff.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            self.table_events.setItem(row, 1, item_diff)

            # 3. Series Name & Format
            item_series = QTableWidgetItem(f"{ev.series_name}\n({ev.race_type})")
            self.table_events.setItem(row, 2, item_series)

            # 4. Classes
            item_cls = QTableWidgetItem(ev.car_classes)
            item_cls.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_events.setItem(row, 3, item_cls)

            # 5. Circuit
            item_trk = QTableWidgetItem(ev.track_name)
            self.table_events.setItem(row, 4, item_trk)

            # 6. Length
            item_dur = QTableWidgetItem(f"{ev.race_length_min}m ({ev.setup_type})")
            item_dur.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_events.setItem(row, 5, item_dur)

            # 7. Times (Inscr / Start)
            item_times = QTableWidgetItem(f"{ev.reg_open_time_str} / {ev.start_time_str}")
            item_times.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_events.setItem(row, 6, item_times)

            # 8. Subscription Toggle Button
            btn_sub = QPushButton("🔔 Subscribed" if is_subbed else "🔕 Inactive")
            if is_subbed:
                btn_sub.setStyleSheet("background-color: #064e3b; color: #34d399; font-weight: bold;")
            else:
                btn_sub.setStyleSheet("background-color: #1e293b; color: #94a3b8;")
            btn_sub.clicked.connect(lambda _, s_id=ev.setup_id: self._toggle_subscription(s_id))
            self.table_events.setCellWidget(row, 7, btn_sub)

    def _refresh_setups_view(self) -> None:
        """Populates the Series Setup subscription cards list."""
        # Clear existing cards
        while self.setups_layout.count() > 0:
            child = self.setups_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        setups = list(self.schedule_mgr.setups.values())
        for sp in setups:
            if self._matches_filters(
                sp.difficulty, sp.car_classes, sp.race_type, sp.setup_type,
                sp.series_name, sp.circuit, sp.enabled
            ):
                card = SeriesSetupCardWidget(sp, self.setups_content)
                card.setup_updated.connect(self._on_setup_card_updated)
                self.setups_layout.addWidget(card)

        self.setups_layout.addStretch()

    def _on_setup_card_updated(self, setup_id: str) -> None:
        self.plugin.save_config()
        self._refresh_schedule_view()

    def _toggle_subscription(self, setup_id: str) -> None:
        setup = self.schedule_mgr.setups.get(setup_id)
        if setup:
            setup.enabled = not setup.enabled
            if setup.enabled and not (setup.notify_15m or setup.notify_10m or setup.notify_5m or setup.notify_1m or setup.notify_start):
                setup.notify_5m = True
            self.plugin.save_config()
            self._refresh_schedule_view()
            self._refresh_setups_view()

    def _on_timer_tick(self) -> None:
        """Executes every second to update countdowns and trigger voice announcements."""
        now = time.time()
        # 1. Trigger voice alert checks
        if self.plugin.config.master_enabled:
            self.schedule_mgr.check_notifications(now)

        # 2. Refresh schedule table countdowns if visible
        if self.isVisible() and self.sub_tabs.currentIndex() == 0:
            self._refresh_schedule_view()

    def _sync_api(self) -> None:
        self.lbl_api_status.setText("⏳ Syncing API...")
        self.worker = ApiSyncWorker(self.schedule_mgr, self)
        self.worker.sync_finished.connect(self._on_sync_finished)
        self.worker.start()

    def _on_sync_finished(self, ok: bool, msg: str) -> None:
        self.lbl_api_status.setText(f"{'🟢' if ok else '🟡'} API : {msg}")
        self._refresh_schedule_view()
        self._refresh_setups_view()

    def _enable_all_5m(self) -> None:
        for sp in self.schedule_mgr.setups.values():
            sp.enabled = True
            sp.notify_5m = True
        self.plugin.save_config()
        self._refresh_schedule_view()
        self._refresh_setups_view()

    def _clear_all_setups(self) -> None:
        for sp in self.schedule_mgr.setups.values():
            sp.enabled = False
            sp.notify_15m = False
            sp.notify_10m = False
            sp.notify_5m = False
            sp.notify_1m = False
            sp.notify_start = False
        self.plugin.save_config()
        self._refresh_schedule_view()
        self._refresh_setups_view()

    def _on_master_toggled(self, checked: bool) -> None:
        self.plugin.config.master_enabled = checked
        self.schedule_mgr.master_enabled = checked
        self.plugin.save_config()

    def _on_voice_toggled(self, checked: bool) -> None:
        self.plugin.config.voice_enabled = checked
        self.schedule_mgr.audio_enabled = checked
        self.plugin.save_config()

    def _on_os_notif_toggled(self, checked: bool) -> None:
        self.plugin.config.desktop_notif = checked
        self.schedule_mgr.desktop_notifications_enabled = checked
        self.plugin.save_config()


# =============================================================================
# LMU Paddock Agent Plugin Definition
# =============================================================================

class PaddockAgentPlugin(SimPulsePlugin, ITabProvider):
    """
    SimPulse Builtin Plugin for LMU Paddock Agent & Online Race Schedule.
    """

    def __init__(self, schedule_mgr: Optional[LMUScheduleManager] = None):
        super().__init__(PluginMetadata(
            id="simpulse.builtin.paddock_agent",
            name="LMU Paddock Agent",
            version="2.0.0",
            author="SimPulse Team",
            description="LMU Official Online Racing Schedule, Voice Announcements, and Live Paddock Dispatcher with persistent category & skill filters.",
            icon="🏁",
            tags=("schedule", "paddock", "races", "lmu", "online", "announcer", "voice", "filters")
        ))
        self.config: PaddockAgentConfig = PaddockAgentConfig()
        # Injectable for tests: LMUScheduleManager() (the default) reads AND
        # WRITES the real user's schedule_config.json at the repo root and
        # kicks off a real network fetch (auto_fetch=True) — never construct
        # PaddockAgentPlugin() bare in a test; pass a tmp-path-backed,
        # auto_fetch=False instance instead (see test_paddock_agent_plugin.py).
        self.schedule_mgr: LMUScheduleManager = schedule_mgr if schedule_mgr is not None else LMUScheduleManager()
        self._active_tab_widget: Optional[PaddockAgentWidget] = None

    def on_load(self, context: PluginContext) -> None:
        super().on_load(context)
        self.config = context.get_typed_config(PaddockAgentConfig)

        # Apply configuration to schedule manager
        self.schedule_mgr.master_enabled = self.config.master_enabled
        self.schedule_mgr.audio_enabled = self.config.voice_enabled
        self.schedule_mgr.desktop_notifications_enabled = self.config.desktop_notif

        # Restore per-setup notification preferences
        if self.config.setup_configs:
            for s_id, s_data in self.config.setup_configs.items():
                if s_id in self.schedule_mgr.setups and isinstance(s_data, dict):
                    setup = self.schedule_mgr.setups[s_id]
                    setup.enabled = bool(s_data.get("enabled", False))
                    setup.notify_15m = bool(s_data.get("notify_15m", False))
                    setup.notify_10m = bool(s_data.get("notify_10m", False))
                    setup.notify_5m = bool(s_data.get("notify_5m", False))
                    setup.notify_1m = bool(s_data.get("notify_1m", False))
                    setup.notify_start = bool(s_data.get("notify_start", False))

    def save_config(self) -> None:
        if self.context:
            self.config.master_enabled = self.schedule_mgr.master_enabled
            self.config.voice_enabled = self.schedule_mgr.audio_enabled
            self.config.desktop_notif = self.schedule_mgr.desktop_notifications_enabled
            self.config.setup_configs = {
                s_id: sp.to_dict() for s_id, sp in self.schedule_mgr.setups.items()
            }
            self.context.save_typed_config(self.config)

    # ITabProvider Protocol
    def get_tab_title(self) -> str:
        return "LMU Paddock"

    def get_tab_icon(self) -> str:
        return "🏁"

    def create_tab_widget(self, parent: Optional[QWidget] = None) -> QWidget:
        self._active_tab_widget = PaddockAgentWidget(self, parent)
        return self._active_tab_widget
