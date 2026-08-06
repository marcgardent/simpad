"""
Unit tests for LmuHudBoard, modular HUD widgets, and screen geometry calculations.
"""

import unittest
import dearpygui.dearpygui as dpg
from src.utils.window_utils import get_hud_rect, get_screen_dimensions
from src.gui.dashboards.lmu_hud_board import LmuHudBoard
from src.gui.dashboards.manager import DashboardManager
from src.gui.dashboards.widgets import (
    BrakeGaugeWidget,
    ThrottleGaugeWidget,
    GearSpeedWidget,
    RevIndicatorWidget,
    AeroBarWidget,
    DeltaTimerWidget,
    EnergyLapsWidget,
    SectorTimesWidget,
)
from src.telemetry.sensors import VehicleSensors


class TestLmuHudBoard(unittest.TestCase):
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

    def test_get_hud_rect_geometry(self):
        """Verify get_hud_rect positioning for 2nd horizontal third and 2nd vertical half."""
        sw, sh = get_screen_dimensions()
        x, y, w, h = get_hud_rect(col_third=1, row_half=1)

        self.assertGreaterEqual(w, 300)
        self.assertGreaterEqual(h, 240)
        self.assertEqual(x, (sw - w) // 2)
        self.assertEqual(y, sh // 2)



    def test_modular_widgets_instantiation(self):
        """Verify instantiation of all 8 modular HUD widget classes."""
        widgets = [
            BrakeGaugeWidget(),
            ThrottleGaugeWidget(),
            GearSpeedWidget(),
            RevIndicatorWidget(),
            AeroBarWidget(),
            DeltaTimerWidget(),
            EnergyLapsWidget(),
            SectorTimesWidget(),
        ]
        self.assertEqual(len(widgets), 8)

    def test_lmu_hud_board_registration_and_telemetry(self):
        """Verify LmuHudBoard registration in DashboardManager and telemetry updates."""
        mgr = DashboardManager()

        self.assertIn("lmuHudBoard", mgr.dashboard_names)
        board = mgr.get_dashboard("lmuHudBoard")
        self.assertIsNotNone(board)
        self.assertIsInstance(board, LmuHudBoard)

        sensors = VehicleSensors(
            vehicle_speed=55.0,  # ~198 km/h
            gear=3,
            front_left_lock=0.8,
            rear_left_spin=0.6,
        )

        # Build UI to test drawing widgets
        board.build_ui()
        board.show()
        board.update_telemetry(sensors)

    def test_format_time_sec(self):
        """Verify format_time_sec formats times as [MM:]ss.mmm."""
        from src.telemetry.lmu_parser import format_time_sec
        self.assertEqual(format_time_sec(32.41), "32.410")
        self.assertEqual(format_time_sec(92.41), "1:32.410")
        self.assertEqual(format_time_sec(125.008), "2:05.008")
        self.assertEqual(format_time_sec(0.0), "--")
        self.assertEqual(format_time_sec(-1.0), "--")



if __name__ == "__main__":
    unittest.main()
