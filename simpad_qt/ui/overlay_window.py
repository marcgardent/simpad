"""
SimPad Qt6 Transparent Always-On-Top HUD Overlay Compositor Window.
Renders all active IHudWidgetProvider plugins smoothly at high refresh rates (60/120 FPS).
Includes native platform enforcements (Linux KWin DBus keepAbove & Windows SetWindowPos HWND_TOPMOST),
click-through transparency, and dynamic multi-monitor screen geometry sync.
"""

from __future__ import annotations
import os
import sys
import logging
import subprocess
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QWidget, QApplication

from simpad_qt.plugins.manager import PluginManager
from simpad_qt.plugins.contracts import IHudWidgetProvider
from simpad_qt.ui.slot_compositor import HudSlotCompositor
from simpad_qt.core.telemetry import VehicleSensors

logger = logging.getLogger("simpad.overlay")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class SimPadHudOverlayWindow(QWidget):
    """
    Hardware-accelerated transparent HUD window for in-game telemetry overlays.
    Composes vector graphics from all active IHudWidgetProvider plugins into assigned screen slots.
    """

    def __init__(self, plugin_manager: PluginManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.plugin_manager = plugin_manager
        self._latest_sensors = VehicleSensors()
        self._debug_boxes = False
        self._custom_font_family = self._load_custom_font()

        self.setWindowTitle("SimPad Qt6 HUD Overlay")
        self._setup_window_flags()

        # Connect to screen resolution changes
        screen = QApplication.primaryScreen()
        if screen:
            screen.geometryChanged.connect(self.update_geometry_to_screen)

    def _load_custom_font(self) -> str:
        """Load Anta-Regular.ttf custom racing font from plugin fonts folder."""
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

    def _setup_window_flags(self) -> None:
        """Apply window flags for transparent, click-through always-on-top overlay."""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.update_geometry_to_screen()

    def update_geometry_to_screen(self) -> None:
        """Cover the entire primary screen without taskbars."""
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.geometry()
            self.setGeometry(0, 0, geo.width(), geo.height())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.update_geometry_to_screen()
        QTimer.singleShot(50, self._enforce_platform_always_on_top)

    def _enforce_platform_always_on_top(self) -> None:
        """
        Enforce absolute topmost layering over fullscreen games (Wine/Proton on Linux or DirectX on Windows).
        """
        if sys.platform.startswith("linux"):
            self._enforce_kwin_wayland_topmost()
        elif sys.platform == "win32":
            self._enforce_windows_topmost()

    def _enforce_kwin_wayland_topmost(self) -> None:
        """Send DBus script to KWin to force keepAbove and borderless rules on KDE Wayland."""
        try:
            script_dir = Path.home() / ".cache" / "simpad"
            script_dir.mkdir(parents=True, exist_ok=True)
            script_path = script_dir / "kwin_force_overlay.js"
            script_code = (
                'workspace.windowList().forEach(function(w) {'
                '  if (w.caption && w.caption.indexOf("SimPad Qt6 HUD Overlay") !== -1) {'
                '    w.keepAbove = true;'
                '    w.noBorder = true;'
                '    w.skipTaskbar = true;'
                '  }'
                '});'
            )
            script_path.write_text(script_code, encoding="utf-8")

            load_out = subprocess.check_output(
                ["busctl", "--user", "call", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "loadScript", "s", str(script_path)],
                stderr=subprocess.DEVNULL, timeout=0.3
            ).decode("utf-8", errors="ignore").strip()

            if load_out:
                script_id = load_out.split()[-1]
                subprocess.check_output(
                    ["busctl", "--user", "call", "org.kde.KWin", f"/Scripting/Script{script_id}", "org.kde.kwin.Script", "run"],
                    stderr=subprocess.DEVNULL, timeout=0.3
                )
        except Exception:
            pass

    def _enforce_windows_topmost(self) -> None:
        """Enforce HWND_TOPMOST and WS_EX_TRANSPARENT styles on Windows."""
        try:
            import ctypes
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_TOPMOST = 0x00000008
            WS_EX_NOACTIVATE = 0x08000000

            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_NOACTIVATE)

            HWND_TOPMOST = -1
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
        except Exception:
            pass

    def update_telemetry(self, sensors: VehicleSensors) -> None:
        """Update current sensor state and trigger immediate redraw."""
        self._latest_sensors = sensors
        if self.isVisible():
            self.update()

    def set_debug_boxes(self, enabled: bool) -> None:
        """Toggle visualization of slot bounding boxes."""
        self._debug_boxes = enabled
        self.update()

    def paintEvent(self, event) -> None:
        """Composite all active HUD widget providers."""
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

            sw = float(self.width())
            sh = float(self.height())

            providers = self.plugin_manager.get_hud_providers()
            for provider in providers:
                slot = provider.preferred_slot
                desired_size = provider.get_hud_size()
                layout_spec = HudSlotCompositor.calculate_slot_layout(slot, sw, sh, desired_size)
                slot_rect = layout_spec.allocated_rect

                # Optional debug box
                if self._debug_boxes:
                    painter.save()
                    painter.setPen(QColor(0, 210, 255, 120))
                    painter.setBrush(QColor(0, 210, 255, 20))
                    painter.drawRect(slot_rect)
                    painter.setPen(QColor(255, 255, 255, 180))
                    painter.setFont(QFont("sans-serif", 9))
                    painter.drawText(slot_rect.x() + 4, slot_rect.y() + 14, f"[{slot.value}]")
                    painter.restore()

                # Paint widget in its local coordinate system
                painter.save()
                try:
                    painter.translate(slot_rect.x(), slot_rect.y())
                    painter.setClipRect(QRectF(0, 0, slot_rect.width(), slot_rect.height()))
                    provider.paint_hud(
                        painter,
                        slot_rect.width(),
                        slot_rect.height(),
                        self._latest_sensors,
                    )
                except Exception as e:
                    pid = getattr(provider, "metadata", None)
                    pid_str = pid.id if pid else str(provider)
                    self.plugin_manager._handle_plugin_error(pid_str, "paint_hud", e)
                finally:
                    painter.restore()

        finally:
            painter.end()
