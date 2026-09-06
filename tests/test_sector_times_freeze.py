"""
Regression tests for DeltaEngine per-sector HUD display freezing (Phase C1).

Goal guarded by these tests:
  * isiMotor scoring drives the sector boxes through DeltaEngine._last_sectorN_time /
    _last_sectorN_status, consumed later by ReferenceLapManager._build_delta_packet and
    painted by the Cockpit HUD sector widgets.
  * Before Phase C1 these six fields were never assigned after __init__, so completed
    intermediate sectors always displayed '--'. This locks the fix: each box displays a
    stable time (current lap once the split is crossed, else last completed lap) and does
    not flicker back to '--' between packets or right after crossing the finish line.
"""
import unittest
import tempfile
import shutil
from pathlib import Path

import simpulse.core.telemetry.delta_engine as delta_engine_module
from simpulse.core.telemetry.delta_engine import DeltaEngine


def _mk_scoring(laps=1, sec=1, cur_s1=0.0, cur_s2=0.0, last_s1=30.0, last_s2=75.0,
                last_lap=100.0, best_s1=19.0, best_s2=37.5, best_lap=55.0):
    """Builds an rF2-style dict scoring packet (same shape DeltaEngine accepts today)."""
    return {
        "mTrackName": "TestTrack",
        "mLapDist": 3000.0,
        "mVehicles": [
            {
                "mIsPlayer": True,
                "mVehicleName": "TestCar",
                "mVehicleClass": "GT3",
                "mTotalLaps": laps,
                "mTimeIntoLap": 1.0,
                "mLapDist": 50.0,
                "mSector": sec,
                "mCountLapFlag": 2,
                "mLastLapTime": last_lap,
                "mCurSector1": cur_s1,
                "mCurSector2": cur_s2,
                "mLastSector1": last_s1,
                "mLastSector2": last_s2,
                "mBestSector1": best_s1,
                "mBestSector2": best_s2,
                "mBestLapTime": best_lap,
            }
        ],
    }


class TestSectorTimeFreeze(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_ref_dir = delta_engine_module._REF_LAPS_DIR
        delta_engine_module._REF_LAPS_DIR = Path(self.temp_dir)
        self.engine = DeltaEngine()

    def tearDown(self):
        delta_engine_module._REF_LAPS_DIR = self.original_ref_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_boxes_never_empty_before_first_split_of_lap(self):
        """At lap start (no cur split yet) every box displays the previous lap splits."""
        # Track session init + a fresh lap where the S1 loop is not crossed yet.
        self.engine.update_scoring(_mk_scoring(sec=1, cur_s1=0.0, last_s1=30.0, last_s2=75.0, last_lap=100.0))
        self.assertEqual(self.engine._last_sector1_time, "00:30.000")
        # individual S2 = last_s2 - last_s1 (75 - 30)
        self.assertEqual(self.engine._last_sector2_time, "00:45.000")
        # remainder of last lap = 100 - 75
        self.assertEqual(self.engine._last_sector3_time, "00:25.000")

    def test_sector1_updates_on_crossing_and_then_freezes(self):
        """S1 box shows the current-lap split once crossed and stays frozen afterwards."""
        self.engine.update_scoring(_mk_scoring(sec=1, cur_s1=0.0))
        self.engine.update_scoring(_mk_scoring(sec=2, cur_s1=10.5, cur_s2=0.0))
        self.assertEqual(self.engine._last_sector1_time, "00:10.500")
        # Progress in sector 2 without another S1 crossing must not change the S1 box.
        self.engine.update_scoring(_mk_scoring(sec=2, cur_s1=10.5, cur_s2=25.0))
        self.assertEqual(self.engine._last_sector1_time, "00:10.500")

    def test_sector2_individual_display_switch(self):
        """S2 shows previous-lap individual until crossed, then current-lap individual."""
        self.engine.update_scoring(_mk_scoring(sec=1, cur_s1=0.0, last_s1=30.0, last_s2=75.0))
        # Not crossed S2 of the current lap -> previous lap individual S2
        self.assertEqual(self.engine._last_sector2_time, "00:45.000")
        # Cross S2 split (cur_s1..cur_s2) -> current lap individual S2 switches
        self.engine.update_scoring(_mk_scoring(sec=3, cur_s1=10.5, cur_s2=26.0, last_s1=30.0, last_s2=75.0))
        self.assertEqual(self.engine._last_sector2_time, "00:15.500")

    def test_sector3_time_of_previous_lap_stable(self):
        """S3 box equals the remainder of the last completed lap and is stable."""
        self.engine.update_scoring(_mk_scoring(sec=1, cur_s1=0.0, last_s1=30.0, last_s2=75.0, last_lap=100.0))
        self.assertEqual(self.engine._last_sector3_time, "00:25.000")
        self.engine.update_scoring(_mk_scoring(sec=3, cur_s1=10.5, cur_s2=26.0, last_s1=30.0, last_s2=75.0, last_lap=100.0))
        self.assertEqual(self.engine._last_sector3_time, "00:25.000")

    def test_no_regression_after_finish_line(self):
        """Crossing the finish line (new lap) must not reset the boxes to '--'."""
        self.engine.update_scoring(_mk_scoring(laps=2, sec=1, cur_s1=0.0, cur_s2=0.0,
                                               last_s1=20.0, last_s2=40.0, last_lap=65.0))
        self.assertNotEqual(self.engine._last_sector1_time, "--")
        self.assertNotEqual(self.engine._last_sector2_time, "--")
        self.assertNotEqual(self.engine._last_sector3_time, "--")
        self.assertNotIn(self.engine._last_sector1_time, ("--", "--:--.---"))
        self.assertNotIn(self.engine._last_sector3_time, ("--", "--:--.---"))

    def test_status_green_when_under_personal_best(self):
        """A current-lap split better than the personal best S1 is colored 'green'."""
        self.engine.update_scoring(_mk_scoring(sec=1, cur_s1=0.0))
        self.engine.update_scoring(_mk_scoring(sec=2, cur_s1=9.0, cur_s2=0.0, best_s1=19.0))
        self.assertEqual(self.engine._last_sector1_status, "green")
        self.assertEqual(self.engine._last_sector1_time, "00:09.000")


if __name__ == "__main__":
    unittest.main()
