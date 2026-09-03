"""
SimPad Plugin — Cockpit Gear & Speedometer HUD.
Uses strongly-typed Python dataclasses for all plugin configurations and state.
"""

from typing import Optional
from dataclasses import dataclass
import math

from PySide6.QtCore import Qt, QSize, QRectF
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QCheckBox, QGroupBox, QProgressBar
)

from simpad_qt.plugins.contracts import (
    SimPadPlugin, PluginMetadata, PluginContext,
    ITabProvider, ITelemetrySubscriber, IHudWidgetProvider, HudSlot
)
from src.telemetry.sensors import VehicleSensors


@dataclass
class GearSpeedConfig:
    """Strongly-typed configuration schema for Gear & Speed HUD."""
    slot: HudSlot = HudSlot.COCKPIT_CENTER
    unit: str = "kmh"
    hud_enabled: bool = True
    shift_rpm_ratio: float = 0.92


class GearSpeedHudWidget(QWidget):
    """Studio Tab Widget for Gear & Speed plugin."""

    def __init__(self, plugin: "GearSpeedHudPlugin", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.plugin = plugin
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Telemetry Live Preview Section
        live_group = QGroupBox("📊 Live Telemetry Preview", self)
        l_layout = QVBoxLayout(live_group)

        row_gauges = QHBoxLayout()
        self.lbl_gear = QLabel("N", live_group)
        self.lbl_gear.setStyleSheet(
            "font-size: 42px; font-weight: bold; color: #22c55e; "
            "background: #0f1115; border: 2px solid #22c55e; border-radius: 8px; padding: 10px 24px;"
        )
        self.lbl_gear.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row_gauges.addWidget(self.lbl_gear)

        v_box = QVBoxLayout()
        self.lbl_speed = QLabel("0.0 KM/H", live_group)
        self.lbl_speed.setStyleSheet("font-size: 26px; font-weight: bold; color: #ffffff;")
        v_box.addWidget(self.lbl_speed)

        self.rpm_bar = QProgressBar(live_group)
        self.rpm_bar.setRange(0, 8500)
        self.rpm_bar.setValue(0)
        self.rpm_bar.setFixedHeight(22)
        self.rpm_bar.setTextVisible(True)
        self.rpm_bar.setFormat("%v RPM")
        v_box.addWidget(self.rpm_bar)

        row_gauges.addLayout(v_box)
        row_gauges.addStretch()
        l_layout.addLayout(row_gauges)
        layout.addWidget(live_group)

        # Settings Section
        cfg_group = QGroupBox("⚙️ HUD Overlay Settings", self)
        c_layout = QVBoxLayout(cfg_group)

        # Slot Selector
        slot_row = QHBoxLayout()
        slot_row.addWidget(QLabel("Overlay Slot Position:", cfg_group))
        self.slot_combo = QComboBox(cfg_group)
        for s in HudSlot:
            self.slot_combo.addItem(s.value.replace("_", " ").title(), s)
        current_slot = self.plugin.config.slot
        idx = self.slot_combo.findData(current_slot)
        if idx != -1:
            self.slot_combo.setCurrentIndex(idx)
        self.slot_combo.currentIndexChanged.connect(self._on_slot_changed)
        slot_row.addWidget(self.slot_combo)
        slot_row.addStretch()
        c_layout.addLayout(slot_row)

        # Units selector
        unit_row = QHBoxLayout()
        unit_row.addWidget(QLabel("Speed Unit:", cfg_group))
        self.unit_combo = QComboBox(cfg_group)
        self.unit_combo.addItem("KM/H (Metric)", "kmh")
        self.unit_combo.addItem("MPH (Imperial)", "mph")
        if self.plugin.config.unit == "mph":
            self.unit_combo.setCurrentIndex(1)
        self.unit_combo.currentIndexChanged.connect(self._on_unit_changed)
        unit_row.addWidget(self.unit_combo)
        unit_row.addStretch()
        c_layout.addLayout(unit_row)

        # Visible checkbox
        self.chk_hud_visible = QCheckBox("Enable In-Game Overlay Display", cfg_group)
        self.chk_hud_visible.setChecked(self.plugin.config.hud_enabled)
        self.chk_hud_visible.toggled.connect(self._on_hud_toggled)
        c_layout.addWidget(self.chk_hud_visible)

        layout.addWidget(cfg_group)
        layout.addStretch()

    def update_live_view(self, speed_kmh: float, gear: int, rpm: float) -> None:
        """Update live preview on the Qt tab."""
        gear_str = "R" if gear == -1 else ("N" if gear == 0 else str(gear))
        self.lbl_gear.setText(gear_str)

        if self.plugin.config.unit == "mph":
            spd = speed_kmh * 0.621371
            self.lbl_speed.setText(f"{spd:.1f} MPH")
        else:
            self.lbl_speed.setText(f"{speed_kmh:.1f} KM/H")

        self.rpm_bar.setValue(int(rpm))

    def _on_slot_changed(self, index: int) -> None:
        slot = self.slot_combo.currentData()
        self.plugin.config.slot = slot
        self.plugin.save_config()

    def _on_unit_changed(self, index: int) -> None:
        unit = self.unit_combo.currentData()
        self.plugin.config.unit = unit
        self.plugin.save_config()

    def _on_hud_toggled(self, checked: bool) -> None:
        self.plugin.config.hud_enabled = checked
        self.plugin.save_config()


class GearSpeedHudPlugin(SimPadPlugin, ITabProvider, ITelemetrySubscriber, IHudWidgetProvider):
    """
    Plugin implementing Tab, Telemetry and HUD Overlay capabilities with strongly-typed config.
    """

    def __init__(self):
        super().__init__(PluginMetadata(
            id="simpad.builtin.gear_speed_hud",
            name="Gear & Speed Cockpit HUD",
            version="1.0.0",
            author="SimPad Team",
            description="Displays digital speedometer, gear number, and dynamic RPM rev bar on overlay and studio.",
            icon="🏎️",
            tags=("hud", "telemetry", "speedometer")
        ))
        self.config: GearSpeedConfig = GearSpeedConfig()

        self._current_speed_kmh: float = 0.0
        self._current_gear: int = 0
        self._current_rpm: float = 0.0
        self._max_rpm: float = 8500.0

        self._active_tab_widget: Optional[GearSpeedHudWidget] = None

    def get_channel_requirements(self) -> list:
        from simpad_qt.core.telemetry_channels import TelemetryChannel, ChannelRequirement
        return [
            ChannelRequirement(
                channel=TelemetryChannel.TELEMETRY,
                preferred_hz=100,
                required=True,
                reason="High-frequency calculation of vehicle speed, engaged gear and engine RPM"
            ),
            ChannelRequirement(
                channel=TelemetryChannel.COMPACT_SCORING,
                preferred_hz=10,
                required=False,
                reason="Real-time lap delta time calculation"
            ),
        ]

    def on_load(self, context: PluginContext) -> None:
        super().on_load(context)
        # Restore configuration into strongly-typed dataclass
        self.config = context.get_typed_config(GearSpeedConfig)
        if isinstance(self.config.slot, str):
            try:
                self.config.slot = HudSlot(self.config.slot)
            except ValueError:
                self.config.slot = HudSlot.COCKPIT_CENTER

    def save_config(self) -> None:
        if self.context:
            self.context.save_typed_config(self.config)

    # =========================================================================
    # ITabProvider
    # =========================================================================

    def get_tab_title(self) -> str:
        return "Gear & Speed"

    def get_tab_icon(self) -> str:
        return "⚡"

    def create_tab_widget(self, parent: Optional[QWidget] = None) -> QWidget:
        self._active_tab_widget = GearSpeedHudWidget(self, parent)
        return self._active_tab_widget

    # =========================================================================
    # ITelemetrySubscriber
    # =========================================================================

    def on_telemetry_frame(self, sensors: VehicleSensors) -> None:
        self._current_speed_kmh = sensors.vehicle_speed * 3.6
        self._current_gear = sensors.gear
        self._current_rpm = sensors.engine_rpm
        self._max_rpm = max(1000.0, sensors.engine_max_rpm)

        if self._active_tab_widget and self._active_tab_widget.isVisible():
            self._active_tab_widget.update_live_view(
                self._current_speed_kmh, self._current_gear, self._current_rpm
            )

    # =========================================================================
    # IHudWidgetProvider
    # =========================================================================

    @property
    def preferred_slot(self) -> HudSlot:
        return self.config.slot

    def get_hud_size(self) -> QSize:
        return QSize(260, 120)

    def is_hud_visible(self) -> bool:
        return self.config.hud_enabled

    def paint_hud(
        self,
        painter: QPainter,
        width: float,
        height: float,
        sensors: VehicleSensors,
    ) -> None:
        """Render modern vector cockpit telemetry."""
        # 1. Dark semi-transparent glowing backing card
        card_rect = QRectF(0, 0, width, height)
        painter.setPen(QPen(QColor(0, 210, 255, 60), 1.5))
        painter.setBrush(QBrush(QColor(10, 14, 20, 190)))
        painter.drawRoundedRect(card_rect, 10.0, 10.0)

        # 2. Gear Box (Left)
        gear_rect = QRectF(12, 14, 80, 80)
        painter.setPen(QPen(QColor(0, 210, 255, 120), 1.5))
        painter.setBrush(QBrush(QColor(18, 24, 34, 220)))
        painter.drawRoundedRect(gear_rect, 6.0, 6.0)

        gear_str = "R" if sensors.gear == -1 else ("N" if sensors.gear == 0 else str(sensors.gear))
        painter.setPen(QColor(46, 204, 113) if gear_str == "N" else QColor(255, 255, 255))
        font_gear = QFont("Segoe UI", 36, QFont.Weight.Bold)
        painter.setFont(font_gear)
        painter.drawText(gear_rect, Qt.AlignmentFlag.AlignCenter, gear_str)

        # 3. Digital Speedometer (Right)
        spd_val = sensors.vehicle_speed * 3.6
        unit_lbl = "KM/H"
        if self.config.unit == "mph":
            spd_val *= 0.621371
            unit_lbl = "MPH"

        speed_rect = QRectF(102, 14, 146, 50)
        painter.setPen(QColor(0, 210, 255))
        font_spd = QFont("Segoe UI", 28, QFont.Weight.Bold)
        painter.setFont(font_spd)
        painter.drawText(speed_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{int(spd_val)}")

        # Unit label
        unit_rect = QRectF(185, 30, 65, 25)
        painter.setPen(QColor(148, 163, 184))
        font_unit = QFont("Segoe UI", 10, QFont.Weight.Bold)
        painter.setFont(font_unit)
        painter.drawText(unit_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, unit_lbl)

        # 4. RPM Rev Indicator Bar (Bottom)
        rpm_ratio = min(1.0, max(0.0, sensors.engine_rpm / max(1.0, sensors.engine_max_rpm)))
        bar_bg_rect = QRectF(102, 70, 146, 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(30, 41, 59, 200))
        painter.drawRoundedRect(bar_bg_rect, 3.0, 3.0)

        if rpm_ratio > 0:
            fill_w = 146 * rpm_ratio
            bar_fill_rect = QRectF(102, 70, fill_w, 16)

            # Color gradient based on RPM shift threshold
            if rpm_ratio > self.config.shift_rpm_ratio:
                fill_color = QColor(239, 68, 68)
            elif rpm_ratio > 0.80:
                fill_color = QColor(245, 158, 11)
            else:
                fill_color = QColor(14, 165, 233)

            painter.setBrush(fill_color)
            painter.drawRoundedRect(bar_fill_rect, 3.0, 3.0)

        # 5. Delta Time preview (if present)
        if sensors.delta_time_str and sensors.delta_time_str != "--:--.---":
            delta_rect = QRectF(12, 98, 236, 16)
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            delta_val = sensors.delta_time
            delta_color = QColor(34, 197, 94) if delta_val <= 0 else QColor(239, 68, 68)
            painter.setPen(delta_color)
            painter.drawText(delta_rect, Qt.AlignmentFlag.AlignRight, f"Δ {sensors.delta_time_str}")
