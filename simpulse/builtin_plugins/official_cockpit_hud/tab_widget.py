"""
Studio Tab Widget for the Official Cockpit HUD.
Provides live telemetry previews, real-time metrics readouts, and extensive configuration toggles.
"""

from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel,
    QComboBox, QCheckBox, QGroupBox, QSlider, QScrollArea, QFrame
)

from simpulse_sdk import HudSlot, LapDeltaPacket, VehicleSensors
from simpulse.builtin_plugins.official_cockpit_hud.preview_canvas import OfficialHudPreviewCanvas

if TYPE_CHECKING:
    from simpulse.builtin_plugins.official_cockpit_hud.plugin import OfficialCockpitHudPlugin


def _format_smoothing_window(window_ms: int) -> str:
    """Display label for the Delta/Sector smoothing slider — 'Xms' below 1s,
    'X.Xs' at/above it (the slider goes up to 16s)."""
    if window_ms >= 1000:
        return f"{window_ms / 1000.0:.1f}s"
    return f"{window_ms}ms"


class OfficialCockpitHudTabWidget(QWidget):
    """
    Studio Tab Widget for the Official Cockpit HUD.
    Provides live telemetry previews, real-time metrics readouts, and extensive configuration toggles.
    """

    def __init__(self, plugin: OfficialCockpitHudPlugin, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.plugin = plugin
        self._is_idle: bool = False
        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # Scroll area to comfortably house preview + all configuration cards
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        # ── 1. Live Vector HUD Preview Card ──
        preview_group = QGroupBox("🏎️ Official Cockpit HUD — Live Dynamic Preview", container)
        prev_layout = QVBoxLayout(preview_group)
        self.preview_canvas = OfficialHudPreviewCanvas(self.plugin, preview_group)
        prev_layout.addWidget(self.preview_canvas)
        layout.addWidget(preview_group)

        # ── 2. Live Telemetry Data Quick Cards ──
        data_group = QGroupBox("📊 Live Telemetry Telemetry Status", container)
        d_layout = QGridLayout(data_group)
        d_layout.setSpacing(10)

        # Speed / Gear
        self.lbl_speed_gear = QLabel("0 KM/H  |  Gear: N", data_group)
        self.lbl_speed_gear.setStyleSheet("font-size: 15px; font-weight: bold; color: #00d2ff;")
        d_layout.addWidget(QLabel("Speed & Gear:", data_group), 0, 0)
        d_layout.addWidget(self.lbl_speed_gear, 0, 1)

        # Delta / Last Lap
        self.lbl_delta = QLabel("Δ --:--.---  (Last: --:--.---)", data_group)
        self.lbl_delta.setStyleSheet("font-size: 14px; font-weight: bold; color: #22c55e;")
        d_layout.addWidget(QLabel("Delta & Lap Time:", data_group), 0, 2)
        d_layout.addWidget(self.lbl_delta, 0, 3)

        # Inputs (Brake / Throttle)
        self.lbl_pedals = QLabel("THR: 0%  |  BRK: 0%", data_group)
        self.lbl_pedals.setStyleSheet("font-size: 14px; font-weight: bold; color: #ffffff;")
        d_layout.addWidget(QLabel("Pedal Inputs:", data_group), 1, 0)
        d_layout.addWidget(self.lbl_pedals, 1, 1)

        # Assists (ABS / TC)
        self.lbl_assists = QLabel("ABS: 0% (lvl 0)  |  TC: 0% (lvl 0)", data_group)
        self.lbl_assists.setStyleSheet("font-size: 14px; font-weight: bold; color: #a855f7;")
        d_layout.addWidget(QLabel("Electronic Assists:", data_group), 1, 2)
        d_layout.addWidget(self.lbl_assists, 1, 3)

        layout.addWidget(data_group)

        # ── 3. Overlay Positioning & Primary Settings ──
        cfg_group = QGroupBox("⚙️ Overlay Placement & Scaling", container)
        c_layout = QGridLayout(cfg_group)
        c_layout.setSpacing(10)

        # Slot selector
        c_layout.addWidget(QLabel("Screen Slot Position:", cfg_group), 0, 0)
        self.slot_combo = QComboBox(cfg_group)
        for s in HudSlot:
            self.slot_combo.addItem(s.value.replace("_", " ").title(), s)
        idx = self.slot_combo.findData(self.plugin.config.slot)
        if idx != -1:
            self.slot_combo.setCurrentIndex(idx)
        self.slot_combo.currentIndexChanged.connect(self._on_slot_changed)
        c_layout.addWidget(self.slot_combo, 0, 1)

        # Speed Unit selector
        c_layout.addWidget(QLabel("Speedometer Units:", cfg_group), 0, 2)
        self.unit_combo = QComboBox(cfg_group)
        self.unit_combo.addItem("KM/H (Metric)", "kmh")
        self.unit_combo.addItem("MPH (Imperial)", "mph")
        if self.plugin.config.speed_unit == "mph":
            self.unit_combo.setCurrentIndex(1)
        self.unit_combo.currentIndexChanged.connect(self._on_unit_changed)
        c_layout.addWidget(self.unit_combo, 0, 3)

        # Scale slider
        self.lbl_scale = QLabel(f"HUD Scale: {int(self.plugin.config.scale * 100)}%", cfg_group)
        c_layout.addWidget(self.lbl_scale, 1, 0)
        self.slider_scale = QSlider(Qt.Orientation.Horizontal, cfg_group)
        self.slider_scale.setRange(70, 150)
        self.slider_scale.setValue(int(self.plugin.config.scale * 100))
        self.slider_scale.valueChanged.connect(self._on_scale_changed)
        c_layout.addWidget(self.slider_scale, 1, 1)

        # Master visible checkbox
        self.chk_hud_visible = QCheckBox("Enable In-Game Overlay Display", cfg_group)
        self.chk_hud_visible.setChecked(self.plugin.config.hud_enabled)
        self.chk_hud_visible.toggled.connect(self._on_hud_toggled)
        c_layout.addWidget(self.chk_hud_visible, 1, 2, 1, 2)

        # Delta/Sector smoothing slider (HudTimeWindowAverage — see
        # widgets/display_cache.py): averaging window in milliseconds of
        # GAME time (not PC/wall-clock time) for the Delta Timer and Sector
        # Times live readouts. 0ms disables smoothing (latest raw sample).
        # Range capped at 2s — the 16s debug-only ceiling (for proving the
        # effect isn't a placebo, see hud_smoothing_logger.py) is gone now
        # that's confirmed; nothing usable in a real HUD needs more than this.
        window_ms = int(round(self.plugin.config.hud_smoothing_window_s * 1000))
        self.lbl_smoothing = QLabel(f"Delta/Sector Smoothing: {_format_smoothing_window(window_ms)} (game time)", cfg_group)
        c_layout.addWidget(self.lbl_smoothing, 2, 0)
        self.slider_smoothing = QSlider(Qt.Orientation.Horizontal, cfg_group)
        self.slider_smoothing.setRange(0, 2000)
        self.slider_smoothing.setValue(window_ms)
        self.slider_smoothing.valueChanged.connect(self._on_smoothing_window_changed)
        c_layout.addWidget(self.slider_smoothing, 2, 1, 1, 3)

        layout.addWidget(cfg_group)

        # ── 4. Modular Sub-Component Toggles ──
        mod_group = QGroupBox("🧩 Modular Component Toggles", container)
        m_layout = QGridLayout(mod_group)
        m_layout.setSpacing(10)

        # Speed & Gear
        self.chk_gear_speed = QCheckBox("Speedometer & Gear Display", mod_group)
        self.chk_gear_speed.setChecked(self.plugin.config.show_gear_speed)
        self.chk_gear_speed.toggled.connect(lambda v: self._update_flag("show_gear_speed", v))
        m_layout.addWidget(self.chk_gear_speed, 0, 0)

        # Rev Indicator Triangles
        self.chk_rev = QCheckBox("Rev Indicator Triangles (Under/Overrev)", mod_group)
        self.chk_rev.setChecked(self.plugin.config.show_rev_indicator)
        self.chk_rev.toggled.connect(lambda v: self._update_flag("show_rev_indicator", v))
        m_layout.addWidget(self.chk_rev, 0, 1)

        # 4-Tire Dynamics
        self.chk_tires = QCheckBox("4-Tire Tri-Axial Dynamics (Slip / Lock / Spin)", mod_group)
        self.chk_tires.setChecked(self.plugin.config.show_tires)
        self.chk_tires.toggled.connect(lambda v: self._update_flag("show_tires", v))
        m_layout.addWidget(self.chk_tires, 0, 2)

        # Pedal Inputs
        self.chk_pedals = QCheckBox("Throttle & Brake Pedal Gauges", mod_group)
        self.chk_pedals.setChecked(self.plugin.config.show_pedals)
        self.chk_pedals.toggled.connect(lambda v: self._update_flag("show_pedals", v))
        m_layout.addWidget(self.chk_pedals, 1, 0)

        # Electronic Assists (ABS / TC)
        self.chk_assists = QCheckBox("ABS & TC Electronic Assist Bars", mod_group)
        self.chk_assists.setChecked(self.plugin.config.show_assists)
        self.chk_assists.toggled.connect(lambda v: self._update_flag("show_assists", v))
        m_layout.addWidget(self.chk_assists, 1, 1)

        # Live Delta Chrono
        self.chk_delta = QCheckBox("Live Lap Delta / Finish Lap Time", mod_group)
        self.chk_delta.setChecked(self.plugin.config.show_delta)
        self.chk_delta.toggled.connect(lambda v: self._update_flag("show_delta", v))
        m_layout.addWidget(self.chk_delta, 1, 2)

        # Delta Timer display mode: live Delta (+/-) vs projected Expected time
        self.delta_mode_combo = QComboBox(mod_group)
        self.delta_mode_combo.addItem("Show Delta (+/-)", "delta")
        self.delta_mode_combo.addItem("Show Expected (finish time)", "expected")
        idx = self.delta_mode_combo.findData(self.plugin.config.delta_display_mode)
        self.delta_mode_combo.setCurrentIndex(idx if idx != -1 else 0)
        self.delta_mode_combo.currentIndexChanged.connect(self._on_delta_display_mode_changed)
        m_layout.addWidget(self.delta_mode_combo, 1, 3)

        # S1, S2, S3 Sectors
        self.chk_sectors = QCheckBox("S1, S2, S3 Sector Times & Deltas", mod_group)
        self.chk_sectors.setChecked(self.plugin.config.show_sectors)
        self.chk_sectors.toggled.connect(lambda v: self._update_flag("show_sectors", v))
        m_layout.addWidget(self.chk_sectors, 2, 0)

        # Aero Downforce
        self.chk_aero = QCheckBox("Aerodynamic Load Bar", mod_group)
        self.chk_aero.setChecked(self.plugin.config.show_aero)
        self.chk_aero.toggled.connect(lambda v: self._update_flag("show_aero", v))
        m_layout.addWidget(self.chk_aero, 2, 1)

        # Lap Validity & Clean Lap Badges
        self.chk_lap_status = QCheckBox("Lap Indicators (Validity & Clean/Dirty)", mod_group)
        self.chk_lap_status.setChecked(self.plugin.config.show_lap_status)
        self.chk_lap_status.toggled.connect(lambda v: self._update_flag("show_lap_status", v))
        m_layout.addWidget(self.chk_lap_status, 2, 2)

        # Fuel & Energy
        self.chk_energy = QCheckBox("Remaining Fuel / Energy & Laps", mod_group)
        self.chk_energy.setChecked(self.plugin.config.show_energy)
        self.chk_energy.toggled.connect(lambda v: self._update_flag("show_energy", v))
        m_layout.addWidget(self.chk_energy, 3, 0)

        # Cockpit Background Panel
        self.chk_bg = QCheckBox("Cockpit Chassis Dark Background", mod_group)
        self.chk_bg.setChecked(self.plugin.config.show_background)
        self.chk_bg.toggled.connect(lambda v: self._update_flag("show_background", v))
        m_layout.addWidget(self.chk_bg, 3, 1)

        layout.addWidget(mod_group)
        layout.addStretch()

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    def set_idle_mode(self, is_idle: bool) -> None:
        """Switch between active rendering and power-saving idle mode."""
        self._is_idle = is_idle
        if not is_idle:
            self.update_telemetry_ui(self.plugin.latest_sensors)
            self.update_delta_ui(self.plugin.latest_delta)

    def update_telemetry_ui(self, sensors: VehicleSensors) -> None:
        """Update telemetry numbers and refresh preview canvas."""
        if getattr(self, "_is_idle", False):
            return

        spd = sensors.vehicle_speed * 3.6
        unit = "KM/H"
        if self.plugin.config.speed_unit == "mph":
            spd *= 0.621371
            unit = "MPH"

        gear_str = "R" if sensors.gear == -1 else ("N" if sensors.gear == 0 else str(sensors.gear))
        self.lbl_speed_gear.setText(f"{spd:.1f} {unit}  |  Gear: {gear_str}")

        delta_str = sensors.last_lap_time_str if sensors.is_lap_freeze_active else sensors.delta_time_str
        self.lbl_delta.setText(f"Δ {delta_str}  (Last: {sensors.last_lap_time_str})")

        th = int(sensors.unfiltered_throttle * 100.0)
        brk = int(sensors.unfiltered_brake * 100.0)
        self.lbl_pedals.setText(f"THR: {th}%  |  BRK: {brk}%")

        abs_pct = int(sensors.ecu_abs_active * 100.0)
        tc_pct = int(max(sensors.ecu_tc_active, sensors.spin_intensity) * 100.0)
        self.lbl_assists.setText(f"ABS: {abs_pct}% (lvl {sensors.ecu.abs.level})  |  TC: {tc_pct}% (lvl {sensors.ecu.tc.level})")
        self.preview_canvas.update()

    def update_delta_ui(self, delta: LapDeltaPacket) -> None:
        """Update live delta indicators from authoritative LapDeltaPacket."""
        if getattr(self, "_is_idle", False) or not self.isVisible():
            return
        delta_display = delta.last_lap_time_str if delta.is_lap_freeze_active else delta.delta_str
        self.lbl_delta.setText(f"Δ {delta_display}  (Last: {delta.last_lap_time_str})")
        self.preview_canvas.update()

    def _on_slot_changed(self, index: int) -> None:
        slot = self.slot_combo.currentData()
        self.plugin.config.slot = slot
        self.plugin.save_config()

    def _on_unit_changed(self, index: int) -> None:
        unit = self.unit_combo.currentData()
        self.plugin.config.speed_unit = unit
        self.plugin.save_config()
        self.preview_canvas.update()

    def _on_scale_changed(self, val: int) -> None:
        scale = val / 100.0
        self.plugin.config.scale = scale
        self.lbl_scale.setText(f"HUD Scale: {val}%")
        self.plugin.save_config()

    def _on_hud_toggled(self, checked: bool) -> None:
        self.plugin.config.hud_enabled = checked
        self.plugin.save_config()

    def _on_smoothing_window_changed(self, window_ms: int) -> None:
        self.plugin.config.hud_smoothing_window_s = window_ms / 1000.0
        self.lbl_smoothing.setText(f"Delta/Sector Smoothing: {_format_smoothing_window(window_ms)} (game time)")
        self.plugin.save_config()

    def _on_delta_display_mode_changed(self, index: int) -> None:
        self.plugin.config.delta_display_mode = self.delta_mode_combo.currentData()
        self.plugin.save_config()
        self.preview_canvas.update()

    def _update_flag(self, field_name: str, val: bool) -> None:
        setattr(self.plugin.config, field_name, val)
        self.plugin.save_config()
        self.preview_canvas.update()
