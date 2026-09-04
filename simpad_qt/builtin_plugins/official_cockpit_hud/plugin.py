"""
Official SimPad Center Cockpit HUD Plugin (Qt6 Pure).

Orchestrates the 12 modular HUD widgets:
- Speedometer & Gear display with <60 km/h backdrop box.
- Underrev / Overrev warning triangles.
- 4-Tire tri-axial slip/lock/spin physical model gauges.
- Dual pedal bars (Throttle green, Brake red).
- Electronic assists (ABS purple, TC cyan) with level readouts.
- Live lap delta timer & finish line lap freeze (purple/green/yellow/invalid).
- S1, S2, S3 Sector times with live sector delta indicators.
- Aerodynamic downforce bar (4-stage color ramp).
- Lap validity & Clean lap badges (SVG icons, separate layer).
- Remaining energy & laps counter.
"""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from PySide6.QtCore import QSize
from PySide6.QtGui import QPainter, QFontDatabase
from PySide6.QtWidgets import QWidget

from simpad_qt.plugins.contracts import (
    SimPadPlugin, PluginMetadata, PluginContext,
    ITabProvider, ITelemetrySubscriber, IDeltaSubscriber, IHudWidgetProvider, HudSlot
)
from simpad_qt.core.reference_lap import LapDeltaPacket
from simpad_qt.core.telemetry import VehicleSensors, TelemetryStateStore
from simpad_qt.builtin_plugins.official_cockpit_hud.widgets import (
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
    QtLapStatusWidget,
    QtEnergyLapsWidget,
)

# Modular imports from submodules
from simpad_qt.builtin_plugins.official_cockpit_hud.config import OfficialCockpitHudConfig
from simpad_qt.builtin_plugins.official_cockpit_hud.preview_canvas import OfficialHudPreviewCanvas
from simpad_qt.builtin_plugins.official_cockpit_hud.tab_widget import OfficialCockpitHudTabWidget

logger = logging.getLogger("simpad.plugin.official_cockpit_hud")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class OfficialCockpitHudPlugin(SimPadPlugin, ITabProvider, ITelemetrySubscriber, IDeltaSubscriber, IHudWidgetProvider):
    """
    Official SimPad Center Cockpit Racing HUD Plugin.
    Implements Tab, Telemetry, and high-performance vector HUD rendering for the 12-widget telemetry suite.
    """

    def __init__(self):
        super().__init__(PluginMetadata(
            id="simpad.builtin.official_cockpit_hud",
            name="Official Cockpit HUD",
            version="2.0.0",
            author="SimPad Team",
            description="Official SimPad Center Cockpit Racing HUD: Speedometer, Gear, Rev Triangles, 4-Tire Slip Dynamics, Live Delta, Sectors S1/S2/S3, Assists (ABS/TC), Pedals, Downforce, Clean/Valid Lap Badges & Energy.",
            icon="🏎️",
            tags=("hud", "official", "cockpit", "telemetry", "overlay", "racing")
        ))
        self.config: OfficialCockpitHudConfig = OfficialCockpitHudConfig()
        self.latest_sensors: VehicleSensors = VehicleSensors()
        self.latest_delta: LapDeltaPacket = LapDeltaPacket()

        # Font configuration
        self.font_family: str = self._load_custom_font()

        # Instantiate all 12 modular HUD widgets
        self.widget_abs = QtAbsGaugeWidget()
        self.widget_brake = QtBrakeGaugeWidget()
        self.widget_tires = QtTiresGaugeWidget()
        self.widget_throttle = QtThrottleGaugeWidget()
        self.widget_tc = QtTcGaugeWidget()
        self.widget_gear_speed = QtGearSpeedWidget(font_family=self.font_family)
        self.widget_rev = QtRevIndicatorWidget()
        self.widget_aero = QtAeroBarWidget()
        plugin_icons_dir = Path(__file__).resolve().parent / "icons"
        self.widget_lap_status = QtLapStatusWidget(icons_dir=plugin_icons_dir)
        self.widget_delta = QtDeltaTimerWidget(font_family=self.font_family)
        self.widget_energy = QtEnergyLapsWidget(font_family=self.font_family)
        self.widget_sectors = QtSectorTimesWidget(font_family=self.font_family)

        self._active_tab_widget: Optional[OfficialCockpitHudTabWidget] = None

    def _load_custom_font(self) -> str:
        """Load Anta-Regular.ttf custom racing font from plugin fonts folder."""
        font_path = Path(__file__).resolve().parent / "fonts" / "Anta-Regular.ttf"
        if not font_path.exists():
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
    # Polymorphic Telemetry State Event Hooks
    # =========================================================================

    def on_physics_tick(self, state: TelemetryStateStore) -> None:
        """Called directly on high-frequency physics tick (100-120Hz) from central state store."""
        pass

    def on_scoring_update(self, state: TelemetryStateStore) -> None:
        """Called directly on scoring update (10Hz) from central state store."""
        pass

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
            "hit_count_current_lap": getattr(
                sensors,
                "hit_count_current_lap",
                TelemetryStateStore.get_instance().hit_count_current_lap,
            ),
            "is_clean_lap": getattr(
                sensors,
                "is_clean_lap",
                TelemetryStateStore.get_instance().is_clean_lap,
            ),
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

        # 6. Aerodynamic Downforce Bar
        if self.config.show_aero:
            self.widget_aero.paint(painter, canvas_w, canvas_h, sensors, extra_data)

        # 6b. Lap Status & Clean Lap Indicators (Separate Layer)
        if self.config.show_lap_status:
            self.widget_lap_status.paint(painter, canvas_w, canvas_h, sensors, extra_data)

        # 7. Live Lap Delta & Finished Lap Time
        if self.config.show_delta:
            self.widget_delta.paint(painter, canvas_w, canvas_h, sensors, extra_data)

        # 8. Remaining Energy & Laps
        if self.config.show_energy:
            self.widget_energy.paint(painter, canvas_w, canvas_h, sensors, extra_data)

        # 9. S1, S2, S3 Sector Times
        if self.config.show_sectors:
            self.widget_sectors.paint(painter, canvas_w, canvas_h, sensors, extra_data)


# Re-export for backward compatibility
__all__ = [
    "OfficialCockpitHudPlugin",
    "OfficialCockpitHudConfig",
    "OfficialCockpitHudTabWidget",
    "OfficialHudPreviewCanvas",
]
