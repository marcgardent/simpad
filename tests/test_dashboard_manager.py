"""
Unit tests for DashboardManager, MonitoringBoard, LmuHudBoard, and grid geometry calculation.
"""

import unittest
import dearpygui.dearpygui as dpg
from src.utils.window_utils import get_3x3_grid_rect, get_screen_dimensions
from src.gui.dashboards.manager import DashboardManager
from src.gui.dashboards.monitoring_board import MonitoringBoard
from src.telemetry.sensors import VehicleSensors


class TestDashboardManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            dpg.create_context()
        except Exception:
            pass

    @classmethod
    def tearDownClass(cls):
        try:
            dpg.destroy_context()
        except Exception:
            pass

    def test_3x3_grid_rect_calculation(self):
        """Verify 3x3 grid geometry calculations."""
        sw, sh = get_screen_dimensions()
        x, y, w, h = get_3x3_grid_rect(col=1, row=0)  # Top-Middle

        self.assertGreaterEqual(w, 300)
        self.assertGreaterEqual(h, 180)
        self.assertEqual(y, 0)

    def test_dashboard_manager_lifecycle(self):
        """Verify DashboardManager registration, lookup, and lifecycle calls."""
        mgr = DashboardManager()

        # Verify default registration of monitoringBoard and lmuHudBoard
        self.assertIn("monitoringBoard", mgr.dashboard_names)
        self.assertIn("lmuHudBoard", mgr.dashboard_names)

        # Verify default activation states: lmuHudBoard = True, monitoringBoard = False
        self.assertTrue(mgr.is_dashboard_enabled("lmuHudBoard"))
        self.assertFalse(mgr.is_dashboard_enabled("monitoringBoard"))

        board_mon = mgr.get_dashboard("monitoringBoard")
        self.assertIsNotNone(board_mon)
        self.assertIsInstance(board_mon, MonitoringBoard)

        # Verify _qt_overlay is instantiated
        self.assertIsNotNone(mgr._qt_overlay)

        # Test update_telemetry without errors
        sensors = VehicleSensors(front_left_lock=0.2, rear_left_spin=0.1)
        mgr.update_telemetry(sensors)

    def test_dashboard_manager_display_modes(self):
        """Verify DashboardManager display mode switching."""
        mgr = DashboardManager()
        self.assertEqual(mgr.display_mode, "desktop")

        mgr.set_display_mode("ingame")
        self.assertEqual(mgr.display_mode, "ingame")

        mgr.set_display_mode("pause")
        self.assertEqual(mgr.display_mode, "pause")

        mgr.set_display_mode("desktop")
        self.assertEqual(mgr.display_mode, "desktop")

    def test_dashboard_manager_auto_display_decision(self):
        """Verify shared display decision logic across all overlays."""
        mgr = DashboardManager()

        # Enable both for testing auto-display visibility
        mgr.set_dashboard_enabled("monitoringBoard", True)
        mgr.set_dashboard_enabled("lmuHudBoard", True)

        # LMU Not in foreground -> Desktop mode
        mode = mgr.update_auto_display_state(is_lmu_foreground=False, on_track=True)
        self.assertEqual(mode, "desktop")
        self.assertEqual(mgr.display_mode, "desktop")

        # LMU in foreground AND on track -> InGame mode (immediate transition)
        mode = mgr.update_auto_display_state(is_lmu_foreground=True, on_track=True)
        self.assertEqual(mode, "ingame")
        self.assertEqual(mgr.display_mode, "ingame")
        self.assertTrue(mgr.get_dashboard("monitoringBoard").is_visible)

        # Disable monitoringBoard checkbox -> should hide monitoringBoard
        mgr.set_dashboard_enabled("monitoringBoard", False)
        self.assertFalse(mgr.get_dashboard("monitoringBoard").is_visible)

        # LMU in foreground BUT in menus/pause -> Pause mode immediately (all overlays hidden)
        mode = mgr.update_auto_display_state(is_lmu_foreground=True, on_track=False)
        self.assertEqual(mode, "pause")
        self.assertEqual(mgr.display_mode, "pause")
        self.assertFalse(mgr.get_dashboard("monitoringBoard").is_visible)

    def test_gamepad_status_indicator_update(self):
        """Verify that _update_status_indicators correctly updates lbl_pad_status."""
        from src.gui.dpg_app import SimPadDPGApp
        from src.haptics.mock_controller import MockHapticController

        app = SimPadDPGApp()
        if not dpg.does_item_exist("lbl_pad_status"):
            with dpg.window():
                dpg.add_text("Disconnected", tag="lbl_pad_status")

        # Case 1: _haptics is None -> Disconnected
        app._haptics = None
        app._update_status_indicators()
        self.assertEqual(dpg.get_value("lbl_pad_status"), "Disconnected")

        # Case 2: _haptics is connected -> Connected (Gamepad Name)
        mock_pad = MockHapticController()
        app._haptics = mock_pad
        app._update_status_indicators()
        self.assertIn("Connected", dpg.get_value("lbl_pad_status"))
        self.assertIn(mock_pad.get_gamepad_name(), dpg.get_value("lbl_pad_status"))


if __name__ == "__main__":
    unittest.main()
