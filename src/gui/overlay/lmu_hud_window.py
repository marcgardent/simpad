"""
SimPad PySide6 Native LMU HUD Overlay Window.
Orchestrates all 8 modular racing HUD widgets on a hardware-accelerated 60 FPS transparent canvas.
Positioned at 2nd horizontal third (middle) and 2nd vertical half (bottom) of screen.
Supports Linux (KDE Plasma Wayland & X11) and Windows with Frameless, AlwaysOnTop, and ClickThrough.
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

# Ensure XCB compatibility for KWin state sync
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter, QFontDatabase
from PySide6.QtWidgets import QWidget, QApplication

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
    QtLapStatusWidget,
    QtEnergyLapsWidget,
)
from src.telemetry.sensors import VehicleSensors
from src.telemetry.state_store import TelemetryStateStore
from src.utils.window_utils import get_hud_rect, _PROJECT_ROOT


class LmuHudQtWindow(QWidget):
    """
    PySide6 HUD Overlay Window: 100% transparent and Always-On-Top.
    Orchestrates LMU telemetry widgets without any black background.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SimPad LMU HUD Overlay (Qt6)")

        # 1. Load Anta-Regular racing font
        self.font_family = self._load_custom_font()

        # 2. Modular instantiation of 12 HUD widgets
        self._widgets = [
            QtAbsGaugeWidget(),
            QtBrakeGaugeWidget(),
            QtTiresGaugeWidget(),
            QtThrottleGaugeWidget(),
            QtTcGaugeWidget(),
            QtGearSpeedWidget(font_family=self.font_family),
            QtRevIndicatorWidget(),
            QtAeroBarWidget(),
            QtLapStatusWidget(),
            QtDeltaTimerWidget(font_family=self.font_family),
            QtEnergyLapsWidget(font_family=self.font_family),
            QtSectorTimesWidget(font_family=self.font_family),
        ]

        self._sensors = VehicleSensors()
        self._extra_data: Dict[str, Any] = {}

        # 3. Configure window flags (Transparent, AlwaysOnTop, ClickThrough)
        self._apply_window_flags()

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self.update_geometry()

        # 120 FPS timer for fluid responsive continuous rendering
        self._timer = QTimer(self)
        self._timer.setInterval(8)
        self._timer.timeout.connect(self.update)
        self._timer.start()

    def _load_custom_font(self) -> str:
        """Loads Anta-Regular.ttf into the Qt font database."""
        font_path = _PROJECT_ROOT / "simpad_qt" / "builtin_plugins" / "official_cockpit_hud" / "fonts" / "Anta-Regular.ttf"
        if not font_path.exists():
            font_path = _PROJECT_ROOT / "assets" / "fonts" / "Anta-Regular.ttf"
        if font_path.exists():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            if font_id != -1:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    return families[0]
        return "Segoe UI"

    def _apply_window_flags(self) -> None:
        """Applies window flags for transparent click-through overlay."""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )

    def update_geometry(self) -> None:
        """Covers entire physical screen to allow flexible widget placement."""
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.geometry()
            self.setGeometry(0, 0, geo.width(), geo.height())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.update_geometry()
        QTimer.singleShot(100, self._enforce_kwin_keep_above)

    def _enforce_kwin_keep_above(self) -> None:
        """Sends KWin DBus command to enforce absolute top plane under KDE Wayland."""
        try:
            script_dir = Path.home() / ".cache" / "simpad"
            script_dir.mkdir(parents=True, exist_ok=True)
            script_path = script_dir / "kwin_force_hud.js"
            script_code = 'workspace.windowList().forEach(function(w) { if (w.caption.indexOf("LMU HUD Overlay") !== -1) { w.keepAbove = true; w.noBorder = true; w.skipTaskbar = true; } });'
            script_path.write_text(script_code, encoding="utf-8")

            load_out = subprocess.check_output(
                ["busctl", "--user", "call", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "loadScript", "s", str(script_path)],
                stderr=subprocess.DEVNULL, timeout=0.5
            ).decode("utf-8", errors="ignore").strip()

            if load_out:
                script_id = load_out.split()[-1]
                subprocess.check_output(
                    ["busctl", "--user", "call", "org.kde.KWin", f"/Scripting/Script{script_id}", "org.kde.kwin.Script", "run"],
                    stderr=subprocess.DEVNULL, timeout=0.5
                )
        except Exception:
            pass

    def update_telemetry(self, sensors: VehicleSensors, extra_data: Optional[Dict[str, Any]] = None) -> None:
        """Receives real-time telemetry data and triggers canvas repaint."""
        self._sensors = sensors
        speed_kmh = sensors.vehicle_speed * 3.6
        throttle_pct = sensors.unfiltered_throttle * 100.0
        brake_pct = sensors.unfiltered_brake * 100.0

        try:
            from src.telemetry.overlay_anomaly_logger import OverlayAnomalyLogger
            OverlayAnomalyLogger.get_instance().check_telemetry_anomaly(
                speed_kmh=speed_kmh,
                throttle_pct=throttle_pct,
                brake_pct=brake_pct,
                gear=sensors.gear,
                in_realtime=sensors.in_realtime,
                source="QtOverlayUpdate",
            )
        except Exception:
            pass

        if extra_data:
            self._extra_data = dict(extra_data)
        else:
            self._extra_data = {
                "speed": speed_kmh,
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
        self.update()

    def paintEvent(self, event) -> None:
        """120 FPS vector rendering loop for all HUD widgets (Head-Up Display)."""
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

            sw = float(self.width())
            sh = float(self.height())

            # Exact HUD dimensions (800x600 base proportional to screen)
            hud_w = max(300.0, sw / 3.0)
            hud_h = max(240.0, sh / 2.0)

            # Positioned at 2nd horizontal third (center) and 2nd vertical half (cockpit head-up display)
            hud_x = (sw - hud_w) / 2.0
            hud_y = sh / 2.0

            painter.save()
            painter.translate(hud_x, hud_y)

            # Modular sequential rendering of each widget
            for widget in self._widgets:
                widget.paint(painter, hud_w, hud_h, self._sensors, self._extra_data)

            painter.restore()
        finally:
            painter.end()
