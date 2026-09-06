"""
Regression tests: the per-sector HUD view must stay stable frame-to-frame.

Background (seen in field):
  * hud_overlay_glitch.log catches one-frame sector S1..S3 "glitch jumps" that the
    Official Cockpit HUD would repaint as a transiently-current (white-bordered)
    box whenever a scoring sample reports a backward / skipped sector id.
  * Source of truth for the current sector is DeltaEngine._last_current_sector,
    which is written by both CompactScoring (10 Hz) and FullScoringSession (5 Hz),
    plus isiMotor's `sector == 0` inter-loop code used for the whole S3 phase.

What these tests lock:
  * Current sector advances strictly one forward step at a time (1 -> 2 -> 3 -> 1).
  * A single out-of-sequence sample (echo / stale FullScoring while the car is
    still in S1 or S2) is *ignored* instead of lighting a neighbouring box for one
    packet, and the engine keeps the last coherent sector.
  * The first observation still converges (live join in the middle of a lap) and
    real transitions observed in delta_debug.log remain recognised.
"""

import unittest
import tempfile
import shutil
from pathlib import Path

import simpulse.core.telemetry.delta_engine as delta_engine_module
from simpulse.core.telemetry.delta_engine import DeltaEngine


def _mk(laps=3, sec=1, dist=0.0, cur_s1=0.0, cur_s2=0.0, last_s1=30.0,
        last_s2=75.0, last_lap=100.0, flag=2, t_into=10.0, time_into=None):
    """Compact-style scoring packet dict (same shape DeltaEngine.update_scoring accepts)."""
    return {
        "mTrackName": "TestTrack",
        "mLapDist": 5000.0,
        "mCurrentET": 10.0 + t_into,
        "mScoringInfo": {
            "mTrackName": "TestTrack",
            "mLapDist": 5000.0,
            "mVehicles": [{
                "mIsPlayer": True,
                "mVehicleName": "TestCar",
                "mVehicleClass": "GT3",
                "mTotalLaps": laps,
                "mTimeIntoLap": time_into if time_into is not None else t_into,
                "mLapDist": dist,
                "mSector": sec,
                "mCountLapFlag": flag,
                "mLastLapTime": last_lap,
                "mCurSector1": cur_s1,
                "mCurSector2": cur_s2,
                "mLastSector1": last_s1,
                "mLastSector2": last_s2,
                "mBestSector1": 19.0,
                "mBestSector2": 37.5,
                "mBestLapTime": 55.0,
            }]
        },
    }


class TestSectorViewStability(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_ref_dir = delta_engine_module._REF_LAPS_DIR
        delta_engine_module._REF_LAPS_DIR = Path(self.temp_dir)
        self.engine = DeltaEngine()

    def tearDown(self):
        delta_engine_module._REF_LAPS_DIR = self.original_ref_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_forward_steps_still_cross(self):
        """Real lap progress 1->2->3 (via the S3 marker 0) still advances the view."""
        self.engine.update_scoring(_mk(laps=2, sec=1, dist=200.0, t_into=3.0))
        self.assertEqual(self.engine.current_sector, 1)

        self.engine.update_scoring(_mk(laps=2, sec=2, dist=1800.0, cur_s1=30.0, t_into=40.0))
        self.assertEqual(self.engine.current_sector, 2)

        # isiMotor marks the whole S3 phase with sector == 0 (see delta_debug.log).
        self.engine.update_scoring(_mk(laps=2, sec=0, dist=3200.0, cur_s1=30.0, cur_s2=55.0, t_into=65.0))
        self.assertEqual(self.engine.current_sector, 3)

    def test_stray_s3_sample_while_in_s1_is_ignored(self):
        """A packet reporting S3 while the car is still in S1 must NOT blink S3."""
        self.engine.update_scoring(_mk(laps=2, sec=1, dist=300.0, t_into=5.0))
        self.engine.update_scoring(_mk(laps=2, sec=1, dist=400.0, t_into=6.0))
        self.assertEqual(self.engine.current_sector, 1)

        # Same glitch shape as hud_overlay_glitch.log: "S1 -> S3" jump.
        self.engine.update_scoring(_mk(laps=2, sec=3, dist=450.0, t_into=7.0))
        self.assertEqual(self.engine.current_sector, 1)

        # Next coherent sample keeps S1 (was a one-frame echo, not a lap reset).
        self.engine.update_scoring(_mk(laps=2, sec=1, dist=500.0, t_into=8.0))
        self.assertEqual(self.engine.current_sector, 1)

        # Real S2 crossing remains recognised afterwards.
        self.engine.update_scoring(_mk(laps=2, sec=2, dist=2000.0, cur_s1=28.0, t_into=38.0))
        self.assertEqual(self.engine.current_sector, 2)

    def test_backward_sample_in_s2_is_ignored(self):
        """A backward S2->S1 sample (stale packet) must not move back to S1."""
        self.engine.update_scoring(_mk(laps=2, sec=1, dist=300.0, t_into=5.0))
        self.engine.update_scoring(_mk(laps=2, sec=2, dist=2600.0, cur_s1=29.0, t_into=45.0))
        self.assertEqual(self.engine.current_sector, 2)

        # Logged glitch: "S2 -> S1".
        self.engine.update_scoring(_mk(laps=2, sec=1, dist=2700.0, cur_s1=29.0, t_into=46.0))
        self.assertEqual(self.engine.current_sector, 2)

    def test_forward_step_without_prior_confirmed_s2_is_latched(self):
        """A single forward S1->S2 sample is a legitimate split crossing (latched)."""
        self.engine.update_scoring(_mk(laps=2, sec=1, dist=400.0, t_into=6.0))
        self.engine.update_scoring(_mk(laps=2, sec=2, dist=2000.0, cur_s1=29.0, t_into=38.0))
        self.assertEqual(self.engine.current_sector, 2)
        self.assertTrue(self.engine._s1_captured)
        # Locking: after capture, a repeat / stale S1 sample must not regress the view.
        self.engine.update_scoring(_mk(laps=2, sec=1, dist=2100.0, cur_s1=29.0, t_into=39.0))
        self.assertEqual(self.engine.current_sector, 2)

    def test_first_observation_converges_when_joining_live(self):
        """Joining a session mid lap still snaps to the reported sector once."""
        self.engine.update_scoring(_mk(laps=6, sec=3, dist=4200.0, cur_s1=30.0, cur_s2=70.0, t_into=90.0))
        self.assertEqual(self.engine.current_sector, 3)

        # While in S3, a de-phased FullScoring sample lagging one sector behind (S2)
        # must not regress the HUD backwards.
        self.engine.update_scoring(_mk(laps=6, sec=2, dist=4250.0, cur_s1=30.0, cur_s2=70.0, t_into=90.8))
        self.assertEqual(self.engine.current_sector, 3)
        # nor the forward 3->1 wrap before the next lap was actually recorded:
        self.engine.update_scoring(_mk(laps=6, sec=1, dist=4300.0, cur_s1=30.0, cur_s2=70.0, t_into=91.4))
        self.assertEqual(self.engine.current_sector, 3)
        # whereas a real lap completion (total_laps rolled over) stays coherent :
        self.engine.update_scoring(_mk(laps=7, sec=1, dist=20.0, cur_s1=0.0, cur_s2=0.0, t_into=1.0))
        self.assertEqual(self.engine.current_sector, 1)


if __name__ == "__main__":
    unittest.main()
