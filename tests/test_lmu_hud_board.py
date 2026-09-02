"""
Unit tests for LmuHudBoard, modular HUD widgets, and screen geometry calculations.
"""

import unittest
import dearpygui.dearpygui as dpg
from src.utils.window_utils import get_hud_rect, get_screen_dimensions
from src.gui.dashboards.lmu_hud_board import LmuHudBoard
from src.gui.dashboards.manager import DashboardManager
from src.gui.dashboards.widgets import (
    AbsGaugeWidget,
    BrakeGaugeWidget,
    ThrottleGaugeWidget,
    TcGaugeWidget,
    TiresGaugeWidget,
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
        """Verify instantiation of all 11 modular HUD widget classes."""
        widgets = [
            AbsGaugeWidget(),
            BrakeGaugeWidget(),
            TiresGaugeWidget(),
            ThrottleGaugeWidget(),
            TcGaugeWidget(),
            GearSpeedWidget(),
            RevIndicatorWidget(),
            AeroBarWidget(),
            DeltaTimerWidget(),
            EnergyLapsWidget(),
            SectorTimesWidget(),
        ]
        self.assertEqual(len(widgets), 11)

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



    def test_hud_gauges_abs_and_tc_binding(self):
        """Verify that ECU ABS and TC activation are properly bound to HUD gauges."""
        board = LmuHudBoard()
        # 1. Car ECU ABS Active (unfiltered_brake=1.0, filtered_brake=0.5 -> ecu_abs_active=0.5)
        sensors_abs = VehicleSensors(
            in_realtime=True,
            vehicle_speed=30.0,
            unfiltered_brake=1.0,
            filtered_brake=0.5,
            front_left_lock=0.30,
        )
        ctx_abs = board._build_widget_context(sensors_abs)
        self.assertTrue(ctx_abs["overbrake"])
        self.assertFalse(ctx_abs["wheelspin"])
        self.assertEqual(ctx_abs["brake"], 100.0)
        self.assertAlmostEqual(ctx_abs["abs"], 50.0, places=1)
        self.assertEqual(ctx_abs["tc"], 0.0)

        # 2. Car ECU TC Active (ecu_tc_active_raw=True)
        sensors_tc = VehicleSensors(
            in_realtime=True,
            vehicle_speed=30.0,
            ecu_tc_active_raw=True,
            unfiltered_throttle=1.0,
            filtered_throttle=0.4,
            rear_left_spin=0.35,
        )
        ctx_tc = board._build_widget_context(sensors_tc)
        self.assertFalse(ctx_tc["overbrake"])
        self.assertTrue(ctx_tc["wheelspin"])
        self.assertEqual(ctx_tc["throttle"], 100.0)
        self.assertEqual(ctx_tc["tc"], 100.0)
        self.assertEqual(ctx_tc["abs"], 0.0)

        # 2b. Car without ABS / ABS=0 during heavy wheel lockup (front_left_lock=1.0, ecu_abs_active_raw=False)
        sensors_lock_no_abs = VehicleSensors(
            in_realtime=True,
            vehicle_speed=30.0,
            ecu_abs_active_raw=False,
            ecu_abs_level=0,
            unfiltered_brake=1.0,
            filtered_brake=1.0,
            front_left_lock=1.0,
        )
        ctx_lock_no_abs = board._build_widget_context(sensors_lock_no_abs)
        self.assertTrue(ctx_lock_no_abs["overbrake"])
        self.assertEqual(ctx_lock_no_abs["abs"], 0.0)  # ABS gauge must stay strictly 0!

        # 3. Normal driving without TC intervention (unfiltered_throttle=0.85, filtered_throttle=0.85)
        sensors_normal = VehicleSensors(
            in_realtime=True,
            vehicle_speed=30.0,
            unfiltered_throttle=0.85,
            filtered_throttle=0.85,
        )
        ctx_normal = board._build_widget_context(sensors_normal)
        self.assertFalse(ctx_normal["wheelspin"])
        self.assertEqual(ctx_normal["throttle"], 85.0)
        self.assertEqual(ctx_normal["tc"], 0.0)

        # 4. Zero throttle at standstill (unfiltered_throttle=0.0)
        sensors_idle = VehicleSensors(
            in_realtime=True,
            unfiltered_throttle=0.0,
            filtered_throttle=0.0,
        )
        ctx_idle = board._build_widget_context(sensors_idle)
        self.assertEqual(ctx_idle["throttle"], 0.0)
        self.assertFalse(ctx_idle["wheelspin"])

    def test_qt_overlay_gauges_instantiation(self):
        """Verify instantiation of Qt gauges including 4-Tire widget."""
        from src.gui.overlay.widgets import (
            QtAbsGaugeWidget,
            QtBrakeGaugeWidget,
            QtThrottleGaugeWidget,
            QtTcGaugeWidget,
            QtTiresGaugeWidget,
        )
        abs_g = QtAbsGaugeWidget()
        brake_g = QtBrakeGaugeWidget()
        thr_g = QtThrottleGaugeWidget()
        tc_g = QtTcGaugeWidget()
        tires_g = QtTiresGaugeWidget()

        self.assertEqual(abs_g.display_abs, 0.0)
        self.assertEqual(brake_g.display_brake, 0.0)
        self.assertEqual(thr_g.display_throttle, 0.0)
        self.assertEqual(tc_g.display_tc, 0.0)
        self.assertEqual(tires_g.disp_fl_lock, 0.0)

    def test_tires_gauge_physical_colors(self):
        """Verify tire colors: neutral dark, purple on lockup, cyan on slip with pastel to deep gradient."""
        from src.gui.dashboards.widgets.tires_gauge import get_tire_colors

        # 1. Neutral pneu
        fill, border, mode, intensity = get_tire_colors(lock_val=0.0, slip_val=0.0)
        self.assertEqual(mode, "NONE")
        self.assertEqual(intensity, 0.0)

        # 2. Lockup / Over-Braking -> Purple
        fill_l, border_l, mode_l, int_l = get_tire_colors(lock_val=0.20, slip_val=0.0)
        self.assertEqual(mode_l, "LOCK")
        self.assertAlmostEqual(int_l, 0.20, places=2)
        # Check purple characteristics (R high, B highest, G lower)
        self.assertGreater(fill_l[0], fill_l[1])
        self.assertGreater(fill_l[2], fill_l[1])

        # 3. Slip / Spin -> Cyan
        fill_s, border_s, mode_s, int_s = get_tire_colors(lock_val=0.0, slip_val=0.50)
        self.assertEqual(mode_s, "SLIP")
        self.assertAlmostEqual(int_s, 0.50, places=2)
        # Check cyan characteristics (G and B high, R lower)
        self.assertGreater(fill_s[1], fill_s[0])
        self.assertGreater(fill_s[2], fill_s[0])


if __name__ == "__main__":
    unittest.main()
