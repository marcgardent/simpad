"""SimPulse Utilities Package."""

from .audio import AudioAnnouncer
from .audio_baker import AudioBaker
from .glfw_manager import GLFWWindowManager
from .window import (
    BaseWindowManager,
    WindowsWindowManager,
    LinuxWindowManager,
    WindowManagerFactory,
)
from .window_utils import (
    get_window_manager,
    get_foreground_window_title,
    get_foreground_process_name,
    is_lmu_running,
    is_lmu_foreground,
    get_lmu_window_status,
    make_transparent_overlay,
    force_viewport_fullscreen_overlay,
    restore_viewport_windowed,
    get_screen_dimensions,
    get_3x3_grid_rect,
    get_hud_rect,
)

__all__ = [
    "AudioAnnouncer",
    "AudioBaker",
    "GLFWWindowManager",
    "BaseWindowManager",
    "WindowsWindowManager",
    "LinuxWindowManager",
    "WindowManagerFactory",
    "get_window_manager",
    "get_foreground_window_title",
    "get_foreground_process_name",
    "is_lmu_running",
    "is_lmu_foreground",
    "get_lmu_window_status",
    "make_transparent_overlay",
    "force_viewport_fullscreen_overlay",
    "restore_viewport_windowed",
    "get_screen_dimensions",
    "get_3x3_grid_rect",
    "get_hud_rect",
]
