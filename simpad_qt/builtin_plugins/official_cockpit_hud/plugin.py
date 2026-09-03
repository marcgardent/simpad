"""
Official SimPad Center Cockpit HUD Plugin (Qt6 Pure).

Migrates the official SimPad modular overlay:
- Speedometer & Gear display with <60 km/h backdrop box.
- Underrev / Overrev warning triangles.
- 4-Tire tri-axial slip/lock/spin physical model gauges.
- Dual pedal bars (Throttle green, Brake red).
- Electronic assists (ABS purple, TC cyan) with level readouts.
- Live lap delta timer & finish line lap freeze (purple/green/yellow/dirty).
- S1, S2, S3 Sector times with live sector delta indicators.
- Aerodynamic downforce bar (4-stage color ramp) & clean lap indicator dot.
- Remaining energy & laps counter.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any, List

from PySide6.QtCore import Qt, QSize, QRectF, QPointF
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QFontDatabase
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QComboBox, QCheckBox, QGroupBox, QSlider, QScrollArea, QFrame
)

from simpad_qt.plugins.contracts import (
    SimPadPlugin, PluginMetadata, PluginContext,
    ITabProvider, ITelemetrySubscriber, IDeltaSubscriber, IHudWidgetProvider, HudSlot
)
from simpad_qt.core.reference_lap import LapDeltaPacket
from src.telemetry.sensors import VehicleSensors
from src.gui.overlay.widgets import (
    QtGearSpeedWidget,
    QtRevIndicatorWidget,
    QtAbsGaugeWidget,
    QtBrakeGaugeWidget,
    QtThrottleGaugeWidget,
    QtTcGaugeWidget,
    QtTiresGaugeWidget,
    QtDeltaTimerWidget,
    QtSectorTimesWidget,
    QtAeroBarWidget,
    QtEnergyLapsWidget,
)

logger = logging.getLogger("simpad.plugin.official_cockpit_hud")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


@dataclass
class OfficialCockpitHudConfig:
    """Strongly-typed configuration schema for the Official Cockpit HUD."""
    slot: HudSlot = HudSlot.COCKPIT_CENTER
    hud_enabled: bool = True
    speed_unit: str = "kmh"          # "kmh" or "mph"
    scale: float = 1.0               # 0.7 to 1.5 multiplier
    show_gear_speed: bool = True
    show_rev_indicator: bool = True
    show_pedals: bool = True
    show_assists: bool = True
    show_tires: bool = True
    show_delta: bool = True
    show_sectors: bool = True
    show_aero: bool = True
    show_energy: bool = True


class OfficialHudPreviewCanvas(QWidget):
    """
    Live interactive vector preview canvas rendered inside the Studio Tab.
    Displays pixel-identical HUD graphics as seen in-game.
    """

    def __init__(self, plugin: OfficialCockpitHudPlugin, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.plugin = plugin
        self.setMinimumSize(640, 300)
        self.setFixedHeight(310)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

            w = float(self.width())
            h = float(self.height())

            # Dark cockpit background container with subtle grid / border
            bg_rect = QRectF(0, 0, w, h)
            painter.setPen(QPen(QColor(30, 41, 59, 180), 1.5))
            painter.setBrush(QBrush(QColor(10, 14, 20, 240)))
            painter.drawRoundedRect(bg_rect, 8.0, 8.0)

            # Paint HUD widgets inside local coordinate bounds
            self.plugin.paint_hud(painter, w, h, self.plugin.latest_sensors)

        finally:
            painter.end()


class OfficialCockpitHudTabWidget(QWidget):
    """
    Studio Tab Widget for the Official Cockpit HUD.
    Provides live telemetry previews, real-time metrics readouts, and extensive configuration toggles.
    """

    def __init__(self, plugin: OfficialCockpitHudPlugin, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.plugin = plugin
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

        # S1, S2, S3 Sectors
        self.chk_sectors = QCheckBox("S1, S2, S3 Sector Times & Deltas", mod_group)
        self.chk_sectors.setChecked(self.plugin.config.show_sectors)
        self.chk_sectors.toggled.connect(lambda v: self._update_flag("show_sectors", v))
        m_layout.addWidget(self.chk_sectors, 2, 0)

        # Aero Downforce & Cleanlap
        self.chk_aero = QCheckBox("Aerodynamic Load Bar & Clean Lap Indicator", mod_group)
        self.chk_aero.setChecked(self.plugin.config.show_aero)
        self.chk_aero.toggled.connect(lambda v: self._update_flag("show_aero", v))
        m_layout.addWidget(self.chk_aero, 2, 1)

        # Fuel & Energy
        self.chk_energy = QCheckBox("Remaining Fuel / Energy & Laps", mod_group)
        self.chk_energy.setChecked(self.plugin.config.show_energy)
        self.chk_energy.toggled.connect(lambda v: self._update_flag("show_energy", v))
        m_layout.addWidget(self.chk_energy, 2, 2)

        layout.addWidget(mod_group)
        layout.addStretch()

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    def update_telemetry_ui(self, sensors: VehicleSensors) -> None:
        """Update telemetry numbers and refresh preview canvas."""
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
        self.lbl_assists.setText(f"ABS: {abs_pct}% (lvl {sensors.ecu_abs_level})  |  TC: {tc_pct}% (lvl {sensors.ecu_tc_level})")
        self.preview_canvas.update()

    def update_delta_ui(self, delta: LapDeltaPacket) -> None:
        """Update live delta indicators from authoritative LapDeltaPacket."""
        if not self.isVisible():
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

    def _update_flag(self, field_name: str, val: bool) -> None:
        setattr(self.plugin.config, field_name, val)
        self.plugin.save_config()
        self.preview_canvas.update()


class OfficialCockpitHudPlugin(SimPadPlugin, ITabProvider, ITelemetrySubscriber, IDeltaSubscriber, IHudWidgetProvider):
    """
    Official SimPad Center Cockpit Racing HUD Plugin.
    Implements Tab, Telemetry, and high-performance vector HUD rendering for the entire 11-widget telemetry suite.
    """

    def __init__(self):
        super().__init__(PluginMetadata(
            id="simpad.builtin.official_cockpit_hud",
            name="Official Cockpit HUD",
            version="2.0.0",
            author="SimPad Team",
            description="Official SimPad Center Cockpit Racing HUD: Speedometer, Gear, Rev Triangles, 4-Tire Slip Dynamics, Live Delta, Sectors S1/S2/S3, Assists (ABS/TC), Pedals, Downforce & Energy.",
            icon="🏎️",
            tags=("hud", "official", "cockpit", "telemetry", "overlay", "racing")
        ))
        self.config: OfficialCockpitHudConfig = OfficialCockpitHudConfig()
        self.latest_sensors: VehicleSensors = VehicleSensors()
        self.latest_delta: LapDeltaPacket = LapDeltaPacket()

        # Font configuration
        self.font_family: str = self._load_custom_font()

        # Instantiate all 11 modular HUD widgets
        self.widget_abs = QtAbsGaugeWidget()
        self.widget_brake = QtBrakeGaugeWidget()
        self.widget_tires = QtTiresGaugeWidget()
        self.widget_throttle = QtThrottleGaugeWidget()
        self.widget_tc = QtTcGaugeWidget()
        self.widget_gear_speed = QtGearSpeedWidget(font_family=self.font_family)
        self.widget_rev = QtRevIndicatorWidget()
        self.widget_aero = QtAeroBarWidget()
        self.widget_delta = QtDeltaTimerWidget(font_family=self.font_family)
        self.widget_energy = QtEnergyLapsWidget(font_family=self.font_family)
        self.widget_sectors = QtSectorTimesWidget(font_family=self.font_family)

        self._active_tab_widget: Optional[OfficialCockpitHudTabWidget] = None

    def _load_custom_font(self) -> str:
        """Load Anta-Regular.ttf custom racing font if available."""
        font_path = _PROJECT_ROOT / "assets" / "fonts" / "Anta-Regular.ttf"
        if font_path.exists():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            if font_id != -1:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    return families[0]
        return "Segoe UI"

    def get_channel_requirements(self) -> list:
        from simpad_qt.core.telemetry_channels import TelemetryChannel, ChannelRequirement
        return [
            ChannelRequirement(
                channel=TelemetryChannel.TELEMETRY,
                preferred_hz=100,
                required=True,
                reason="High-frequency calculation of vehicle speed, gear, RPM, pedals, tire slip & assists"
            ),
            ChannelRequirement(
                channel=TelemetryChannel.COMPACT_SCORING,
                preferred_hz=10,
                required=True,
                reason="Real-time lap delta time, finish line lap freeze, S1/S2/S3 sector times & flags"
            ),
            ChannelRequirement(
                channel=TelemetryChannel.EXTENDED_STATE,
                preferred_hz=10,
                required=False,
                reason="ECU ABS and TC active levels and vehicle state flags"
            ),
        ]

    def on_load(self, context: PluginContext) -> None:
        super().on_load(context)
        self.config = context.get_typed_config(OfficialCockpitHudConfig)
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
        return "Cockpit HUD"

    def get_tab_icon(self) -> str:
        return "🏎️"

    def create_tab_widget(self, parent: Optional[QWidget] = None) -> QWidget:
        self._active_tab_widget = OfficialCockpitHudTabWidget(self, parent)
        return self._active_tab_widget

    # =========================================================================
    # ITelemetrySubscriber & IDeltaSubscriber
    # =========================================================================

    def on_telemetry_frame(self, sensors: VehicleSensors) -> None:
        self.latest_sensors = sensors
        if self._active_tab_widget and self._active_tab_widget.isVisible():
            self._active_tab_widget.update_telemetry_ui(sensors)

    def on_delta_frame(self, delta_packet: LapDeltaPacket) -> None:
        self.latest_delta = delta_packet
        if self._active_tab_widget and self._active_tab_widget.isVisible():
            self._active_tab_widget.update_delta_ui(delta_packet)

    # =========================================================================
    # IHudWidgetProvider
    # =========================================================================

    @property
    def preferred_slot(self) -> HudSlot:
        return self.config.slot

    def get_hud_size(self) -> QSize:
        """Return scaled bounding box for the complete HUD (Default 640x300)."""
        base_w = 640.0 * self.config.scale
        base_h = 300.0 * self.config.scale
        return QSize(max(320, int(base_w)), max(150, int(base_h)))

    def is_hud_visible(self) -> bool:
        return self.config.hud_enabled

    def paint_hud(
        self,
        painter: QPainter,
        width: float,
        height: float,
        sensors: VehicleSensors,
    ) -> None:
        """
        Vector rendering routine for the official SimPad HUD overlay suite.
        Maps the 800x600 modular widgets perfectly into the allocated slot rect.
        """
        # Virtual canvas scaling: base 800x600 widgets use top half (0..300)
        canvas_w = width
        canvas_h = height * 2.0

        # Calculate speed in configured unit
        raw_speed = sensors.vehicle_speed * 3.6
        if self.config.speed_unit == "mph":
            raw_speed *= 0.621371

        throttle_pct = sensors.unfiltered_throttle * 100.0
        brake_pct = sensors.unfiltered_brake * 100.0

        extra_data: Dict[str, Any] = {
            "speed": raw_speed,
            "gear": "R" if sensors.gear == -1 else ("N" if sensors.gear == 0 else str(sensors.gear)),
            "expectedTime": sensors.last_lap_time_str if sensors.is_lap_freeze_active else sensors.delta_time_str,
            "delta": sensors.delta_time_str,
            "estimatedLapTime": sensors.estimated_lap_time_str,
            "lastLapTime": sensors.last_lap_time_str,
            "lastLapStatus": sensors.last_lap_status,
            "isLapFreezeActive": sensors.is_lap_freeze_active,
            "sectors": sensors.sectors_list,
            "energyLaps": sensors.fuel_level,
            "remainingLaps": sensors.remaining_laps,
            "aero": sensors.aero_load * 100.0,
            "brake": brake_pct,
            "throttle": throttle_pct,
            "abs": sensors.ecu_abs_active * 100.0,
            "tc": max(sensors.ecu_tc_active, sensors.spin_intensity) * 100.0,
            "overbrake": sensors.lock_intensity > 0.05,
            "wheelspin": sensors.spin_intensity > 0.05,
            "underrev": sensors.underrev_intensity > 0.1,
            "overrev": sensors.overrev_intensity > 0.1,
            "lap_flag": sensors.lap_flag,
            "is_pit_lap": sensors.is_pit_lap,
        }

        # 1. Electronic Assists (ABS / TC)
        if self.config.show_assists:
            self.widget_abs.paint(painter, canvas_w, canvas_h, sensors, extra_data)
            self.widget_tc.paint(painter, canvas_w, canvas_h, sensors, extra_data)

        # 2. Driver Pedal Inputs (Brake / Throttle)
        if self.config.show_pedals:
            self.widget_brake.paint(painter, canvas_w, canvas_h, sensors, extra_data)
            self.widget_throttle.paint(painter, canvas_w, canvas_h, sensors, extra_data)

        # 3. 4-Tires Tri-Axial Dynamics
        if self.config.show_tires:
            self.widget_tires.paint(painter, canvas_w, canvas_h, sensors, extra_data)

        # 4. Speedometer & Engaged Gear
        if self.config.show_gear_speed:
            self.widget_gear_speed.paint(painter, canvas_w, canvas_h, sensors, extra_data)

        # 5. Rev Warning Triangles
        if self.config.show_rev_indicator:
            self.widget_rev.paint(painter, canvas_w, canvas_h, sensors, extra_data)

        # 6. Aerodynamic Downforce Bar & Clean Lap Dot
        if self.config.show_aero:
            self.widget_aero.paint(painter, canvas_w, canvas_h, sensors, extra_data)

        # 7. Live Lap Delta & Finished Lap Time
        if self.config.show_delta:
            self.widget_delta.paint(painter, canvas_w, canvas_h, sensors, extra_data)

        # 8. Remaining Energy & Laps
        if self.config.show_energy:
            self.widget_energy.paint(painter, canvas_w, canvas_h, sensors, extra_data)

        # 9. S1, S2, S3 Sector Times
        if self.config.show_sectors:
            self.widget_sectors.paint(painter, canvas_w, canvas_h, sensors, extra_data)
