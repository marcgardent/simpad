"""Official SimPulse Center Cockpit HUD Plugin Package."""

from simpulse.builtin_plugins.official_cockpit_hud.config import OfficialCockpitHudConfig
from simpulse.builtin_plugins.official_cockpit_hud.preview_canvas import OfficialHudPreviewCanvas
from simpulse.builtin_plugins.official_cockpit_hud.tab_widget import OfficialCockpitHudTabWidget
from simpulse.builtin_plugins.official_cockpit_hud.plugin import OfficialCockpitHudPlugin

__all__ = [
    "OfficialCockpitHudPlugin",
    "OfficialCockpitHudConfig",
    "OfficialCockpitHudTabWidget",
    "OfficialHudPreviewCanvas",
]
