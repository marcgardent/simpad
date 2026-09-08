"""
Contract: QtSectorTimesWidget's per-box visibility (TIME_STATUS_SPEC.md's
3-state rule) and the Delta/Expected display-mode choice, which applies to
the sector boxes exactly like it does to QtDeltaTimerWidget.
"""
import unittest

from simpulse.builtin_plugins.official_cockpit_hud.widgets import QtSectorTimesWidget, CockpitWidgetContext
from simpulse.core.telemetry.delta_engine import DeltaEngine
from simpulse.core.telemetry.reference_profile import ReferenceLapProfile
from simpulse_sdk import (
    TimeLapViewModel,
    TimeSectorViewModel,
    TimeStatus,
    VehicleSensors,
    WallOfFameTimes,
)


class TestSectorTimesWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from simpulse.builtin_plugins.official_cockpit_hud.widgets import sector_paint_recorder
        self.captured = {}

        def fake_record(cur, boxes, mode, rgb):
            self.captured["boxes"] = boxes
            self.captured["mode"] = mode

        self._orig_record = sector_paint_recorder.record
        sector_paint_recorder.record = fake_record
        self.addCleanup(setattr, sector_paint_recorder, "record", self._orig_record)

    def _paint(self, sensors: VehicleSensors, **context_overrides) -> None:
        from PySide6.QtGui import QImage, QPainter
        widget = QtSectorTimesWidget()
        img = QImage(800, 600, QImage.Format.Format_ARGB32)
        painter = QPainter(img)
        ctx = CockpitWidgetContext(sensors=sensors, **context_overrides)
        widget.paint(painter, 800.0, 600.0, ctx)
        painter.end()

    def test_not_yet_reached_sector_is_empty(self):
        """In Sector 2: S1 shows its (this-lap) split, S3 must be blank — no
        previous-lap value carried over, no colour."""
        sensors = VehicleSensors(current_sector=2, is_lap_freeze_active=False)
        sensors._sector1_time = "00:31.250"
        sensors._sector3_time = "00:39.944"  # stale previous-lap value
        sensors._sector2_delta = -0.150

        self._paint(sensors)

        self.assertEqual(self.captured["mode"], ("frozen", "live", "empty"))
        self.assertEqual(self.captured["boxes"][2], "--")

    def test_freeze_window_shows_all_three_completed_splits(self):
        """Right after the line: every box shows the just-finished lap's
        split, even though the new lap's S1 is already 'current'."""
        sensors = VehicleSensors(current_sector=1, is_lap_freeze_active=True)
        sensors._sector1_time = "00:31.250"
        sensors._sector2_time = "00:42.100"
        sensors._sector3_time = "00:39.944"

        self._paint(sensors)

        self.assertEqual(self.captured["mode"], ("frozen", "frozen", "frozen"))
        self.assertEqual(self.captured["boxes"], ("00:31.250", "00:42.100", "00:39.944"))

    def test_expected_display_mode_shows_projected_split_time(self):
        """delta_display_mode='expected' applies to the live sector box too,
        not just the Delta Timer — projected split time, not the raw delta."""
        eng = DeltaEngine()
        eng._current_profile = ReferenceLapProfile(lap_time=100.0, sector_1_time=30.0, sector_2_time=60.0)
        eng._ref_t_grid = [float(i) for i in range(101)]
        eng._ref_num_points = 101
        eng._sector2_delta = -0.5  # projected S2 = 30.0 - 0.5 = 29.5

        sensors = VehicleSensors()
        sensors.current_sector = 2
        sensors._sector2_delta = -0.5
        sensors.time_status = eng.time_status

        # delta_smoothing_mode="direct": the widget now reads its live value
        # from sensors.time_status/.time_status_smoothed depending on this
        # mode (default "smoothed") — this test only populates the raw one.
        self._paint(sensors, delta_display_mode="expected", delta_smoothing_mode="direct")

        self.assertEqual(self.captured["mode"][1], "live")
        self.assertEqual(self.captured["boxes"][1], "00:29.500")

    def test_delta_display_mode_shows_raw_delta(self):
        """Default mode ('delta') keeps showing the live gap, unaffected."""
        sensors = VehicleSensors(current_sector=1)
        sensors._sector1_delta = -0.150
        sensors.time_status = TimeStatus(
            lap=TimeLapViewModel(),
            sectors=(
                TimeSectorViewModel(delta_time=-0.150, is_current=True),
                TimeSectorViewModel(),
                TimeSectorViewModel(),
            ),
            wall_of_fame=WallOfFameTimes(),
        )

        # See note above: delta_smoothing_mode="direct" because this test
        # only populates sensors.time_status (raw), not .time_status_smoothed.
        self._paint(sensors, delta_display_mode="delta", delta_smoothing_mode="direct")

        self.assertEqual(self.captured["mode"][0], "live")
        self.assertEqual(self.captured["boxes"][0], "-0.150")


if __name__ == "__main__":
    unittest.main()
