"""Official SimPad Center Cockpit HUD Plugin Package."""

from simpad_qt.builtin_plugins.official_cockpit_hud.config import OfficialCockpitHudConfig
from simpad_qt.builtin_plugins.official_cockpit_hud.preview_canvas import OfficialHudPreviewCanvas
from simpad_qt.builtin_plugins.official_cockpit_hud.tab_widget import OfficialCockpitHudTabWidget
from simpad_qt.builtin_plugins.official_cockpit_hud.plugin import OfficialCockpitHudPlugin

__all__ = [
    "OfficialCockpitHudPlugin",
    "OfficialCockpitHudConfig",
    "OfficialCockpitHudTabWidget",
    "OfficialHudPreviewCanvas",
]
