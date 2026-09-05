"""
SimPulse Plugin — XInput Haptic Feedback & Modular Subplugins (Qt6 Pure).
Translates real-time vehicle telemetry into realistic gamepad rumble sensations
via a modular library of subplugins (including 'Marc Profile' decomposition for ABS, TC, and Shift cues).
"""

from __future__ import annotations
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, List

from PySide6.QtCore import Qt, QSize, Signal, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QGroupBox, QScrollArea, QFrame, QProgressBar,
    QDoubleSpinBox, QSpinBox, QSlider, QComboBox, QListWidget,
    QListWidgetItem, QMessageBox
)

from simpulse_sdk import (
    SimPulsePlugin, PluginMetadata, PluginContext,
    ITabProvider, ITelemetrySubscriber,
    TelemetryChannel, ChannelRequirement,
    VehicleSensors, TelemetryStateStore
)
from .base import HapticController
from .factory import HapticBackendFactory
from .manager import HapticSubpluginManager
from .subplugins.base import BaseHapticSubplugin, HapticHostSlot
from simpulse.core.params import (
    RoleParam, BoolParam, FloatRangeParam, IntRangeParam, ChoiceParam, ParamScalarValue, ParamWidgetFactory
)

logger = logging.getLogger("simpulse.plugin.haptic_feedback")


@dataclass
class HapticFeedbackConfig:
    """Strongly-typed configuration schema for XInput Haptic Feedback Plugin."""
    master_enabled: bool = True
    master_gain: float = 1.0
    subplugin_configs: Dict[str, Dict[str, ParamScalarValue]] = field(default_factory=dict)
    subplugin_order: List[str] = field(default_factory=list)


# =============================================================================
# Custom Subplugin List Item Widget (Left Column)
# =============================================================================

class SubpluginListItemWidget(QWidget):
    """Compact list item widget displaying checkbox, icon, and title."""

    enable_toggled = Signal(str, bool)

    def __init__(
        self,
        slot_or_subplugin: Union[HapticHostSlot, BaseHapticSubplugin],
        parent: Optional[QWidget] = None,
        enabled: Optional[bool] = None,
    ):
        super().__init__(parent)
        if isinstance(slot_or_subplugin, HapticHostSlot):
            self.slot = slot_or_subplugin
            self.subplugin = slot_or_subplugin.subplugin
            self._is_enabled = slot_or_subplugin.enabled
        else:
            self.slot = None
            self.subplugin = slot_or_subplugin
            self._is_enabled = enabled if enabled is not None else getattr(slot_or_subplugin, "enabled", True)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # Enable checkbox
        self.chk_enabled = QCheckBox(self)
        self.chk_enabled.setChecked(self._is_enabled)
        self.chk_enabled.toggled.connect(lambda checked: self.enable_toggled.emit(self.subplugin.subplugin_id, checked))
        layout.addWidget(self.chk_enabled)

        # Icon & Name
        lbl_name = QLabel(f"{self.subplugin.icon} <b>{self.subplugin.name}</b>", self)
        lbl_name.setStyleSheet("color: #f1f5f9; font-size: 13px;")
        layout.addWidget(lbl_name, 1)

        # Status badge
        self.badge = QLabel("ON" if self._is_enabled else "OFF", self)
        self._update_badge(self._is_enabled)
        layout.addWidget(self.badge)

    def _update_badge(self, enabled: bool) -> None:
        if enabled:
            self.badge.setText("ON")
            self.badge.setStyleSheet(
                "background-color: #064e3b; color: #34d399; font-weight: bold; "
                "font-size: 10px; padding: 2px 6px; border-radius: 4px; border: 1px solid #059669;"
            )
        else:
            self.badge.setText("OFF")
            self.badge.setStyleSheet(
                "background-color: #1e293b; color: #94a3b8; font-weight: bold; "
                "font-size: 10px; padding: 2px 6px; border-radius: 4px; border: 1px solid #334155;"
            )

    def set_checked(self, checked: bool) -> None:
        self._is_enabled = checked
        if self.slot:
            self.slot.enabled = checked
        self.chk_enabled.blockSignals(True)
        self.chk_enabled.setChecked(checked)
        self.chk_enabled.blockSignals(False)
        self._update_badge(checked)


# =============================================================================
# Haptic Feedback Studio Tab Widget
# =============================================================================

class HapticFeedbackWidget(QWidget):
    """Main Studio Console Tab for configuring XInput Haptic Feedback and Subplugins."""

    def __init__(self, plugin: HapticFeedbackPlugin, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.plugin = plugin
        self._selected_subplugin_id: Optional[str] = None
        self._subplugin_item_widgets: Dict[str, SubpluginListItemWidget] = {}

        self._init_ui()
        self._refresh_subplugins_list()

        # Timer to refresh gamepad connection status live
        self._device_timer = QTimer(self)
        self._device_timer.setInterval(1000)
        self._device_timer.timeout.connect(self._update_device_label)
        self._device_timer.start()

    def _init_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(14)

        # Top Control Bar (Master Switch, Volume, Gamepad Status, Meters, Test Buttons)
        top_group = QGroupBox("🎮 XInput Haptic Hardware & Master Controls", self)
        top_layout = QVBoxLayout(top_group)

        row1 = QHBoxLayout()

        # Master Toggle
        self.chk_master = QCheckBox("Master Haptics Enabled", top_group)
        self.chk_master.setStyleSheet("font-weight: bold; font-size: 14px; color: #38bdf8;")
        self.chk_master.setChecked(self.plugin.config.master_enabled)
        self.chk_master.toggled.connect(self._on_master_toggled)
        row1.addWidget(self.chk_master)

        row1.addSpacing(20)

        # Master Gain Slider
        lbl_gain = QLabel("Global Force:", top_group)
        lbl_gain.setStyleSheet("color: #94a3b8; font-weight: 500;")
        row1.addWidget(lbl_gain)

        row1.addSpacing(20)

        # Device status
        self.lbl_device = QLabel("Status: Detecting...", top_group)
        self._update_device_label()
        row1.addWidget(self.lbl_device)

        row1.addStretch()

        # Test Vibration Buttons
        btn_test_low = QPushButton("Test Low Rumble", top_group)
        btn_test_low.clicked.connect(lambda: self.plugin.test_rumble(low=0.7, high=0.0, duration_ms=400))
        row1.addWidget(btn_test_low)

        btn_test_high = QPushButton("Test High Buzz", top_group)
        btn_test_high.clicked.connect(lambda: self.plugin.test_rumble(low=0.0, high=0.7, duration_ms=400))
        row1.addWidget(btn_test_high)

        btn_test_both = QPushButton("Test Both", top_group)
        btn_test_both.setStyleSheet("background-color: #1e3a8a; border: 1px solid #3b82f6;")
        btn_test_both.clicked.connect(lambda: self.plugin.test_rumble(low=0.7, high=0.7, duration_ms=500))
        row1.addWidget(btn_test_both)

        btn_stop = QPushButton("Stop", top_group)
        btn_stop.setStyleSheet("background-color: #7f1d1d; border: 1px solid #ef4444;")
        btn_stop.clicked.connect(self.plugin.stop_rumble)
        row1.addWidget(btn_stop)

        top_layout.addLayout(row1)

        # Row 2: Live Motor Output Meters
        row2 = QHBoxLayout()

        lbl_m1 = QLabel("Left Motor (Low Freq / Rumble):", top_group)
        lbl_m1.setStyleSheet("color: #94a3b8; font-size: 11px;")
        row2.addWidget(lbl_m1)

        self.pbar_low = QProgressBar(top_group)
        self.pbar_low.setRange(0, 100)
        self.pbar_low.setFixedHeight(12)
        self.pbar_low.setStyleSheet("QProgressBar::chunk { background-color: #f59e0b; }")
        row2.addWidget(self.pbar_low, 1)

        row2.addSpacing(20)

        lbl_m2 = QLabel("Right Motor (High Freq / Buzz):", top_group)
        lbl_m2.setStyleSheet("color: #94a3b8; font-size: 11px;")
        row2.addWidget(lbl_m2)

        self.pbar_high = QProgressBar(top_group)
        self.pbar_high.setRange(0, 100)
        self.pbar_high.setFixedHeight(12)
        self.pbar_high.setStyleSheet("QProgressBar::chunk { background-color: #38bdf8; }")
        row2.addWidget(self.pbar_high, 1)

        top_layout.addLayout(row2)
        root_layout.addWidget(top_group)

        # Split: Left (Subplugins List) | Right (Selected Subplugin Details & Params)
        split_layout = QHBoxLayout()
        split_layout.setSpacing(14)

        # Left Column: Subplugins List
        left_box = QGroupBox("🧩 Haptic Subplugins (Check to Enable/Disable)", self)
        left_box.setFixedWidth(340)
        l_layout = QVBoxLayout(left_box)

        self.subplugins_list = QListWidget(left_box)
        self.subplugins_list.setStyleSheet(
            "QListWidget { background-color: #0b0f19; border: 1px solid #1e293b; border-radius: 6px; } "
            "QListWidget::item { padding: 2px; border-bottom: 1px solid #1e293b; } "
            "QListWidget::item:selected { background-color: #1e293b; border-radius: 4px; }"
        )
        self.subplugins_list.itemClicked.connect(self._on_subplugin_selected)
        l_layout.addWidget(self.subplugins_list)

        split_layout.addWidget(left_box)

        # Right Column: Subplugin Detail & Parameters Panel
        self.detail_box = QGroupBox("⚙️ Subplugin Parameters & Effect Tuning", self)
        self.d_layout = QVBoxLayout(self.detail_box)

        # Header of detail
        self.lbl_sp_title = QLabel("Select a subplugin on the left to configure", self.detail_box)
        self.lbl_sp_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #f8fafc;")
        self.d_layout.addWidget(self.lbl_sp_title)

        self.lbl_sp_desc = QLabel("", self.detail_box)
        self.lbl_sp_desc.setWordWrap(True)
        self.lbl_sp_desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.d_layout.addWidget(self.lbl_sp_desc)

        # Scroll area for dynamic parameter widgets
        self.param_scroll = QScrollArea(self.detail_box)
        self.param_scroll.setWidgetResizable(True)
        self.param_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.param_scroll_content = QWidget()
        self.param_layout = QVBoxLayout(self.param_scroll_content)
        self.param_layout.setContentsMargins(4, 4, 4, 4)
        self.param_layout.setSpacing(12)
        self.param_scroll.setWidget(self.param_scroll_content)
        self.d_layout.addWidget(self.param_scroll, 1)

        split_layout.addWidget(self.detail_box, 1)
        root_layout.addLayout(split_layout, 1)

    def _update_device_label(self) -> None:
        controller = self.plugin.haptic_controller
        if controller and controller.is_connected():
            name = controller.get_gamepad_name()
            self.lbl_device.setText(f"🟢 Connected: <b>{name}</b>")
            self.lbl_device.setStyleSheet(
                "color: #34d399; font-size: 12px; background-color: #064e3b; "
                "padding: 4px 10px; border-radius: 4px; border: 1px solid #059669;"
            )
        else:
            self.lbl_device.setText("🔴 Gamepad Disconnected (Waiting...)")
            self.lbl_device.setStyleSheet(
                "color: #f87171; font-size: 12px; background-color: #450a0a; "
                "padding: 4px 10px; border-radius: 4px; border: 1px solid #dc2626;"
            )


    def _refresh_subplugins_list(self) -> None:
        self.subplugins_list.clear()
        self._subplugin_item_widgets.clear()

        slots = self.plugin.manager.get_all_slots()
        for slot in slots:
            item = QListWidgetItem(self.subplugins_list)
            widget = SubpluginListItemWidget(slot, self.subplugins_list)
            widget.enable_toggled.connect(self._on_subplugin_toggled)
            item.setSizeHint(QSize(300, 42))
            self.subplugins_list.addItem(item)
            self.subplugins_list.setItemWidget(item, widget)
            self._subplugin_item_widgets[slot.subplugin_id] = widget

        if slots:
            self.subplugins_list.setCurrentRow(0)
            self._load_subplugin_details(slots[0].subplugin_id)

    def _on_subplugin_selected(self, item: QListWidgetItem) -> None:
        row = self.subplugins_list.row(item)
        slots = self.plugin.manager.get_all_slots()
        if 0 <= row < len(slots):
            self._load_subplugin_details(slots[row].subplugin_id)

    def _on_subplugin_toggled(self, subplugin_id: str, enabled: bool) -> None:
        self.plugin.manager.set_subplugin_enabled(subplugin_id, enabled)
        widget = self._subplugin_item_widgets.get(subplugin_id)
        if widget:
            widget.set_checked(enabled)
        self.plugin.save_config()

    def _load_subplugin_details(self, subplugin_id: str) -> None:
        self._selected_subplugin_id = subplugin_id
        slot = self.plugin.manager.get_slot(subplugin_id)
        if not slot:
            return
        sp = slot.subplugin

        self.lbl_sp_title.setText(f"{sp.icon} {sp.name}")
        self.lbl_sp_desc.setText(sp.description)

        # Clear existing dynamic parameters
        while self.param_layout.count() > 0:
            child = self.param_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
            elif child.layout():
                while child.layout().count() > 0:
                    c = child.layout().takeAt(0)
                    if c.widget():
                        c.widget().deleteLater()

        # 1. Subplugin Gain row
        gain_row = QHBoxLayout()
        gain_row.addWidget(QLabel("Effect Intensity (Master Gain):", self.param_scroll_content), 1)
        sp_gain_slider = QSlider(Qt.Orientation.Horizontal, self.param_scroll_content)
        sp_gain_slider.setRange(0, 300)
        sp_gain_slider.setValue(int(slot.master_gain * 100))
        gain_row.addWidget(sp_gain_slider, 2)

        lbl_val = QLabel(f"{int(slot.master_gain * 100)}%", self.param_scroll_content)
        lbl_val.setFixedWidth(50)
        lbl_val.setStyleSheet("color: #38bdf8; font-weight: bold;")
        gain_row.addWidget(lbl_val)

        def on_sp_gain_changed(v: int):
            slot.master_gain = v / 100.0
            lbl_val.setText(f"{v}%")
            self.plugin.save_config()

        sp_gain_slider.valueChanged.connect(on_sp_gain_changed)
        self.param_layout.addLayout(gain_row)

        # Separator
        sep = QFrame(self.param_scroll_content)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #334155;")
        self.param_layout.addWidget(sep)

        # 2. Dynamic declared parameters
        for p in sp.get_declared_params():
            curr_val = sp.get_param(p.name, p.default)
            row = QHBoxLayout()
            lbl = QLabel(f"<b>{p.label}:</b><br/><span style='color: #64748b; font-size: 11px;'>{p.description}</span>", self.param_scroll_content)
            lbl.setWordWrap(True)
            row.addWidget(lbl, 2)

            widget = ParamWidgetFactory.create_widget(
                param=p,
                parent=self.param_scroll_content,
                current_value=curr_val,
                on_change=lambda val, pname=p.name: self._set_param_and_save(sp, pname, val),
            )
            if widget:
                row.addWidget(widget, 1)

            self.param_layout.addLayout(row)

        self.param_layout.addStretch()

    def _set_param_and_save(self, sp: BaseHapticSubplugin, name: str, val: ParamScalarValue) -> None:
        sp.set_param(name, val)
        self.plugin.save_config()

    def _on_master_toggled(self, checked: bool) -> None:
        self.plugin.config.master_enabled = checked
        self.plugin.save_config()
        if not checked:
            self.plugin.stop_rumble()

    def _on_master_gain_changed(self, value: int) -> None:
        gain = value / 100.0
        self.plugin.config.master_gain = gain
        self.lbl_gain_val.setText(f"{value}%")
        self.plugin.save_config()

    def update_live_meters(self, low_pct: float, high_pct: float) -> None:
        self.pbar_low.setValue(int(low_pct * 100))
        self.pbar_high.setValue(int(high_pct * 100))
        self._update_device_label()


# =============================================================================
# Haptic Feedback SimPulse Plugin Implementation
# =============================================================================

class HapticFeedbackPlugin(SimPulsePlugin, ITabProvider, ITelemetrySubscriber):
    """
    SimPulse Qt6 Builtin Plugin for XInput Haptic Feedback.
    Evaluates real-time telemetry across modular subplugins and controls hardware gamepad motors.
    """

    def __init__(self):
        super().__init__(PluginMetadata(
            id="simpulse.builtin.haptic_feedback",
            name="XInput Haptic Feedback",
            version="2.0.0",
            author="SimPulse Team",
            description="Pure Python modular haptic feedback middleware for XInput gamepads (Decomposed Marc Profile).",
            icon="🎮",
            tags=("haptics", "xinput", "gamepad", "rumble", "subplugins", "telemetry")
        ))
        self.config: HapticFeedbackConfig = HapticFeedbackConfig()
        self.manager: HapticSubpluginManager = HapticSubpluginManager()
        self.haptic_controller: Optional[HapticController] = None
        self._active_tab_widget: Optional[HapticFeedbackWidget] = None

    def get_channel_requirements(self) -> List[ChannelRequirement]:
        return [
            ChannelRequirement(
                channel=TelemetryChannel.TELEMETRY,
                preferred_hz=100,
                required=True,
                reason="High-frequency telemetry for ABS, TC, slip and curb haptic calculations"
            ),
            ChannelRequirement(
                channel=TelemetryChannel.EXTENDED_STATE,
                preferred_hz=10,
                required=False,
                reason="ECU ABS & Traction Control electronic intervention flags"
            )
        ]

    def on_load(self, context: PluginContext) -> None:
        super().on_load(context)
        self.config = context.get_typed_config(HapticFeedbackConfig)

        # Restore subplugins configuration
        if self.config.subplugin_configs:
            self.manager.load_config_dict({
                "order": self.config.subplugin_order,
                "subplugins": self.config.subplugin_configs
            })

        # Initialize hardware controller backend
        try:
            self.haptic_controller = HapticBackendFactory.create_backend()
            logger.info(f"Haptic Controller backend initialized: {self.haptic_controller.get_gamepad_name()}")
        except Exception as e:
            logger.warning(f"Could not initialize native haptic backend: {e}. Using mock fallback.")
            self.haptic_controller = HapticBackendFactory.create_backend(force_mock=True)

    def on_unload(self) -> None:
        self.stop_rumble()
        if self.haptic_controller:
            try:
                self.haptic_controller.close()
            except Exception:
                pass
            self.haptic_controller = None
        super().on_unload()

    def on_disable(self) -> None:
        self.stop_rumble()
        super().on_disable()

    def save_config(self) -> None:
        """Saves current state and subplugins configs into PluginContext."""
        if self.context:
            cfg_dict = self.manager.get_config_dict()
            self.config.subplugin_order = cfg_dict["order"]
            self.config.subplugin_configs = cfg_dict["subplugins"]
            self.context.save_typed_config(self.config)

    # ITabProvider Protocol
    def get_tab_title(self) -> str:
        return "XInput Haptics"

    def get_tab_icon(self) -> str:
        return "🎮"

    def create_tab_widget(self, parent: Optional[QWidget] = None) -> QWidget:
        self._active_tab_widget = HapticFeedbackWidget(self, parent)
        return self._active_tab_widget

    # Polymorphic Event Hooks
    def on_physics_tick(self, state: TelemetryStateStore) -> None:
        """Called directly on high-frequency physics tick (100-120Hz) from central state store."""
        raw_telem = state.telemetry.data
        if raw_telem is not None:
            # If normalized VehicleSensors or compatible raw data is available, evaluate haptics
            if hasattr(raw_telem, "vehicle_speed") or hasattr(raw_telem, "speed_mps"):
                pass

    # ITelemetrySubscriber Protocol
    def on_telemetry_frame(self, sensors: VehicleSensors) -> None:
        if not self.config.master_enabled:
            return

        t_now = time.time()
        # Evaluate all enabled subplugins
        out = self.manager.evaluate(sensors, t_now)

        # Apply global master gain
        scaled_out = out.scaled(self.config.master_gain)
        low_val, high_val = scaled_out.to_xinput()

        # Drive hardware motors
        if self.haptic_controller:
            try:
                self.haptic_controller.set_vibration(
                    left_low=low_val,
                    left_high=0.0,
                    right_low=0.0,
                    right_high=high_val,
                    duration_ms=30
                )
            except Exception as e:
                logger.debug(f"Error sending vibration: {e}")

        # Update Live meters if UI tab is visible
        if self._active_tab_widget and self._active_tab_widget.isVisible():
            self._active_tab_widget.update_live_meters(low_val, high_val)

    def test_rumble(self, low: float = 0.5, high: float = 0.5, duration_ms: int = 400) -> None:
        """Triggers a manual hardware rumble test pulse."""
        if self.haptic_controller:
            self.haptic_controller.set_vibration(
                left_low=low * self.config.master_gain,
                left_high=0.0,
                right_low=0.0,
                right_high=high * self.config.master_gain,
                duration_ms=duration_ms
            )


    def stop_rumble(self) -> None:
        """Stops all rumble motors immediately."""
        if self.haptic_controller:
            try:
                self.haptic_controller.stop()
            except Exception:
                pass
        if self._active_tab_widget:
            self._active_tab_widget.update_live_meters(0.0, 0.0)
