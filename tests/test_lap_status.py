"""
Unit Tests for TelemetryStateStore Hit Tracking, Clean/Dirty Lap Calculation,
and QtLapStatusWidget Rendering.
"""

import time
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPainter, QImage
from PySide6.QtCore import QRectF

from simpad_qt.core.telemetry.state_store import TelemetryStateStore
from simpad_qt.builtin_plugins.official_cockpit_hud.widgets.lap_status import QtLapStatusWidget
from simpad_qt.core.telemetry.sensors import VehicleSensors
from isimotor_rawudp_client import TelemInfo, CompactScoring


class TestHitAndCleanLap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.store = TelemetryStateStore()
        self.store.reset()

    def test_initial_state_clean_zero_hits(self):
        self.assertEqual(self.store.hit_count_current_lap, 0)
        self.assertTrue(self.store.is_clean_lap)
        self.assertEqual(self.store.clean_lap_status, "clean")
        self.assertFalse(self.store.is_dirty_lap)

    def test_impact_detection_increments_hit_counter_and_dirties_lap(self):
        now = time.time()
        self.store.update_lap_validity(2, timestamp=now)
        self.assertTrue(self.store.is_clean_lap)

        # Impact 1 at 10.5s
        t1 = TelemInfo(lap_number=1, last_impact_et=10.5)
        self.store.update_telemetry(t1, timestamp=now)
        self.assertEqual(self.store.hit_count_current_lap, 1)
        self.assertFalse(self.store.is_clean_lap)
        self.assertTrue(self.store.is_dirty_lap)
        self.assertEqual(self.store.clean_lap_status, "dirty")

        # Duplicate frame with same impact timestamp: no increment
        t2 = TelemInfo(lap_number=1, last_impact_et=10.5)
        self.store.update_telemetry(t2, timestamp=now + 0.01)
        self.assertEqual(self.store.hit_count_current_lap, 1)

        # Impact 2 at 15.8s
        t3 = TelemInfo(lap_number=1, last_impact_et=15.8)
        self.store.update_telemetry(t3, timestamp=now + 0.02)
        self.assertEqual(self.store.hit_count_current_lap, 2)
        self.assertFalse(self.store.is_clean_lap)

    def test_lap_change_resets_hit_counter_and_restores_clean_lap(self):
        now = time.time()
        self.store.update_lap_validity(2, timestamp=now)

        # Lap 1 with impact
        t1 = TelemInfo(lap_number=1, last_impact_et=10.5)
        self.store.update_telemetry(t1, timestamp=now)
        self.assertEqual(self.store.hit_count_current_lap, 1)
        self.assertFalse(self.store.is_clean_lap)

        # Lap 2 begins (lap_number changes from 1 to 2)
        t2 = TelemInfo(lap_number=2, last_impact_et=10.5)
        self.store.update_telemetry(t2, timestamp=now + 1.0)
        self.assertEqual(self.store.hit_count_current_lap, 0)
        self.assertTrue(self.store.is_clean_lap)
        self.assertEqual(self.store.clean_lap_status, "clean")

    def test_invalid_lap_is_dirty_even_with_zero_hits(self):
        now = time.time()
        # Lap flag 0 = time deleted
        self.store.update_lap_validity(0, timestamp=now)
        self.assertEqual(self.store.hit_count_current_lap, 0)
        self.assertFalse(self.store.is_clean_lap)
        self.assertTrue(self.store.is_dirty_lap)

        # Lap flag 2 = restored valid
        self.store.update_lap_validity(2, timestamp=now + 0.5)
        self.assertTrue(self.store.is_clean_lap)

    def test_lap_status_widget_paint_both_states(self):
        from simpad_qt.builtin_plugins.official_cockpit_hud.widgets import CockpitWidgetContext
        widget = QtLapStatusWidget()

        img = QImage(800, 600, QImage.Format.Format_ARGB32)
        img.fill(0)
        painter = QPainter(img)

        # Valid & Clean
        widget.paint(painter, 800, 600, CockpitWidgetContext(sensors=VehicleSensors(lap_flag=2), hit_count=0))

        # Invalid & Dirty
        widget.paint(painter, 800, 600, CockpitWidgetContext(sensors=VehicleSensors(lap_flag=0), hit_count=3))

        painter.end()

    def test_cockpit_hud_plugin_separate_switches(self):
        from simpad_qt.builtin_plugins.official_cockpit_hud.plugin import OfficialCockpitHudPlugin
        plugin = OfficialCockpitHudPlugin()
        sensors = VehicleSensors()

        img = QImage(640, 300, QImage.Format.Format_ARGB32)
        img.fill(0)
        painter = QPainter(img)

        # Both on
        plugin.config.show_aero = True
        plugin.config.show_lap_status = True
        plugin.paint_hud(painter, 640, 300, sensors)

        # Aero only
        plugin.config.show_aero = True
        plugin.config.show_lap_status = False
        plugin.paint_hud(painter, 640, 300, sensors)

        # Lap status only
        plugin.config.show_aero = False
        plugin.config.show_lap_status = True
        plugin.paint_hud(painter, 640, 300, sensors)

        # Both off
        plugin.config.show_aero = False
        plugin.config.show_lap_status = False
        plugin.paint_hud(painter, 640, 300, sensors)

        painter.end()


if __name__ == "__main__":
    unittest.main()
