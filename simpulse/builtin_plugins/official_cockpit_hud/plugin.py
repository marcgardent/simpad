"""
Official SimPulse Center Cockpit HUD Plugin (Qt6 Pure).

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
from typing import Optional

from PySide6.QtCore import QSize, QRectF, QPointF
from PySide6.QtGui import QPainter, QFontDatabase, QColor, QBrush, QPen, QLinearGradient
from PySide6.QtWidgets import QWidget

from simpulse_sdk import (
    SimPulsePlugin, PluginMetadata, PluginContext,
    ITabProvider, ITelemetrySubscriber, IDeltaSubscriber, IHudWidgetProvider, HudSlot,
    ITelemetryStateSubscriber,
    LapDeltaPacket, VehicleSensors, TelemetryStateStore, TelemetryView
)
from simpulse.builtin_plugins.official_cockpit_hud.widgets import (
    CockpitWidgetContext,
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
from simpulse.builtin_plugins.official_cockpit_hud.config import OfficialCockpitHudConfig
from simpulse.builtin_plugins.official_cockpit_hud.preview_canvas import OfficialHudPreviewCanvas
from simpulse.builtin_plugins.official_cockpit_hud.tab_widget import OfficialCockpitHudTabWidget

logger = logging.getLogger("simpulse.plugin.official_cockpit_hud")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class OfficialCockpitHudPlugin(
    SimPulsePlugin, ITabProvider, ITelemetrySubscriber, IDeltaSubscriber,
    ITelemetryStateSubscriber, IHudWidgetProvider,
):
    """
    Official SimPulse Center Cockpit Racing HUD Plugin.
    Implements Tab, Telemetry, and high-performance vector HUD rendering for the 12-widget telemetry suite.
    """

    def __init__(self):
        super().__init__(PluginMetadata(
            id="simpulse.builtin.official_cockpit_hud",
            name="Official Cockpit HUD",
            version="2.0.0",
            author="SimPulse Team",
            description="Official SimPulse Center Cockpit Racing HUD: Speedometer, Gear, Rev Triangles, 4-Tire Slip Dynamics, Live Delta, Sectors S1/S2/S3, Assists (ABS/TC), Pedals, Downforce, Clean/Valid Lap Badges & Energy.",
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
        from simpulse.core.telemetry_channels import TelemetryChannel, ChannelRequirement
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

    def on_physics_tick(self, state: TelemetryView) -> None:
        """Called directly on high-frequency physics tick (100-120Hz).

        Despite the historical type hint, the dispatcher (PluginManager
        CHANNEL_ROUTING) hands non-raw-ingest plugins the consolidated
        TelemetryView snapshot, not the raw Store — ``.delta`` there is
        already the plain ``Optional[LapDeltaPacket]`` (no ``.data`` wrapper;
        that only exists on the raw Store's PacketSlot).
        """
        if state.delta is not None:
            self.latest_delta = state.delta
            if self._active_tab_widget and self._active_tab_widget.isVisible() and not getattr(self._active_tab_widget, "_is_idle", False):
                self._active_tab_widget.update_delta_ui(state.delta)

    def on_scoring_update(self, state: TelemetryView) -> None:
        """Called directly on scoring update (10Hz) from central state store."""
        pass

    # =========================================================================
    # ITelemetrySubscriber & IDeltaSubscriber
    # =========================================================================

    def on_telemetry_frame(self, sensors: VehicleSensors) -> None:
        self.latest_sensors = sensors
        if self._active_tab_widget and self._active_tab_widget.isVisible() and not getattr(self._active_tab_widget, "_is_idle", False):
            self._active_tab_widget.update_telemetry_ui(sensors)

    def on_delta_frame(self, delta_packet: LapDeltaPacket) -> None:
        self.latest_delta = delta_packet
        if self._active_tab_widget and self._active_tab_widget.isVisible() and not getattr(self._active_tab_widget, "_is_idle", False):
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

    def _get_background_rect(self, width: float, height: float) -> QRectF:
        """Compute bounding rectangle encompassing all displayed HUD widgets."""
        scale_x = width / 800.0
        scale_y = (height * 2.0) / 600.0
        center_x = width / 2.0

        min_x = center_x - (145.0 * scale_x)
        max_x = center_x + (145.0 * scale_x)

        if getattr(self.config, "show_energy", True):
            max_x = max(max_x, width - (12.0 * scale_x))
            min_x = min(min_x, 12.0 * scale_x)

        if getattr(self.config, "show_assists", True):
            min_x = min(min_x, center_x - (276.0 * scale_x))
            max_x = max(max_x, center_x + (276.0 * scale_x))
        elif getattr(self.config, "show_pedals", True):
            min_x = min(min_x, center_x - (258.0 * scale_x))
            max_x = max(max_x, center_x + (258.0 * scale_x))
        elif getattr(self.config, "show_tires", True):
            min_x = min(min_x, center_x - (224.0 * scale_x))
            max_x = max(max_x, center_x + (224.0 * scale_x))

        top_y = 6.0 * scale_y
        bottom_y = height - (4.0 * scale_y)

        min_x = max(3.0, min_x)
        max_x = min(width - 3.0, max_x)

        return QRectF(min_x, top_y, max_x - min_x, bottom_y - top_y)

    @staticmethod
    def _paint_hud_background(painter: QPainter, rect: QRectF) -> None:
        """Render high-tech semi-transparent dark carbon/acrylic chassis container."""
        painter.save()
        radius = 10.0

        # Frosted dark motorsport gradient
        grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        grad.setColorAt(0.0, QColor(15, 23, 42, 225))
        grad.setColorAt(0.5, QColor(10, 15, 26, 240))
        grad.setColorAt(1.0, QColor(6, 9, 16, 250))

        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor(51, 65, 85, 200), 1.5))
        painter.drawRoundedRect(rect, radius, radius)

        # Neon cyan top edge accent
        top_glow = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.top())
        top_glow.setColorAt(0.0, QColor(0, 210, 255, 0))
        top_glow.setColorAt(0.3, QColor(0, 210, 255, 80))
        top_glow.setColorAt(0.5, QColor(56, 189, 248, 140))
        top_glow.setColorAt(0.7, QColor(0, 210, 255, 80))
        top_glow.setColorAt(1.0, QColor(0, 210, 255, 0))

        glow_pen = QPen(QBrush(top_glow), 2.0)
        painter.setPen(glow_pen)
        painter.drawLine(
            QPointF(rect.left() + radius, rect.top() + 1.0),
            QPointF(rect.right() - radius, rect.top() + 1.0)
        )

        # Bottom bezel highlight line
        painter.setPen(QPen(QColor(30, 41, 59, 130), 1.0))
        painter.drawLine(
            QPointF(rect.left() + radius, rect.bottom() - 1.0),
            QPointF(rect.right() - radius, rect.bottom() - 1.0)
        )

        painter.restore()

    def paint_hud(
        self,
        painter: QPainter,
        width: float,
        height: float,
        sensors: VehicleSensors,
    ) -> None:
        """
        Vector rendering routine for the official SimPulse HUD overlay suite.
        Maps the 800x600 modular widgets perfectly into the allocated slot rect.
        """
        # 0. Encompassing Dark Cockpit Chassis Background
        if getattr(self.config, "show_background", True):
            bg_rect = self._get_background_rect(width, height)
            self._paint_hud_background(painter, bg_rect)

        # Virtual canvas scaling: base 800x600 widgets use top half (0..300)
        canvas_w = width
        canvas_h = height * 2.0

        store = TelemetryStateStore.get_instance()
        context = CockpitWidgetContext(
            sensors=sensors,
            speed_unit=self.config.speed_unit,
            hit_count=store.hit_count_current_lap,
            is_clean_lap=store.is_clean_lap,
            delta_display_mode=self.config.delta_display_mode,
            hud_smoothing_window_s=self.config.hud_smoothing_window_s,
            game_time_s=store.timing.current_et,
        )

        # 1. Electronic Assists (ABS / TC)
        if self.config.show_assists:
            self.widget_abs.paint(painter, canvas_w, canvas_h, context)
            self.widget_tc.paint(painter, canvas_w, canvas_h, context)

        # 2. Driver Pedal Inputs (Brake / Throttle)
        if self.config.show_pedals:
            self.widget_brake.paint(painter, canvas_w, canvas_h, context)
            self.widget_throttle.paint(painter, canvas_w, canvas_h, context)

        # 3. 4-Tires Tri-Axial Dynamics
        if self.config.show_tires:
            self.widget_tires.paint(painter, canvas_w, canvas_h, context)

        # 4. Speedometer & Engaged Gear
        if self.config.show_gear_speed:
            self.widget_gear_speed.paint(painter, canvas_w, canvas_h, context)

        # 5. Rev Warning Triangles
        if self.config.show_rev_indicator:
            self.widget_rev.paint(painter, canvas_w, canvas_h, context)

        # 6. Aerodynamic Downforce Bar
        if self.config.show_aero:
            self.widget_aero.paint(painter, canvas_w, canvas_h, context)

        # 6b. Lap Status & Clean Lap Indicators (Separate Layer)
        if self.config.show_lap_status:
            self.widget_lap_status.paint(painter, canvas_w, canvas_h, context)

        # 7. Live Lap Delta & Finished Lap Time
        if self.config.show_delta:
            self.widget_delta.paint(painter, canvas_w, canvas_h, context)

        # 8. Remaining Energy & Laps
        if self.config.show_energy:
            self.widget_energy.paint(painter, canvas_w, canvas_h, context)

        # 9. S1, S2, S3 Sector Times
        if self.config.show_sectors:
            self.widget_sectors.paint(painter, canvas_w, canvas_h, context)


# Re-export for backward compatibility
__all__ = [
    "OfficialCockpitHudPlugin",
    "OfficialCockpitHudConfig",
    "OfficialCockpitHudTabWidget",
    "OfficialHudPreviewCanvas",
]
