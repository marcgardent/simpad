"""
Unit tests for WindowManagerFactory, BaseWindowManager, LinuxWindowManager, and WindowsWindowManager.
"""

import sys
import unittest
from simpad_qt.core.utils.window import (
    BaseWindowManager,
    WindowsWindowManager,
    LinuxWindowManager,
    WindowManagerFactory,
)


class TestWindowManagerFactory(unittest.TestCase):

    def test_factory_creation(self):
        """Verify that WindowManagerFactory returns appropriate manager instance for host OS."""
        manager = WindowManagerFactory.get_manager()
        self.assertIsNotNone(manager)
        self.assertIsInstance(manager, BaseWindowManager)

        if sys.platform == "win32":
            self.assertIsInstance(manager, WindowsWindowManager)
        elif sys.platform.startswith("linux"):
            self.assertIsInstance(manager, LinuxWindowManager)

    def test_window_manager_methods_safety(self):
        """Verify that window manager methods execute safely without throwing unhandled exceptions."""
        manager = WindowManagerFactory.get_manager()
        title = manager.get_foreground_window_title()
        self.assertIsInstance(title, str)

        proc = manager.get_foreground_process_name()
        self.assertIsInstance(proc, str)

        is_fg = manager.is_lmu_foreground()
        self.assertIsInstance(is_fg, bool)

        is_run = manager.is_lmu_running()
        self.assertIsInstance(is_run, bool)

        status = manager.get_lmu_window_status()
        self.assertIn(status, ("foreground", "background", "not_running"))

    def test_linux_window_manager_instance(self):
        """Verify LinuxWindowManager behavior and methods."""
        linux_mgr = LinuxWindowManager()
        self.assertIsInstance(linux_mgr.get_foreground_window_title(), str)
        self.assertIsInstance(linux_mgr.get_foreground_process_name(), str)
        self.assertIsInstance(linux_mgr.is_lmu_running(), bool)
        self.assertIsInstance(linux_mgr.is_lmu_foreground(), bool)
        self.assertIn(linux_mgr.get_lmu_window_status(), ("foreground", "background", "not_running"))

    def test_windows_window_manager_instance(self):
        """Verify WindowsWindowManager behavior and methods."""
        win_mgr = WindowsWindowManager()
        self.assertIsInstance(win_mgr.get_foreground_window_title(), str)
        self.assertIsInstance(win_mgr.get_foreground_process_name(), str)
        self.assertIsInstance(win_mgr.is_lmu_running(), bool)
        self.assertIsInstance(win_mgr.is_lmu_foreground(), bool)
        self.assertIn(win_mgr.get_lmu_window_status(), ("foreground", "background", "not_running"))


if __name__ == "__main__":
    unittest.main()
