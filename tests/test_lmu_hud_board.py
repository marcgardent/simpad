"""
Unit tests for Qt HUD Overlay, modular Qt HUD widgets, and screen geometry calculations.
"""

import unittest
from src.utils.window_utils import get_hud_rect, get_screen_dimensions
from src.gui.dashboards.manager import DashboardManager
from src.gui.overlay.lmu_hud_window import LmuHudQtWindow
from src.gui.overlay.widgets import (
    QtAbsGaugeWidget,
    QtBrakeGaugeWidget,
    QtThrottleGaugeWidget,
    QtTcGaugeWidget,
    QtTiresGaugeWidget,
    QtGearSpeedWidget,
    QtRevIndicatorWidget,
    QtAeroBarWidget,
    QtDeltaTimerWidget,
    QtEnergyLapsWidget,
    QtSectorTimesWidget,
)
from src.gui.overlay.widgets.tires_gauge import get_qt_tire_colors
from src.telemetry.sensors import VehicleSensors


class TestQtHudOverlay(unittest.TestCase):
    def test_get_hud_rect_geometry(self):
        """Verify get_hud_rect positioning for 2nd horizontal third and 2nd vertical half."""
        sw, sh = get_screen_dimensions()
        x, y, w, h = get_hud_rect(col_third=1, row_half=1)

        self.assertGreaterEqual(w, 300)
        self.assertGreaterEqual(h, 240)
        self.assertEqual(x, (sw - w) // 2)
        self.assertEqual(y, sh // 2)

    def test_modular_qt_widgets_instantiation(self):
        """Verify instantiation of all 11 modular Qt HUD widget classes."""
        widgets = [
            QtAbsGaugeWidget(),
            QtBrakeGaugeWidget(),
            QtTiresGaugeWidget(),
            QtThrottleGaugeWidget(),
            QtTcGaugeWidget(),
            QtGearSpeedWidget(),
            QtRevIndicatorWidget(),
            QtAeroBarWidget(),
            QtDeltaTimerWidget(),
            QtEnergyLapsWidget(),
            QtSectorTimesWidget(),
        ]
        self.assertEqual(len(widgets), 11)

    def test_qt_overlay_lifecycle_and_telemetry(self):
        """Verify Qt overlay registration in DashboardManager and telemetry updates."""
        mgr = DashboardManager()

        self.assertIn("lmuHudBoard", mgr.dashboard_names)
        self.assertTrue(mgr.is_dashboard_enabled("lmuHudBoard"))
        self.assertIsNotNone(mgr._qt_overlay)
        self.assertIsInstance(mgr._qt_overlay, LmuHudQtWindow)

        sensors = VehicleSensors(
            vehicle_speed=55.0,  # ~198 km/h
            gear=3,
            front_left_lock=0.8,
            rear_left_spin=0.6,
        )

        mgr.update_telemetry(sensors)

    def test_format_time_sec(self):
        """Verify format_time_sec formats times as [MM:]ss.mmm."""
        from src.telemetry.lmu_parser import format_time_sec
        self.assertEqual(format_time_sec(32.41), "32.410")
        self.assertEqual(format_time_sec(92.41), "1:32.410")
        self.assertEqual(format_time_sec(125.008), "2:05.008")
        self.assertEqual(format_time_sec(0.0), "--")
        self.assertEqual(format_time_sec(-1.0), "--")

    def test_hud_gauges_abs_and_tc_binding(self):
        """Verify that ECU ABS and TC activation are properly bound to sensors."""
        # 1. Car ECU ABS Active (unfiltered_brake=1.0, filtered_brake=0.5 -> ecu_abs_active=0.5)
        sensors_abs = VehicleSensors(
            in_realtime=True,
            vehicle_speed=30.0,
            unfiltered_brake=1.0,
            filtered_brake=0.5,
            front_left_lock=0.30,
        )
        self.assertTrue(sensors_abs.lock_intensity > 0.05)
        self.assertFalse(sensors_abs.spin_intensity > 0.05)
        self.assertEqual(sensors_abs.unfiltered_brake * 100.0, 100.0)
        self.assertAlmostEqual(sensors_abs.ecu_abs_active * 100.0, 50.0, places=1)
        self.assertEqual(sensors_abs.ecu_tc_active * 100.0, 0.0)

        # 2. Car ECU TC Active (ecu_tc_active_raw=True)
        sensors_tc = VehicleSensors(
            in_realtime=True,
            vehicle_speed=30.0,
            ecu_tc_active_raw=True,
            unfiltered_throttle=1.0,
            filtered_throttle=0.4,
            rear_left_spin=0.35,
        )
        self.assertFalse(sensors_tc.lock_intensity > 0.05)
        self.assertTrue(sensors_tc.spin_intensity > 0.05)
        self.assertEqual(sensors_tc.unfiltered_throttle * 100.0, 100.0)
        self.assertEqual(sensors_tc.ecu_tc_active * 100.0, 100.0)
        self.assertEqual(sensors_abs.ecu_abs_active * 100.0, 50.0)

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
        self.assertTrue(sensors_lock_no_abs.lock_intensity > 0.05)
        self.assertEqual(sensors_lock_no_abs.ecu_abs_active * 100.0, 0.0)  # ABS gauge must stay strictly 0!

    def test_tires_gauge_physical_colors(self):
        """Verify tire colors: neutral dark, purple on lockup, cyan on slip with pastel to deep gradient."""
        # 1. Neutral pneu
        fill, border, mode, intensity = get_qt_tire_colors(lock_val=0.0, slip_val=0.0)
        self.assertEqual(mode, "NONE")
        self.assertEqual(intensity, 0.0)

        # 2. Lockup / Over-Braking -> Purple
        fill_l, border_l, mode_l, int_l = get_qt_tire_colors(lock_val=0.20, slip_val=0.0)
        self.assertEqual(mode_l, "LOCK")
        self.assertAlmostEqual(int_l, 0.20, places=2)
        # Check purple characteristics (R high, B highest, G lower)
        self.assertGreater(fill_l.red(), fill_l.green())
        self.assertGreater(fill_l.blue(), fill_l.green())

        # 3. Slip / Spin -> Cyan
        fill_s, border_s, mode_s, int_s = get_qt_tire_colors(lock_val=0.0, slip_val=0.50)
        self.assertEqual(mode_s, "SLIP")
        self.assertAlmostEqual(int_s, 0.50, places=2)
        # Check cyan characteristics (G and B high, R lower)
        self.assertGreater(fill_s.green(), fill_s.red())
        self.assertGreater(fill_s.blue(), fill_s.red())


if __name__ == "__main__":
    unittest.main()

