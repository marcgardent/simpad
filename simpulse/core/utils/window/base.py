"""
SimPulse Window Management — Base Abstract Window Manager.
Defines the interface for cross-platform window state, foreground process tracking, and overlay management.
"""

from abc import ABC, abstractmethod


class BaseWindowManager(ABC):
    """Abstract base class for window and process management according to the operating system."""

    def __init__(self):
        self._focus_listeners = []

    def add_focus_listener(self, callback) -> None:
        """Registers a reactive callback called immediately upon window focus change."""
        if callback not in self._focus_listeners:
            self._focus_listeners.append(callback)

    def remove_focus_listener(self, callback) -> None:
        """Detaches a reactive callback."""
        if callback in self._focus_listeners:
            self._focus_listeners.remove(callback)

    def _notify_focus_changed(self) -> None:
        """Triggers all registered focus listeners immediately."""
        for cb in list(self._focus_listeners):
            try:
                cb()
            except Exception:
                pass

    @abstractmethod
    def get_foreground_window_title(self) -> str:
        """Returns the title of the active foreground window."""
        return ""

    @abstractmethod
    def get_foreground_process_name(self) -> str:
        """Returns the executable name of the active foreground process."""
        return ""

    def is_lmu_running(self) -> bool:
        """Checks if the LMU game process is running on the system."""
        return False

    def is_lmu_foreground(self) -> bool:
        """
        Checks if the Le Mans Ultimate (LMU) game is currently the active foreground window.
        """
        proc_name = self.get_foreground_process_name().lower()
        if proc_name in ("lemansultimate.exe", "rfactor2.exe", "lemansultimate", "rfactor2"):
            return True

        title = self.get_foreground_window_title().lower().strip()
        if "le mans" in title or "lemans" in title or "rfactor" in title:
            return True

        # Transparent HUD overlay only (not the parent Studio console)
        if "hud overlay" in title:
            return True

        return False

    def get_lmu_window_status(self) -> str:
        """
        Returns the precise state of the LMU game:
        - 'foreground'  : Game is running and active in the foreground.
        - 'background'  : Game is running but in the background.
        - 'not_running' : Game is not running.
        """
        if self.is_lmu_foreground():
            return "foreground"
        if self.is_lmu_running():
            return "background"
        return "not_running"

    def make_transparent_overlay(self, window_title: str) -> bool:
        """Enables background transparency on the specified window (OS-specific)."""
        return False

    def force_viewport_fullscreen_overlay(self, window_title: str) -> bool:
        """Switches the window to a fullscreen transparent overlay with click-through."""
        try:
            import dearpygui.dearpygui as dpg
            dpg.configure_viewport(0, decorated=False, always_on_top=True)
            dpg.maximize_viewport()
            return True
        except Exception:
            return False

    def restore_viewport_windowed(self, window_title: str) -> bool:
        """Restores the window to decorated windowed console mode."""
        try:
            import dearpygui.dearpygui as dpg
            dpg.configure_viewport(0, decorated=True, always_on_top=False)
            dpg.maximize_viewport()
            return True
        except Exception:
            return False
