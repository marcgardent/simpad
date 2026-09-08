"""
Unit tests for Qt HUD Overlay, modular Qt HUD widgets, and screen geometry calculations.
"""

import unittest
from simpulse.core.utils.window_utils import get_hud_rect, get_screen_dimensions
from simpulse.builtin_plugins.official_cockpit_hud.widgets import (
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
from simpulse.builtin_plugins.official_cockpit_hud.widgets.tires_gauge import get_qt_tire_colors
from simpulse.core.telemetry.sensors import VehicleSensors
from simpulse_sdk.models import WheelSet, TireCorner, VehicleECU, AntiLockECU, TractionControlECU


class TestQtHudOverlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

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


    def test_format_time_sec(self):
        """format_sector_time is the canonical MM:ss.mmm formatter (LMUParser's
        former format_time_sec was a thin delegating wrapper around it — LMUParser
        is gone, callers use simpulse_sdk.format_sector_time directly now)."""
        from simpulse_sdk import format_sector_time as formatter
        # canonical: minutes zero-padded, same style as engine/packets
        self.assertEqual(formatter(32.41, missing="--"), "00:32.410")
        self.assertEqual(formatter(92.41, missing="--"), "01:32.410")
        self.assertEqual(formatter(125.008, missing="--"), "02:05.008")
        self.assertEqual(formatter(0.0, missing="--"), "--")
        self.assertEqual(formatter(-1.0, missing="--"), "--")

    def test_unified_formatters_agree(self):
        """Engine and SDK share one clock format for the same value."""
        from simpulse_sdk import format_lap_time as sdk_lap, format_sector_time
        from simpulse.core.telemetry.delta_engine import format_lap_time as engine_lap, sector_time_display_str as engine_sect
        self.assertEqual(engine_lap(30.0), sdk_lap(30.0))
        self.assertEqual(format_sector_time(30.0, missing="--"), engine_sect(30.0))
        self.assertEqual(sdk_lap(30.0), engine_sect(30.0))
        self.assertEqual(sdk_lap(92.4), engine_lap(92.4))
        self.assertEqual(format_sector_time(92.4, missing="--"), sdk_lap(92.4))

    def test_hud_gauges_abs_and_tc_binding(self):
        """Verify that ECU ABS and TC activation are properly bound to sensors."""
        # 1. Car ECU ABS Active (unfiltered_brake=1.0, filtered_brake=0.5 -> ecu_abs_active=0.5)
        sensors_abs = VehicleSensors(
            in_realtime=True,
            vehicle_speed=30.0,
            unfiltered_brake=1.0,
            filtered_brake=0.5,
            wheels=WheelSet(front_left=TireCorner(lock=0.30)),
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
            ecu=VehicleECU(tc=TractionControlECU(active_raw=True)),
            unfiltered_throttle=1.0,
            filtered_throttle=0.4,
            wheels=WheelSet(rear_left=TireCorner(spin=0.35)),
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
            ecu=VehicleECU(abs=AntiLockECU(active_raw=False, level=0)),
            unfiltered_brake=1.0,
            filtered_brake=1.0,
            wheels=WheelSet(front_left=TireCorner(lock=1.0)),
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

    def test_format_lap_time_mm_ss_mmm(self):
        """Verify format_lap_time formats lap time strictly as MM:ss.mmm."""
        from simpulse.core.telemetry.delta_engine import format_lap_time
        self.assertEqual(format_lap_time(92.45), "01:32.450")
        self.assertEqual(format_lap_time(125.008), "02:05.008")
        self.assertEqual(format_lap_time(58.123), "00:58.123")
        self.assertEqual(format_lap_time(0.0), "--:--.---")
        self.assertEqual(format_lap_time(-1.0), "--:--.---")

    def test_delta_timer_widget_rendering(self):
        """Verify QtDeltaTimerWidget handles both live delta and frozen lap time modes."""
        from PySide6.QtGui import QImage, QPainter
        widget = QtDeltaTimerWidget()

        img = QImage(800, 600, QImage.Format.Format_ARGB32)
        painter = QPainter(img)

        from simpulse.builtin_plugins.official_cockpit_hud.widgets import CockpitWidgetContext
        # 1. Live delta mode
        sensors_live = VehicleSensors(
            delta_time=-0.150,
            has_delta_reference=True,
            lap_flag=2,
            is_lap_freeze_active=False,
        )
        widget.paint(painter, 800.0, 600.0, CockpitWidgetContext(sensors=sensors_live))

        # 2. Frozen lap time mode (Finish line crossing: 01:32.450 Purple)
        sensors_frozen = VehicleSensors(
            last_lap_time=92.45,
            last_lap_time_str="01:32.450",
            _last_lap_status="purple",
            is_lap_freeze_active=True,
            lap_flag=2,
        )
        widget.paint(painter, 800.0, 600.0, CockpitWidgetContext(sensors=sensors_frozen))
        painter.end()


if __name__ == "__main__":
    unittest.main()

