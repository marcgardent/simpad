"""
Preview Canvas Widget for Official Cockpit HUD.
Renders an interactive live vector preview inside the Qt Studio Settings Tab.
"""

from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter, QPen, QBrush, QColor
from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from simpulse.builtin_plugins.official_cockpit_hud.plugin import OfficialCockpitHudPlugin


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

            # Dark preview viewport backdrop
            bg_rect = QRectF(0, 0, w, h)
            painter.setPen(QPen(QColor(15, 23, 42, 100), 1.0))
            painter.setBrush(QBrush(QColor(6, 9, 15, 255)))
            painter.drawRoundedRect(bg_rect, 6.0, 6.0)

            # Paint HUD widgets inside local coordinate bounds
            self.plugin.paint_hud(painter, w, h, self.plugin.latest_sensors)

        finally:
            painter.end()
