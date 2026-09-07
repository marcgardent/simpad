"""
SimPulse Plugin — Live Pedal & Slip Telemetry Monitor.
Uses strongly-typed Python dataclasses for all plugin configurations and state.
"""

from typing import Optional
from dataclasses import dataclass

from PySide6.QtCore import Qt, QSize, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QProgressBar, QCheckBox, QComboBox
)

from simpulse_sdk import (
    SimPulsePlugin, PluginMetadata, PluginContext,
    ITabProvider, ITelemetrySubscriber, IHudWidgetProvider, HudSlot,
    VehicleSensors, TelemetryStateStore, TelemetryView
)


@dataclass
class PedalMonitorConfig:
    """Strongly-typed configuration schema for Pedal & Slip Monitor."""
    slot: HudSlot = HudSlot.BOTTOM_LEFT
    hud_enabled: bool = True
    show_abs_warning: bool = True
    show_tc_warning: bool = True


class PedalMonitorWidget(QWidget):
    """Studio Tab Widget for Pedal & Slip Telemetry."""

    def __init__(self, plugin: "PedalTelemetryPlugin", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.plugin = plugin
        self._is_idle: bool = False
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Pedals Section
        pedal_group = QGroupBox("🦶 Live Pedals & Inputs", self)
        p_layout = QVBoxLayout(pedal_group)

        # Throttle
        t_row = QHBoxLayout()
        t_row.addWidget(QLabel("Throttle Input:", pedal_group), 1)
        self.pbar_throttle = QProgressBar(pedal_group)
        self.pbar_throttle.setRange(0, 100)
        self.pbar_throttle.setStyleSheet("QProgressBar::chunk { background-color: #22c55e; }")
        t_row.addWidget(self.pbar_throttle, 3)
        p_layout.addLayout(t_row)

        # Brake
        b_row = QHBoxLayout()
        b_row.addWidget(QLabel("Brake Input:", pedal_group), 1)
        self.pbar_brake = QProgressBar(pedal_group)
        self.pbar_brake.setRange(0, 100)
        self.pbar_brake.setStyleSheet("QProgressBar::chunk { background-color: #ef4444; }")
        b_row.addWidget(self.pbar_brake, 3)
        p_layout.addLayout(b_row)

        layout.addWidget(pedal_group)

        # Electronic & Slip Assist Section
        slip_group = QGroupBox("⚡ Assists & Tire Dynamics", self)
        s_layout = QVBoxLayout(slip_group)

        # ABS
        abs_row = QHBoxLayout()
        abs_row.addWidget(QLabel("ABS Lock Intensity:", slip_group), 1)
        self.pbar_abs = QProgressBar(slip_group)
        self.pbar_abs.setRange(0, 100)
        self.pbar_abs.setStyleSheet("QProgressBar::chunk { background-color: #f59e0b; }")
        abs_row.addWidget(self.pbar_abs, 3)
        s_layout.addLayout(abs_row)

        # TC
        tc_row = QHBoxLayout()
        tc_row.addWidget(QLabel("TC Wheelspin Intensity:", slip_group), 1)
        self.pbar_tc = QProgressBar(slip_group)
        self.pbar_tc.setRange(0, 100)
        self.pbar_tc.setStyleSheet("QProgressBar::chunk { background-color: #3b82f6; }")
        tc_row.addWidget(self.pbar_tc, 3)
        s_layout.addLayout(tc_row)

        layout.addWidget(slip_group)

        # Settings Section
        cfg_group = QGroupBox("⚙️ HUD Settings", self)
        c_layout = QVBoxLayout(cfg_group)

        # Slot selector
        slot_row = QHBoxLayout()
        slot_row.addWidget(QLabel("HUD Overlay Slot Position:", cfg_group))
        self.slot_combo = QComboBox(cfg_group)
        for s in HudSlot:
            self.slot_combo.addItem(s.value.replace("_", " ").title(), s)
        idx = self.slot_combo.findData(self.plugin.config.slot)
        if idx != -1:
            self.slot_combo.setCurrentIndex(idx)
        self.slot_combo.currentIndexChanged.connect(self._on_slot_changed)
        slot_row.addWidget(self.slot_combo)
        slot_row.addStretch()
        c_layout.addLayout(slot_row)

        self.chk_hud_visible = QCheckBox("Enable In-Game Overlay Display", cfg_group)
        self.chk_hud_visible.setChecked(self.plugin.config.hud_enabled)
        self.chk_hud_visible.toggled.connect(self._on_hud_toggled)
        c_layout.addWidget(self.chk_hud_visible)

        layout.addWidget(cfg_group)
        layout.addStretch()

    def set_idle_mode(self, is_idle: bool) -> None:
        """Switch between active live view and power-saving idle mode."""
        self._is_idle = is_idle
        if not is_idle:
            self.update_live_view(
                self.plugin._throttle_pct, self.plugin._brake_pct,
                self.plugin._abs_pct, self.plugin._tc_pct
            )

    def update_live_view(self, throttle_pct: float, brake_pct: float, abs_pct: float, tc_pct: float) -> None:
        if getattr(self, "_is_idle", False):
            return
        self.pbar_throttle.setValue(int(throttle_pct))
        self.pbar_brake.setValue(int(brake_pct))
        self.pbar_abs.setValue(int(abs_pct))
        self.pbar_tc.setValue(int(tc_pct))

    def _on_slot_changed(self, index: int) -> None:
        slot = self.slot_combo.currentData()
        self.plugin.config.slot = slot
        self.plugin.save_config()

    def _on_hud_toggled(self, checked: bool) -> None:
        self.plugin.config.hud_enabled = checked
        self.plugin.save_config()


class PedalTelemetryPlugin(SimPulsePlugin, ITabProvider, ITelemetrySubscriber, IHudWidgetProvider):
    """Plugin displaying live pedal inputs and electronic assists with strongly-typed config."""

    def __init__(self):
        super().__init__(PluginMetadata(
            id="simpulse.builtin.pedal_monitor",
            name="Pedal & Assist Monitor",
            version="1.0.0",
            author="SimPulse Team",
            description="Live Throttle, Brake, ABS and Traction Control telemetry gauges.",
            icon="🦶",
            tags=("pedals", "telemetry", "assists")
        ))
        self.config: PedalMonitorConfig = PedalMonitorConfig()

        self._throttle_pct: float = 0.0
        self._brake_pct: float = 0.0
        self._abs_pct: float = 0.0
        self._tc_pct: float = 0.0

        self._active_tab_widget: Optional[PedalMonitorWidget] = None

    def get_channel_requirements(self) -> list:
        from simpulse.core.telemetry_channels import TelemetryChannel, ChannelRequirement
        return [
            ChannelRequirement(
                channel=TelemetryChannel.TELEMETRY,
                preferred_hz=100,
                required=True,
                reason="Calculation of throttle and brake pedal inputs"
            ),
            ChannelRequirement(
                channel=TelemetryChannel.EXTENDED_STATE,
                preferred_hz=10,
                required=False,
                reason="Monitoring of flags and electronic brake assists"
            ),
        ]

    def on_load(self, context: PluginContext) -> None:
        super().on_load(context)
        self.config = context.get_typed_config(PedalMonitorConfig)
        try:
            self.config.slot = HudSlot(self.config.slot)
        except ValueError:
            self.config.slot = HudSlot.BOTTOM_LEFT

    def save_config(self) -> None:
        if self.context:
            self.context.save_typed_config(self.config)

    def get_tab_title(self) -> str:
        return "Pedals & Assists"

    def get_tab_icon(self) -> str:
        return "🦶"

    def create_tab_widget(self, parent: Optional[QWidget] = None) -> QWidget:
        self._active_tab_widget = PedalMonitorWidget(self, parent)
        return self._active_tab_widget

    def on_physics_tick(self, state: TelemetryView) -> None:
        """Called directly on high-frequency physics tick (100-120Hz) from central state store."""
        self._throttle_pct = state.throttle_pct
        self._brake_pct = state.brake_pct

        if self._active_tab_widget and self._active_tab_widget.isVisible() and not getattr(self._active_tab_widget, "_is_idle", False):
            self._active_tab_widget.update_live_view(
                self._throttle_pct, self._brake_pct, self._abs_pct, self._tc_pct
            )

    def on_telemetry_frame(self, sensors: VehicleSensors) -> None:
        self._throttle_pct = sensors.unfiltered_throttle * 100.0
        self._brake_pct = sensors.unfiltered_brake * 100.0
        self._abs_pct = max(sensors.ecu_abs_active, sensors.lock_intensity) * 100.0
        self._tc_pct = max(sensors.ecu_tc_active, sensors.spin_intensity) * 100.0

        if self._active_tab_widget and self._active_tab_widget.isVisible() and not getattr(self._active_tab_widget, "_is_idle", False):
            self._active_tab_widget.update_live_view(
                self._throttle_pct, self._brake_pct, self._abs_pct, self._tc_pct
            )

    @property
    def preferred_slot(self) -> HudSlot:
        return self.config.slot

    def get_hud_size(self) -> QSize:
        return QSize(90, 140)

    def is_hud_visible(self) -> bool:
        return self.config.hud_enabled

    def paint_hud(
        self,
        painter: QPainter,
        width: float,
        height: float,
        sensors: VehicleSensors,
    ) -> None:
        """Render vertical dual pedal bar on transparent HUD."""
        # 1. Backing container
        card_rect = QRectF(0, 0, width, height)
        painter.setPen(QPen(QColor(0, 210, 255, 60), 1.5))
        painter.setBrush(QBrush(QColor(10, 14, 20, 190)))
        painter.drawRoundedRect(card_rect, 8.0, 8.0)

        # 2. Dual vertical bars (Throttle / Brake)
        bar_h = 90.0
        bar_w = 24.0
        bar_y = 12.0

        # Throttle (Green, on the right)
        tx = 48.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(30, 41, 59, 200))
        painter.drawRoundedRect(QRectF(tx, bar_y, bar_w, bar_h), 4.0, 4.0)

        th_val = min(1.0, max(0.0, sensors.unfiltered_throttle))
        if th_val > 0:
            fill_h = bar_h * th_val
            painter.setBrush(QColor(34, 197, 94))
            painter.drawRoundedRect(QRectF(tx, bar_y + (bar_h - fill_h), bar_w, fill_h), 4.0, 4.0)

        # Brake (Red, on the left)
        bx = 16.0
        painter.setBrush(QColor(30, 41, 59, 200))
        painter.drawRoundedRect(QRectF(bx, bar_y, bar_w, bar_h), 4.0, 4.0)

        brk_val = min(1.0, max(0.0, sensors.unfiltered_brake))
        if brk_val > 0:
            fill_h = bar_h * brk_val
            painter.setBrush(QColor(239, 68, 68))
            painter.drawRoundedRect(QRectF(bx, bar_y + (bar_h - fill_h), bar_w, fill_h), 4.0, 4.0)

        # Labels (B / T)
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.setPen(QColor(239, 68, 68))
        painter.drawText(QRectF(bx, bar_y + bar_h + 4, bar_w, 16), Qt.AlignmentFlag.AlignCenter, "BRK")
        painter.setPen(QColor(34, 197, 94))
        painter.drawText(QRectF(tx, bar_y + bar_h + 4, bar_w, 16), Qt.AlignmentFlag.AlignCenter, "THR")

        # 3. ABS / TC Warning Badges
        abs_active = sensors.ecu_abs_active > 0.1 or sensors.lock_intensity > 0.05
        tc_active = sensors.ecu_tc_active > 0.1 or sensors.spin_intensity > 0.05

        if self.config.show_abs_warning and abs_active:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(245, 158, 11, 230))
            painter.drawRoundedRect(QRectF(bx - 2, 2, bar_w + 4, 12), 3.0, 3.0)
            painter.setPen(QColor(0, 0, 0))
            painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
            painter.drawText(QRectF(bx - 2, 2, bar_w + 4, 12), Qt.AlignmentFlag.AlignCenter, "ABS")

        if self.config.show_tc_warning and tc_active:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(59, 130, 246, 230))
            painter.drawRoundedRect(QRectF(tx - 2, 2, bar_w + 4, 12), 3.0, 3.0)
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
            painter.drawText(QRectF(tx - 2, 2, bar_w + 4, 12), Qt.AlignmentFlag.AlignCenter, "TC")
