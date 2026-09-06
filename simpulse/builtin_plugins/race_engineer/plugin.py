"""
SimPulse Plugin — Virtual Race Engineer & Sub-Plugins Orchestrator.
Manages modular sub-plugins (Roles), aggregates channel telemetry requirements,
aggregates and synthesizes voice sound assets, and dispatches data in priority order.
Provides a 3-column Studio Master-Detail layout:
- Left: Sortable & Selectable Sub-Plugins list
- Center: Selected Role Details & Dynamic Configuration Panel
- Right: Aggregated Sound Generation & Live Radio Feed
"""

from __future__ import annotations
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, List, Tuple

from PySide6.QtCore import Qt, QSize, Signal, QObject, QThread, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QGroupBox, QScrollArea, QFrame, QProgressBar,
    QDoubleSpinBox, QSpinBox, QListWidget, QListWidgetItem,
    QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QLineEdit
)

class RadioMessageBridge(QObject):
    """Thread-safe bridge to deliver radio log messages to the GUI."""
    radio_message = Signal(object)


from isimotor_rawudp_client import TelemInfo, FullScoringSession, CompactScoring
from simpulse_sdk import (
    SimPulsePlugin, PluginMetadata, PluginContext,
    ITabProvider, ITelemetrySubscriber, IDeltaSubscriber, ITelemetryStateSubscriber,
    TelemetryChannel, ChannelRequirement, TelemetryRawPacket,
    LapDeltaPacket, VehicleSensors, TelemetryStateStore, TelemetryWakeReason
)
from .base import BaseRole, RoleHostSlot, EngineerMessage, RoleStatus
from .manager import RaceEngineer
from .context import TelemetryTriggerPacket
from .params import RoleParam, BoolParam, IntRangeParam, FloatRangeParam, ParamScalarValue, ParamWidgetFactory
from simpulse.core.utils.audio import AudioAnnouncer
from simpulse.core.utils.audio_baker import AudioBaker, DEFAULT_SOUND_DIR, DEFAULT_MODEL_PATH

logger = logging.getLogger("simpulse.plugin.race_engineer")


@dataclass
class RaceEngineerPluginConfig:
    """Strongly-typed configuration schema for Race Engineer Plugin and its Sub-plugins."""
    master_enabled: bool = True
    muted: bool = False
    subplugin_configs: Dict[str, Dict[str, ParamScalarValue]] = field(default_factory=dict)
    subplugin_order: List[str] = field(default_factory=list)


# =============================================================================
# Background Worker for TTS Sound Baking
# =============================================================================

class SoundBakerWorker(QThread):
    """Background worker to bake sound files without freezing the Qt main event loop."""
    progress = Signal(int, int, str)     # current, total, phrase_key
    finished_baking = Signal(int, int)   # baked_count, skipped_count
    error_occurred = Signal(str)

    def __init__(
        self,
        phrases: Dict[str, str],
        sound_dir: Path,
        model_path: Path,
        force: bool = False,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.phrases = phrases
        self.sound_dir = sound_dir
        self.model_path = model_path
        self.force = force

    def run(self) -> None:
        try:
            self.sound_dir.mkdir(parents=True, exist_ok=True)
            voice = AudioBaker.get_voice(self.model_path)

            to_bake = []
            for k, text in self.phrases.items():
                wav_path = self.sound_dir / f"{k}.wav"
                if not wav_path.exists() or self.force:
                    to_bake.append((k, text, wav_path))

            total = len(to_bake)
            if total == 0:
                self.finished_baking.emit(0, len(self.phrases))
                return

            baked = 0
            for idx, (key, text, wav_path) in enumerate(to_bake, start=1):
                self.progress.emit(idx, total, key)
                AudioBaker.bake_file(text, wav_path, force=True, voice=voice)
                baked += 1

            skipped = len(self.phrases) - baked
            self.finished_baking.emit(baked, skipped)
        except Exception as e:
            logger.error(f"[SoundBakerWorker] Error during audio baking: {e}", exc_info=True)
            self.error_occurred.emit(str(e))


# =============================================================================
# Sound Library Inspector Dialog
# =============================================================================

class SoundLibraryDialog(QDialog):
    """Dialog allowing user to view, test play, and bake all declared sub-plugin sounds."""

    def __init__(self, plugin: "RaceEngineerPlugin", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.plugin = plugin
        self.setWindowTitle("SimPulse Voice Sound Library")
        self.resize(740, 540)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        lbl_info = QLabel("<b>Declared Sub-Plugin Voice Phrases & Sound Assets (Complete List)</b>", self)
        lbl_info.setStyleSheet("font-size: 14px; color: #ffffff;")
        layout.addWidget(lbl_info)

        # Filter bar
        filter_row = QHBoxLayout()
        filter_lbl = QLabel("🔍 Filter:", self)
        filter_lbl.setStyleSheet("color: #94a3b8; font-weight: bold;")
        filter_row.addWidget(filter_lbl)

        self.filter_input = QLineEdit(self)
        self.filter_input.setPlaceholderText("Search phrase key or spoken text...")
        self.filter_input.setStyleSheet("background-color: #0d1117; color: #ffffff; border: 1px solid #30363d; padding: 4px 8px; border-radius: 4px;")
        self.filter_input.textChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self.filter_input)
        layout.addLayout(filter_row)

        self.table = QTableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Phrase Key", "Spoken Text (Piper TTS)", "Disk Status", "Action"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet("background-color: #0d1117; color: #ffffff; gridline-color: #30363d;")
        layout.addWidget(self.table)

        self._populate_table()

        btn_close = QPushButton("Close", self)
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignmentFlag.AlignRight)

    def _on_filter_changed(self, text: str) -> None:
        query = text.strip().lower()
        for row in range(self.table.rowCount()):
            item_k = self.table.item(row, 0)
            item_t = self.table.item(row, 1)
            k_text = item_k.text().lower() if item_k else ""
            t_text = item_t.text().lower() if item_t else ""
            self.table.setRowHidden(row, query not in k_text and query not in t_text)

    def _populate_table(self) -> None:
        sounds = self.plugin.engineer.get_all_sound_requirements(only_enabled=False)
        self.table.setRowCount(len(sounds))

        for row, (key, text) in enumerate(sorted(sounds.items())):
            wav_path = DEFAULT_SOUND_DIR / f"{key}.wav"
            exists = wav_path.exists()

            item_k = QTableWidgetItem(key)
            item_k.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 0, item_k)

            item_t = QTableWidgetItem(text)
            item_t.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 1, item_t)

            status_txt = f"✓ Present ({wav_path.stat().st_size // 1024} KB)" if exists else "✗ Missing"
            item_s = QTableWidgetItem(status_txt)
            item_s.setForeground(Qt.GlobalColor.green if exists else Qt.GlobalColor.red)
            item_s.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, 2, item_s)

            btn_play = QPushButton("▶ Test Play", self.table)
            btn_play.clicked.connect(lambda _, k=key, t=text: self._play_sound(k, t))
            self.table.setCellWidget(row, 3, btn_play)

    def _play_sound(self, phrase_key: str, text: str) -> None:
        AudioAnnouncer.play_phrase(phrase_key, interrupt=True, text=text)


# =============================================================================
# Role List Item Widget (Left Column)
# =============================================================================

class RoleListItemWidget(QWidget):
    """Custom compact widget for a role entry in the left sortable list."""

    enable_toggled = Signal(str, bool)

    def __init__(
        self,
        slot_or_role: Union[RoleHostSlot, BaseRole],
        parent: Optional[QWidget] = None,
        enabled: Optional[bool] = None,
    ):
        super().__init__(parent)
        if isinstance(slot_or_role, RoleHostSlot):
            self.slot = slot_or_role
            self.role = slot_or_role.role
            self._is_enabled = slot_or_role.enabled
        else:
            self.slot = None
            self.role = slot_or_role
            self._is_enabled = enabled if enabled is not None else getattr(slot_or_role, "enabled", True)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # Checkbox
        self.chk_enabled = QCheckBox(self)
        self.chk_enabled.setChecked(self._is_enabled)
        self.chk_enabled.toggled.connect(lambda checked: self.enable_toggled.emit(self.role.role_id, checked))
        layout.addWidget(self.chk_enabled)

        # Role Name
        self.lbl_name = QLabel(self.role.name, self)
        self.lbl_name.setStyleSheet("font-weight: bold; color: #ffffff; font-size: 12px;")
        layout.addWidget(self.lbl_name, stretch=1)

        # Status Pill
        self.lbl_status = QLabel(self.role.status.value, self)
        self.update_status()
        layout.addWidget(self.lbl_status)

    def update_status(self) -> None:
        if self.slot:
            self._is_enabled = self.slot.enabled
        self.chk_enabled.blockSignals(True)
        self.chk_enabled.setChecked(self._is_enabled)
        self.chk_enabled.blockSignals(False)

        if not self._is_enabled:
            self.lbl_status.setText("OFF")
            self.lbl_status.setStyleSheet("background-color: #3e1b1e; color: #f85149; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 10px;")
        elif self.role.is_busy():
            self.lbl_status.setText("BUSY")
            self.lbl_status.setStyleSheet("background-color: #5a3e1b; color: #d29922; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 10px;")
        else:
            self.lbl_status.setText("IDLE")
            self.lbl_status.setStyleSheet("background-color: #1b3e2b; color: #3fb950; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 10px;")

    def set_checked(self, checked: bool) -> None:
        self._is_enabled = checked
        if self.slot:
            self.slot.enabled = checked
        self.chk_enabled.blockSignals(True)
        self.chk_enabled.setChecked(checked)
        self.chk_enabled.blockSignals(False)
        self.update_status()


# =============================================================================
# Center Panel: Role Details & Dynamic Configuration
# =============================================================================

class RoleDetailWidget(QWidget):
    """Detail panel displayed in the center when a role is selected."""

    param_changed = Signal(str, str, object)  # role_id, param_name, new_val
    enable_toggled = Signal(str, bool)

    def __init__(self, plugin: "RaceEngineerPlugin", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.plugin = plugin
        self.current_role: Optional[BaseRole] = None
        self._param_widgets: Dict[str, QWidget] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(14, 14, 14, 14)
        self.layout.setSpacing(12)

        # 1. Role Header Card
        self.header_card = QFrame(self)
        self.header_card.setStyleSheet("background-color: #161b22; border: 1px solid #30363d; border-radius: 8px;")
        h_layout = QVBoxLayout(self.header_card)
        h_layout.setContentsMargins(14, 12, 14, 12)
        h_layout.setSpacing(8)

        title_row = QHBoxLayout()
        self.chk_role_enabled = QCheckBox(self.header_card)
        self.chk_role_enabled.toggled.connect(self._on_enable_toggled)
        title_row.addWidget(self.chk_role_enabled)

        self.lbl_title = QLabel("Select a Role from the list", self.header_card)
        self.lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #58a6ff;")
        title_row.addWidget(self.lbl_title)

        title_row.addStretch()

        self.lbl_status_badge = QLabel("IDLE", self.header_card)
        self.lbl_status_badge.setStyleSheet("background-color: #1b3e2b; color: #3fb950; padding: 3px 8px; border-radius: 4px; font-weight: bold;")
        title_row.addWidget(self.lbl_status_badge)

        h_layout.addLayout(title_row)

        self.lbl_description = QLabel("", self.header_card)
        self.lbl_description.setStyleSheet("color: #8b949e; font-size: 12px;")
        self.lbl_description.setWordWrap(True)
        h_layout.addWidget(self.lbl_description)

        self.layout.addWidget(self.header_card)

        # 2. Live Diagnostics
        self.diag_group = QGroupBox("📊 Live Telemetry Diagnostics", self)
        d_layout = QVBoxLayout(self.diag_group)
        self.lbl_live_diag = QLabel("No active telemetry frame", self.diag_group)
        self.lbl_live_diag.setStyleSheet("color: #58a6ff; font-family: monospace; font-size: 11px;")
        self.lbl_live_diag.setWordWrap(True)
        d_layout.addWidget(self.lbl_live_diag)
        self.layout.addWidget(self.diag_group)

        # 3. Dynamic Parameters
        self.params_group = QGroupBox("⚙️ Configurable Parameters", self)
        self.params_layout = QVBoxLayout(self.params_group)
        self.params_layout.setContentsMargins(12, 12, 12, 12)
        self.params_layout.setSpacing(8)
        self.layout.addWidget(self.params_group)

        # 4. Declared Channel Subscriptions
        self.sub_group = QGroupBox("📡 Declared Channel Subscriptions", self)
        s_layout = QVBoxLayout(self.sub_group)
        self.lbl_sub_info = QLabel("", self.sub_group)
        self.lbl_sub_info.setStyleSheet("color: #7ee787; font-size: 11px;")
        self.lbl_sub_info.setWordWrap(True)
        s_layout.addWidget(self.lbl_sub_info)
        self.layout.addWidget(self.sub_group)

        # 5. Declared Sounds & Audio Assets
        self.sounds_group = QGroupBox("🔊 Declared Voice Sound Assets", self)
        self.sounds_layout = QVBoxLayout(self.sounds_group)
        self.sounds_layout.setContentsMargins(12, 12, 12, 12)
        self.sounds_layout.setSpacing(6)
        self.layout.addWidget(self.sounds_group)

        self.layout.addStretch()

    def set_slot(self, slot: Optional[RoleHostSlot]) -> None:
        """Display details for the given host slot."""
        self.current_slot = slot
        self.set_role(slot.role if slot else None, enabled=slot.enabled if slot else True)

    def set_role(self, role: Optional[BaseRole], enabled: Optional[bool] = None) -> None:
        """Display details for the given role."""
        self.current_role = role
        if enabled is not None:
            self._is_enabled = enabled
        elif hasattr(self, "current_slot") and self.current_slot and self.current_slot.role == role:
            self._is_enabled = self.current_slot.enabled
        elif role and hasattr(self.plugin, "engineer") and self.plugin.engineer.get_slot(role.role_id):
            self._is_enabled = self.plugin.engineer.is_role_enabled(role.role_id)
        else:
            self._is_enabled = getattr(role, "enabled", True)

        if not role:
            self.lbl_title.setText("Select a Role from the list")
            self.lbl_description.setText("")
            self.lbl_status_badge.setText("OFF")
            self.chk_role_enabled.setChecked(False)
            self._clear_params()
            self._clear_sounds()
            self.lbl_sub_info.setText("No role selected.")
            return

        self.chk_role_enabled.blockSignals(True)
        self.chk_role_enabled.setChecked(self._is_enabled)
        self.chk_role_enabled.blockSignals(False)

        self.lbl_title.setText(role.name)
        self.lbl_description.setText(role.description or "No description.")
        self._update_status_badge()

        # Update Subscriptions
        reqs = role.get_channel_requirements()
        if reqs:
            req_lines = [f"• <b>{r.channel.value.upper()}</b> @ {r.preferred_hz} Hz ({'Required' if r.required else 'Optional'}) — <i>{r.reason}</i>" for r in reqs]
            self.lbl_sub_info.setText("<br>".join(req_lines))
        else:
            self.lbl_sub_info.setText("No channel subscription requirements declared.")

        # Build Parameters
        self._build_params(role)

        # Build Sounds
        self._build_sounds(role)

        self.update_live_state()

    def _update_status_badge(self) -> None:
        if not self.current_role:
            return
        if not getattr(self, "_is_enabled", True):
            self.lbl_status_badge.setText("DISABLED")
            self.lbl_status_badge.setStyleSheet("background-color: #3e1b1e; color: #f85149; padding: 3px 8px; border-radius: 4px; font-weight: bold;")
        elif self.current_role.is_busy():
            self.lbl_status_badge.setText("BUSY")
            self.lbl_status_badge.setStyleSheet("background-color: #5a3e1b; color: #d29922; padding: 3px 8px; border-radius: 4px; font-weight: bold;")
        else:
            self.lbl_status_badge.setText("IDLE")
            self.lbl_status_badge.setStyleSheet("background-color: #1b3e2b; color: #3fb950; padding: 3px 8px; border-radius: 4px; font-weight: bold;")

    def _on_enable_toggled(self, checked: bool) -> None:
        self._is_enabled = checked
        if hasattr(self, "current_slot") and self.current_slot:
            self.current_slot.enabled = checked
        if self.current_role:
            self.enable_toggled.emit(self.current_role.role_id, checked)
            self._update_status_badge()

    def _clear_params(self) -> None:
        while self.params_layout.count():
            item = self.params_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()
        self._param_widgets.clear()

    def _build_params(self, role: BaseRole) -> None:
        self._clear_params()
        params = role.get_parameters()
        if not params:
            lbl_none = QLabel("No configurable parameters for this role.", self.params_group)
            lbl_none.setStyleSheet("color: #8b949e; font-style: italic;")
            self.params_layout.addWidget(lbl_none)
            return

        for p in params:
            row = QHBoxLayout()
            row.setSpacing(12)

            label_txt = p.label or p.name
            lbl = QLabel(label_txt, self.params_group)
            lbl.setToolTip(p.description)
            lbl.setMinimumWidth(180)
            lbl.setStyleSheet("color: #c9d1d9; font-size: 12px;")
            row.addWidget(lbl)

            val = role.get_param_value(p.name)

            widget = ParamWidgetFactory.create_widget(
                param=p,
                parent=self.params_group,
                current_value=val,
                on_change=lambda v, name=p.name: self._on_param_changed(name, v),
            )
            if widget:
                self._param_widgets[p.name] = widget
                row.addWidget(widget)

            row.addStretch()
            self.params_layout.addLayout(row)

    def _on_param_changed(self, name: str, val: ParamScalarValue) -> None:
        if self.current_role:
            self.current_role.set_param_value(name, val)
            self.param_changed.emit(self.current_role.role_id, name, val)

    def _clear_sounds(self) -> None:
        while self.sounds_layout.count():
            item = self.sounds_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()

    def _build_sounds(self, role: BaseRole) -> None:
        self._clear_sounds()
        sounds = role.get_sound_requirements()
        if not sounds:
            lbl_none = QLabel("No voice sounds declared by this role.", self.sounds_group)
            lbl_none.setStyleSheet("color: #8b949e; font-style: italic;")
            self.sounds_layout.addWidget(lbl_none)
            return

        lbl_hdr = QLabel(f"<b>{len(sounds)} Declared Phrases (Complete List):</b>", self.sounds_group)
        lbl_hdr.setStyleSheet("color: #d2a8ff; font-size: 11px;")
        self.sounds_layout.addWidget(lbl_hdr)

        # Show complete list of phrases declared by this role
        for key, text in sorted(sounds.items()):
            row = QHBoxLayout()
            wav_path = DEFAULT_SOUND_DIR / f"{key}.wav"
            exists = wav_path.exists()
            status_icon = "✓" if exists else "✗"
            color = "#7ee787" if exists else "#f85149"

            lbl_phrase = QLabel(f"<span style='color:{color}; font-weight:bold;'>{status_icon}</span> <code>{key}</code> : \"{text}\"", self.sounds_group)
            lbl_phrase.setStyleSheet("font-size: 11px; color: #c9d1d9;")
            row.addWidget(lbl_phrase, stretch=1)

            btn_test = QPushButton("▶ Test", self.sounds_group)
            btn_test.setFixedSize(60, 22)
            btn_test.setStyleSheet("font-size: 10px; padding: 2px;")
            btn_test.clicked.connect(lambda _, k=key, t=text: AudioAnnouncer.play_phrase(k, interrupt=True, text=t))
            row.addWidget(btn_test)

            self.sounds_layout.addLayout(row)

    def update_live_state(self) -> None:
        """Update live status and diagnostic info."""
        if not self.current_role:
            return
        self._update_status_badge()
        summary = self.current_role.get_state_summary()
        items = []
        for k, v in summary.items():
            if k not in ("role_id", "name", "enabled", "priority", "status"):
                items.append(f"<b>{k}</b>: {v}")
        if items:
            self.lbl_live_diag.setText(" | ".join(items))
        else:
            self.lbl_live_diag.setText("Status: Nominal / Ready")


# =============================================================================
# Main Tab Widget for Race Engineer Plugin
# =============================================================================

class RaceEngineerWidget(QWidget):
    """Interactive Studio Tab for the Race Engineer Plugin."""

    def __init__(self, plugin: "RaceEngineerPlugin", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.plugin = plugin
        self._baker_thread: Optional[SoundBakerWorker] = None
        self._init_ui()

        # UI timer on the GUI thread for safe periodic refresh
        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(100)  # 10 Hz refresh
        self._ui_timer.timeout.connect(self.update_live_views)
        self._ui_timer.start()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        # 1. Header Control Bar
        header_card = QFrame(self)
        header_card.setStyleSheet("background-color: #0d1117; border: 1px solid #30363d; border-radius: 8px;")
        h_layout = QHBoxLayout(header_card)
        h_layout.setContentsMargins(14, 10, 14, 10)
        h_layout.setSpacing(14)

        self.chk_master = QCheckBox("VIRTUAL RACE ENGINEER MASTER", header_card)
        self.chk_master.setStyleSheet("font-size: 14px; font-weight: bold; color: #00d2ff;")
        self.chk_master.setChecked(self.plugin.engineer.enabled)
        self.chk_master.toggled.connect(self._on_master_toggled)
        h_layout.addWidget(self.chk_master)

        h_layout.addSpacing(15)

        self.lbl_global_status = QLabel("🟢 ACTIVE", header_card)
        self.lbl_global_status.setStyleSheet("background-color: #1b3e2b; color: #3fb950; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        h_layout.addWidget(self.lbl_global_status)

        self.chk_mute = QCheckBox("Mute Audio", header_card)
        self.chk_mute.setChecked(AudioAnnouncer.is_muted())
        self.chk_mute.toggled.connect(self._on_mute_toggled)
        h_layout.addWidget(self.chk_mute)

        self.btn_clear_queue = QPushButton("🧹 Clear Radio Queue", header_card)
        self.btn_clear_queue.clicked.connect(self._on_clear_queue)
        h_layout.addWidget(self.btn_clear_queue)

        h_layout.addStretch()

        self.lbl_queue_size = QLabel("Queue: 0", header_card)
        self.lbl_queue_size.setStyleSheet("color: #8b949e; font-weight: bold;")
        h_layout.addWidget(self.lbl_queue_size)

        main_layout.addWidget(header_card)

        # 2. Main 3-Column Content Layout
        content_layout = QHBoxLayout()
        content_layout.setSpacing(12)

        # ---------------------------------------------------------------------
        # LEFT COLUMN: Sortable & Selectable Roles List
        # ---------------------------------------------------------------------
        roles_box = QGroupBox("🧩 Sub-Plugins / Roles Hierarchy", self)
        roles_box.setMinimumWidth(300)
        roles_box.setMaximumWidth(360)
        r_layout = QVBoxLayout(roles_box)
        r_layout.setContentsMargins(10, 10, 10, 10)
        r_layout.setSpacing(8)

        # Execution Order Toolbar
        order_bar = QHBoxLayout()
        order_bar.setSpacing(6)
        lbl_order = QLabel("Execution Order:", roles_box)
        lbl_order.setStyleSheet("color: #8b949e; font-size: 11px;")
        order_bar.addWidget(lbl_order)
        order_bar.addStretch()

        self.btn_up = QPushButton("▲ Move Up", roles_box)
        self.btn_up.setToolTip("Move selected role up in execution order")
        self.btn_up.clicked.connect(self._on_move_selected_up)
        order_bar.addWidget(self.btn_up)

        self.btn_down = QPushButton("▼ Move Down", roles_box)
        self.btn_down.setToolTip("Move selected role down in execution order")
        self.btn_down.clicked.connect(self._on_move_selected_down)
        order_bar.addWidget(self.btn_down)

        r_layout.addLayout(order_bar)

        # List Widget
        self.roles_list = QListWidget(roles_box)
        self.roles_list.setStyleSheet(
            "QListWidget { background-color: #0d1117; border: 1px solid #30363d; border-radius: 6px; } "
            "QListWidget::item { padding: 2px; margin: 2px; border-radius: 4px; } "
            "QListWidget::item:selected { background-color: #1f6feb; color: #ffffff; }"
        )
        self.roles_list.currentRowChanged.connect(self._on_role_selected)
        r_layout.addWidget(self.roles_list, stretch=1)

        content_layout.addWidget(roles_box, stretch=3)

        # ---------------------------------------------------------------------
        # CENTER COLUMN: Selected Role Details Panel
        # ---------------------------------------------------------------------
        detail_box = QGroupBox("🔍 Role Details & Configuration", self)
        d_layout = QVBoxLayout(detail_box)
        d_layout.setContentsMargins(0, 0, 0, 0)

        self.detail_scroll = QScrollArea(detail_box)
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.role_detail_widget = RoleDetailWidget(self.plugin, self.detail_scroll)
        self.role_detail_widget.param_changed.connect(self._on_role_param_changed)
        self.role_detail_widget.enable_toggled.connect(self._on_role_enable_toggled)
        self.detail_scroll.setWidget(self.role_detail_widget)

        d_layout.addWidget(self.detail_scroll)
        content_layout.addWidget(detail_box, stretch=5)

        # ---------------------------------------------------------------------
        # RIGHT COLUMN: Aggregated Sound Assets & Live Radio Feed
        # ---------------------------------------------------------------------
        right_container = QWidget(self)
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        # Right Top: Aggregated Needs & TTS Sound Baker
        needs_group = QGroupBox("⚙️ Aggregated Sounds & Telemetry", right_container)
        n_layout = QVBoxLayout(needs_group)
        n_layout.setContentsMargins(12, 10, 12, 10)
        n_layout.setSpacing(8)

        lbl_ch_title = QLabel("📡 <b>Aggregated Telemetry Subscriptions:</b>", needs_group)
        lbl_ch_title.setStyleSheet("color: #7ee787; font-size: 11px;")
        n_layout.addWidget(lbl_ch_title)

        self.lbl_channels_summary = QLabel("Calculating requirements...", needs_group)
        self.lbl_channels_summary.setStyleSheet("color: #c9d1d9; font-size: 11px;")
        self.lbl_channels_summary.setWordWrap(True)
        n_layout.addWidget(self.lbl_channels_summary)

        n_layout.addSpacing(4)

        lbl_snd_title = QLabel("🎙️ <b>Sub-Plugins Sound Assets (TTS):</b>", needs_group)
        lbl_snd_title.setStyleSheet("color: #d2a8ff; font-size: 11px;")
        n_layout.addWidget(lbl_snd_title)

        self.lbl_sounds_summary = QLabel("Scanning sound assets...", needs_group)
        self.lbl_sounds_summary.setStyleSheet("color: #c9d1d9; font-size: 11px;")
        n_layout.addWidget(self.lbl_sounds_summary)

        btn_row = QHBoxLayout()
        self.btn_bake_sounds = QPushButton("🚀 Bake Missing Sounds", needs_group)
        self.btn_bake_sounds.setStyleSheet("background-color: #238636; color: #ffffff; font-weight: bold; padding: 5px 10px;")
        self.btn_bake_sounds.clicked.connect(self._on_bake_sounds_clicked)
        btn_row.addWidget(self.btn_bake_sounds)

        self.btn_view_sounds = QPushButton("📋 Complete Audio List...", needs_group)
        self.btn_view_sounds.setToolTip("View and test the complete list of all declared audio phrases across all sub-plugins")
        self.btn_view_sounds.clicked.connect(self._open_sound_library)
        btn_row.addWidget(self.btn_view_sounds)
        n_layout.addLayout(btn_row)

        self.progress_bake = QProgressBar(needs_group)
        self.progress_bake.setVisible(False)
        self.progress_bake.setFixedHeight(12)
        n_layout.addWidget(self.progress_bake)

        right_layout.addWidget(needs_group)

        # Right Bottom: Live Radio Announcements Feed
        radio_box = QGroupBox("📻 Live Radio Announcements Feed", right_container)
        r_layout = QVBoxLayout(radio_box)
        r_layout.setContentsMargins(10, 10, 10, 10)
        self.radio_list = QListWidget(radio_box)
        self.radio_list.setStyleSheet(
            "QListWidget { background-color: #0d1117; color: #38bdf8; font-family: monospace; font-size: 11px; border: 1px solid #30363d; border-radius: 6px; }"
        )
        r_layout.addWidget(self.radio_list)
        right_layout.addWidget(radio_box, stretch=1)

        content_layout.addWidget(right_container, stretch=4)
        main_layout.addLayout(content_layout, stretch=1)

        self._build_roles_list()
        self._update_needs_summary()

    # =========================================================================
    # Roles List Rebuilding & Selection
    # =========================================================================

    def _build_roles_list(self, keep_selected_id: Optional[str] = None) -> None:
        """Populate the left roles list in current priority order."""
        sel_id = keep_selected_id
        if sel_id is None and self.roles_list.currentItem():
            row = self.roles_list.currentRow()
            slots = self.plugin.engineer.get_slots()
            if 0 <= row < len(slots):
                sel_id = slots[row].role_id

        self.roles_list.clear()
        slots = self.plugin.engineer.get_slots()

        target_row = 0
        for row, slot in enumerate(slots):
            item = QListWidgetItem(self.roles_list)
            item.setSizeHint(QSize(280, 42))

            widget = RoleListItemWidget(slot, self.roles_list)
            widget.enable_toggled.connect(self._on_role_enable_toggled)
            self.roles_list.setItemWidget(item, widget)

            if sel_id and slot.role_id == sel_id:
                target_row = row

        if slots:
            self.roles_list.setCurrentRow(target_row)
            self.role_detail_widget.set_slot(slots[target_row])
        else:
            self.role_detail_widget.set_slot(None)

    def _on_role_selected(self, row: int) -> None:
        slots = self.plugin.engineer.get_slots()
        if 0 <= row < len(slots):
            self.role_detail_widget.set_slot(slots[row])
        else:
            self.role_detail_widget.set_slot(None)

    def _on_move_selected_up(self) -> None:
        row = self.roles_list.currentRow()
        roles = self.plugin.engineer.get_roles()
        if 0 <= row < len(roles):
            role_id = roles[row].role_id
            if self.plugin.engineer.move_role_up(role_id):
                self.plugin.save_plugin_config()
                self._build_roles_list(keep_selected_id=role_id)
                self._update_needs_summary()

    def _on_move_selected_down(self) -> None:
        row = self.roles_list.currentRow()
        roles = self.plugin.engineer.get_roles()
        if 0 <= row < len(roles):
            role_id = roles[row].role_id
            if self.plugin.engineer.move_role_down(role_id):
                self.plugin.save_plugin_config()
                self._build_roles_list(keep_selected_id=role_id)
                self._update_needs_summary()

    def _on_role_enable_toggled(self, role_id: str, enabled: bool) -> None:
        self.plugin.engineer.set_role_enabled(role_id, enabled)
        self.plugin.save_plugin_config()
        self._refresh_list_item_statuses()
        self.role_detail_widget.update_live_state()
        self._update_needs_summary()

    def _on_role_param_changed(self, role_id: str, param_name: str, val: ParamScalarValue) -> None:
        self.plugin.save_plugin_config()

    def _refresh_list_item_statuses(self) -> None:
        for row in range(self.roles_list.count()):
            item = self.roles_list.item(row)
            w = self.roles_list.itemWidget(item)
            if isinstance(w, RoleListItemWidget):
                w.update_status()

    # =========================================================================
    # Header & Status Handlers
    # =========================================================================

    def _on_master_toggled(self, checked: bool) -> None:
        self.plugin.engineer.set_master_enabled(checked)
        self.plugin.save_plugin_config()
        self._update_global_status()

    def _on_mute_toggled(self, checked: bool) -> None:
        AudioAnnouncer.set_muted(checked)
        self.plugin.save_plugin_config()

    def _on_clear_queue(self) -> None:
        AudioAnnouncer.clear_queue()
        AudioAnnouncer.stop_current()

    def _update_global_status(self) -> None:
        if not self.plugin.engineer.enabled:
            self.lbl_global_status.setText("🔴 DISABLED")
            self.lbl_global_status.setStyleSheet("background-color: #3e1b1e; color: #f85149; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        elif self.plugin.engineer.is_any_role_busy():
            busy_names = ", ".join(r.name for r in self.plugin.engineer.get_busy_roles())
            self.lbl_global_status.setText(f"🟡 BUSY ({busy_names})")
            self.lbl_global_status.setStyleSheet("background-color: #5a3e1b; color: #d29922; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        else:
            self.lbl_global_status.setText("🟢 ACTIVE")
            self.lbl_global_status.setStyleSheet("background-color: #1b3e2b; color: #3fb950; padding: 4px 10px; border-radius: 4px; font-weight: bold;")

    def _update_needs_summary(self) -> None:
        """Refresh aggregated channel requirements and sound status."""
        reqs = self.plugin.get_channel_requirements()
        if reqs:
            req_lines = [f"• <b>{r.channel.value.upper()}</b> @ {r.preferred_hz} Hz ({'Required' if r.required else 'Optional'})" for r in reqs]
            self.lbl_channels_summary.setText("<br>".join(req_lines))
        else:
            self.lbl_channels_summary.setText("No active channel requirements.")

        all_sounds = self.plugin.engineer.get_all_sound_requirements(only_enabled=False)
        missing = self.plugin.engineer.get_missing_sounds(only_enabled=False)
        present_count = len(all_sounds) - len(missing)
        self.lbl_sounds_summary.setText(
            f"<b>{present_count} / {len(all_sounds)}</b> voice files present on disk (<b>{len(missing)}</b> missing)."
        )
        self.btn_bake_sounds.setEnabled(len(missing) > 0)
        if len(missing) == 0:
            self.btn_bake_sounds.setText("✓ All Sounds Baked")
        else:
            self.btn_bake_sounds.setText(f"🚀 Bake Missing Sounds ({len(missing)})")

    def _open_sound_library(self) -> None:
        dlg = SoundLibraryDialog(self.plugin, self)
        dlg.exec()

    def _on_bake_sounds_clicked(self) -> None:
        all_sounds = self.plugin.engineer.get_all_sound_requirements(only_enabled=False)
        self.progress_bake.setVisible(True)
        self.progress_bake.setRange(0, 100)
        self.progress_bake.setValue(0)
        self.btn_bake_sounds.setEnabled(False)

        self._baker_thread = SoundBakerWorker(
            phrases=all_sounds,
            sound_dir=DEFAULT_SOUND_DIR,
            model_path=DEFAULT_MODEL_PATH,
            force=False,
            parent=self
        )
        self._baker_thread.progress.connect(self._on_baker_progress)
        self._baker_thread.finished_baking.connect(self._on_baker_finished)
        self._baker_thread.error_occurred.connect(self._on_baker_error)
        self._baker_thread.start()

    def _on_baker_progress(self, current: int, total: int, phrase_key: str) -> None:
        pct = int((current / max(1, total)) * 100)
        self.progress_bake.setValue(pct)
        self.btn_bake_sounds.setText(f"Baking ({current}/{total}): {phrase_key}...")

    def _on_baker_finished(self, baked: int, skipped: int) -> None:
        self.progress_bake.setVisible(False)
        self._update_needs_summary()
        if self.role_detail_widget.current_role:
            self.role_detail_widget._build_sounds(self.role_detail_widget.current_role)
        QMessageBox.information(
            self,
            "Sound Generation Complete",
            f"Voice audio generation complete!\n\n• Generated : {baked}\n• Cached/Skipped : {skipped}"
        )

    def _on_baker_error(self, err: str) -> None:
        self.progress_bake.setVisible(False)
        self._update_needs_summary()
        QMessageBox.warning(
            self,
            "Sound Generation Warning",
            f"Piper TTS synthesis could not be completed:\n{err}\n\nNote: Missing phrases will be synthesized on-demand."
        )

    def add_radio_log(self, msg: EngineerMessage) -> None:
        """Add message to the live radio activity feed."""
        t_str = time.strftime("%H:%M:%S", time.localtime(msg.timestamp))
        role_tag = f"[{msg.role_id}]" if msg.role_id else "[Engineer]"
        int_tag = "⚡ INTERRUPT" if msg.interrupt else "QUEUE"
        item_text = f"{t_str} {role_tag} » \"{msg.phrase_key}\" ({int_tag})"

        item = QListWidgetItem(item_text)
        if msg.interrupt:
            item.setForeground(Qt.GlobalColor.yellow)
        else:
            item.setForeground(Qt.GlobalColor.cyan)
        self.radio_list.insertItem(0, item)
        while self.radio_list.count() > 50:
            self.radio_list.takeItem(self.radio_list.count() - 1)

    def update_live_views(self) -> None:
        """Periodic refresh invoked by plugin on telemetry frames."""
        self._update_global_status()
        self.lbl_queue_size.setText(f"Queue: {AudioAnnouncer.get_queue_size()}")
        self._refresh_list_item_statuses()
        self.role_detail_widget.update_live_state()


# =============================================================================
# Main Race Engineer SimPulse Plugin
# =============================================================================

class RaceEngineerPlugin(
    SimPulsePlugin,
    ITabProvider,
    ITelemetrySubscriber,
    IDeltaSubscriber,
    ITelemetryStateSubscriber,
):
    """
    SimPulse Main Race Engineer Plugin.
    Orchestrates Sub-plugins (Roles), aggregates channel & sound requirements,
    and dispatches telemetry and raw packets to all sub-plugins.
    """

    def __init__(self):
        super().__init__(PluginMetadata(
            id="simpulse.builtin.race_engineer",
            name="Virtual Race Engineer & Spotters",
            version="1.0.0",
            author="SimPulse Team",
            description="Modular Virtual Race Engineer orchestrating spotters, pace notes, track limits, and TTS voice audio with sub-plugin subscriptions.",
            icon="🎙️",
            tags=("race_engineer", "spotter", "voice", "audio", "subplugins")
        ))
        self.config = RaceEngineerPluginConfig()
        self.engineer = RaceEngineer(
            audio_engine=AudioAnnouncer,
            auto_load_builtin_roles=True,
            auto_load_config=False,
        )
        self._radio_bridge = RadioMessageBridge()
        self._active_tab_widget: Optional[RaceEngineerWidget] = None
        self._latest_sensors: Optional[VehicleSensors] = None
        self._latest_scoring: Optional[Union[FullScoringSession, CompactScoring]] = None
        self._latest_telemetry: Optional[TelemInfo] = None

    # =========================================================================
    # Aggregated Channel Requirements
    # =========================================================================

    def get_channel_requirements(self) -> List[ChannelRequirement]:
        """
        Aggregates telemetry channel requirements declared by all active sub-plugins.
        Exposes the merged desiderata to SimPulse PluginManager and GamePluginManager.
        """
        return self.engineer.get_channel_requirements()

    # =========================================================================
    # Lifecycle Hooks
    # =========================================================================

    def on_load(self, context: PluginContext) -> None:
        super().on_load(context)
        # Restore configuration
        self.config = context.get_typed_config(RaceEngineerPluginConfig)
        self.engineer.enabled = self.config.master_enabled
        AudioAnnouncer.set_muted(self.config.muted)

        # Restore sub-plugin parameters & priorities from config
        if self.config.subplugin_configs:
            for role_id, r_cfg in self.config.subplugin_configs.items():
                role = self.engineer.get_role(role_id)
                if role and isinstance(r_cfg, dict):
                    role.set_config(r_cfg)

        if self.config.subplugin_order:
            self.engineer.reorder_roles(self.config.subplugin_order, auto_save=False)

    def on_enable(self) -> None:
        super().on_enable()
        self.engineer.enabled = True

    def on_disable(self) -> None:
        super().on_disable()
        self.engineer.enabled = False
        self.engineer.reset_all()

    def save_plugin_config(self) -> None:
        """Persist current master switch, sub-plugin states, and order to config."""
        if not self.context:
            return
        self.config.master_enabled = self.engineer.enabled
        self.config.muted = AudioAnnouncer.is_muted()
        configs = {}
        for r in self.engineer.get_roles():
            cfg = dict(r.get_config())
            cfg.pop("priority", None)
            configs[r.role_id] = cfg
        self.config.subplugin_configs = configs
        self.config.subplugin_order = [r.role_id for r in self.engineer.get_roles()]
        self.context.save_typed_config(self.config)

    # =========================================================================
    # ITabProvider
    # =========================================================================

    def get_tab_title(self) -> str:
        return "Race Engineer"

    def get_tab_icon(self) -> str:
        return "🎙️"

    def create_tab_widget(self, parent: Optional[QWidget] = None) -> QWidget:
        self._active_tab_widget = RaceEngineerWidget(self, parent)
        self._radio_bridge.radio_message.connect(
            self._active_tab_widget.add_radio_log,
            Qt.ConnectionType.QueuedConnection,
        )
        return self._active_tab_widget

    # =========================================================================
    # Telemetry & Packet Ingestion Dispatchers
    # =========================================================================

    def on_telemetry_frame(self, sensors: VehicleSensors) -> None:
        """Called on normalized VehicleSensors high-frequency frame."""
        self._latest_sensors = sensors

    def on_delta_frame(self, delta_packet: LapDeltaPacket) -> None:
        """Called on authoritative LapDeltaPacket frame."""
        pass

    # =========================================================================
    # Polymorphic Telemetry State Event Hooks (Every channel has a dedicated on_ hook)
    # =========================================================================

    def on_physics_tick(self, state: TelemetryStateStore) -> None:
        """High-frequency physics tick: announce to roles via consolidated view."""
        self._dispatch_engineer_event(TelemetryWakeReason.PHYSICS_TICK, state)

    def on_opponents_tick(self, state: TelemetryStateStore) -> None:
        """Opponent vehicle dynamics tick."""
        self._dispatch_engineer_event(TelemetryWakeReason.OPPONENTS_TICK, state)

    def on_scoring_update(self, state: TelemetryStateStore) -> None:
        """Compact scoring update (10Hz)."""
        self._dispatch_engineer_event(TelemetryWakeReason.SCORING_UPDATE, state)

    def on_grid_update(self, state: TelemetryStateStore) -> None:
        """Full grid update (2-5Hz)."""
        self._dispatch_engineer_event(TelemetryWakeReason.GRID_UPDATE, state)

    def on_weather_update(self, state: TelemetryStateStore) -> None:
        """Weather update (~1Hz)."""
        self._dispatch_engineer_event(TelemetryWakeReason.WEATHER_UPDATE, state)

    def on_extended_state_update(self, state: TelemetryStateStore) -> None:
        """Vehicle electronics and flags update (5Hz)."""
        self._dispatch_engineer_event(TelemetryWakeReason.STATE_CHANGE, state)

    def on_session_event(self, state: TelemetryStateStore) -> None:
        """System / session event."""
        self._dispatch_engineer_event(TelemetryWakeReason.SYSTEM_EVENT, state)

    def on_ffb_update(self, state: TelemetryStateStore) -> None:
        """Force feedback frame."""
        self._dispatch_engineer_event(TelemetryWakeReason.STATE_CHANGE, state)

    def on_graphics_update(self, state: TelemetryStateStore) -> None:
        """Camera / graphics frame."""
        self._dispatch_engineer_event(TelemetryWakeReason.STATE_CHANGE, state)

    def on_track_rules_update(self, state: TelemetryStateStore) -> None:
        """Track rules update."""
        self._dispatch_engineer_event(TelemetryWakeReason.STATE_CHANGE, state)

    def on_pit_menu_update(self, state: TelemetryStateStore) -> None:
        """Pit menu update."""
        self._dispatch_engineer_event(TelemetryWakeReason.STATE_CHANGE, state)

    def _dispatch_engineer_event(
        self,
        wake_reason: TelemetryWakeReason,
        state: TelemetryStateStore,
        trigger_packet: Optional[TelemetryTriggerPacket] = None,
    ) -> None:
        if not self.engineer.enabled:
            return

        emitted_messages = self.engineer.update(
            store=state,
            wake_reason=wake_reason,
            trigger_packet=trigger_packet,
        )

        for msg in emitted_messages:
            self._radio_bridge.radio_message.emit(msg)
