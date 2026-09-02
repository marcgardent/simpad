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
    QtEnergyLapsWidget,
)
from src.telemetry.sensors import VehicleSensors
from src.utils.window_utils import get_hud_rect, _PROJECT_ROOT


class LmuHudQtWindow(QWidget):
    """
    Fenêtre Overlay HUD PySide6 100% transparente et Always-On-Top.
    Orchestre les widgets de télémétrie LMU sans aucun fond noir.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SimPad LMU HUD Overlay (Qt6)")

        # 1. Chargement de la police de course Anta-Regular
        self.font_family = self._load_custom_font()

        # 2. Instanciation modulaire des 11 widgets HUD
        self._widgets = [
            QtAbsGaugeWidget(),
            QtBrakeGaugeWidget(),
            QtTiresGaugeWidget(),
            QtThrottleGaugeWidget(),
            QtTcGaugeWidget(),
            QtGearSpeedWidget(font_family=self.font_family),
            QtRevIndicatorWidget(),
            QtAeroBarWidget(),
            QtDeltaTimerWidget(font_family=self.font_family),
            QtEnergyLapsWidget(font_family=self.font_family),
            QtSectorTimesWidget(font_family=self.font_family),
        ]

        self._sensors = VehicleSensors()
        self._extra_data: Dict[str, Any] = {}

        # 3. Configuration des drapeaux de fenêtre (Transparent, AlwaysOnTop, ClickThrough)
        self._apply_window_flags()

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self.update_geometry()

        # Timer 120 FPS pour fluidité ultra-réactive et rafraîchissement continu
        self._timer = QTimer(self)
        self._timer.setInterval(8)
        self._timer.timeout.connect(self.update)
        self._timer.start()

    def _load_custom_font(self) -> str:
        """Charge Anta-Regular.ttf dans la base de polices Qt."""
        font_path = _PROJECT_ROOT / "assets" / "fonts" / "Anta-Regular.ttf"
        if font_path.exists():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            if font_id != -1:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    return families[0]
        return "Segoe UI"

    def _apply_window_flags(self) -> None:
        """Applique les drapeaux de fenêtre pour l'overlay transparent traversant."""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )

    def update_geometry(self) -> None:
        """Couvre l'ensemble de l'écran physique pour permettre le placement libre des widgets."""
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.geometry()
            self.setGeometry(0, 0, geo.width(), geo.height())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.update_geometry()
        QTimer.singleShot(100, self._enforce_kwin_keep_above)

    def _enforce_kwin_keep_above(self) -> None:
        """Envoie l'ordre DBus KWin pour forcer le maintien au premier plan absolu sous KDE Wayland."""
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
        """Reçoit les données de télémétrie temps réel et déclenche le rafraîchissement."""
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
                "expectedTime": sensors.delta_time_str,
                "delta": sensors.delta_time_str,
                "estimatedLapTime": sensors.estimated_lap_time_str,
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
        self.update()

    def paintEvent(self, event) -> None:
        """Cycle de rendu vectoriel 120 FPS de l'ensemble des 8 widgets HUD (Affichage Tête Haute)."""
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

            sw = float(self.width())
            sh = float(self.height())

            # Dimensions exactes HUD Tête Haute (Base 800x600 proportionnelle à l'écran)
            hud_w = max(300.0, sw / 3.0)
            hud_h = max(240.0, sh / 2.0)

            # Positionné au 2ème tiers horizontal (centré) et 2ème moitié verticale (tête haute cockpit)
            hud_x = (sw - hud_w) / 2.0
            hud_y = sh / 2.0

            painter.save()
            painter.translate(hud_x, hud_y)

            # Rendu séquentiel modulaire de chaque widget
            for widget in self._widgets:
                widget.paint(painter, hud_w, hud_h, self._sensors, self._extra_data)

            painter.restore()
        finally:
            painter.end()
