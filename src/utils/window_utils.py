"""
SimPad — Utility functions for system window state management and screen dimensions.
Provides facade methods delegating to WindowManagerFactory (Abstract Factory Pattern).
"""

from pathlib import Path
from src.utils.glfw_manager import GLFWWindowManager
from src.utils.window import WindowManagerFactory, BaseWindowManager

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def get_window_manager() -> BaseWindowManager:
    """Returns the window manager instance appropriate for the host OS."""
    return WindowManagerFactory.get_manager()


def get_foreground_window_title() -> str:
    """Returns the title of the currently active foreground window on Windows/Linux."""
    return WindowManagerFactory.get_manager().get_foreground_window_title()


def get_foreground_process_name() -> str:
    """Returns the executable filename of the currently active foreground process on Windows/Linux."""
    return WindowManagerFactory.get_manager().get_foreground_process_name()


def is_lmu_running() -> bool:
    """Returns True if Le Mans Ultimate process is running on the system."""
    return WindowManagerFactory.get_manager().is_lmu_running()


def is_lmu_foreground() -> bool:
    """Returns True if Le Mans Ultimate game executable is the active window in the foreground."""
    return WindowManagerFactory.get_manager().is_lmu_foreground()


def get_lmu_window_status() -> str:
    """Returns 'foreground', 'background', or 'not_running'."""
    return WindowManagerFactory.get_manager().get_lmu_window_status()


def make_transparent_overlay(window_title: str) -> bool:
    """Enables transparent background overlay for the specified window."""
    return WindowManagerFactory.get_manager().make_transparent_overlay(window_title)


def force_viewport_fullscreen_overlay(window_title: str) -> bool:
    """Forces the DPG viewport window to full physical screen resolution."""
    return WindowManagerFactory.get_manager().force_viewport_fullscreen_overlay(window_title)


def restore_viewport_windowed(window_title: str) -> bool:
    """Restores the DPG viewport to windowed desktop console mode."""
    return WindowManagerFactory.get_manager().restore_viewport_windowed(window_title)


def get_screen_dimensions() -> tuple[int, int]:
    """Returns primary monitor resolution (width, height) using GLFW."""
    return GLFWWindowManager.get_screen_dimensions()


def get_3x3_grid_rect(col: int = 1, row: int = 0) -> tuple[int, int, int, int]:
    """
    Calculates (x, y, width, height) for a 3x3 physical screen grid cell.
    Always uses the primary monitor's physical resolution so width is exactly 1/3 of the screen.
    col: 0 (left), 1 (middle), 2 (right)
    row: 0 (top), 1 (middle), 2 (bottom)
    """
    sw, sh = get_screen_dimensions()
    w = max(300, sw // 3)
    h = max(180, sh // 3)
    x = (sw - w) // 2 if col == 1 else col * w
    y = row * h
    return (int(x), int(y), int(w), int(h))


def get_hud_rect(col_third: int = 1, row_half: int = 1) -> tuple[int, int, int, int]:
    """Calculates HUD rect bounds: 2nd horizontal third (col_third=1) and 2nd vertical half (row_half=1)."""
    sw, sh = get_screen_dimensions()
    w = max(300, sw // 3)
    h = max(240, sh // 2)
    x = (sw - w) // 2 if col_third == 1 else col_third * w
    y = row_half * (sh // 2)
    return (int(x), int(y), int(w), int(h))
