import os
import shutil
import unittest
import tempfile
from pathlib import Path
import src.telemetry.delta_engine as delta_engine_module
from src.telemetry.delta_engine import DeltaEngine, _clean_name


class TestDeltaEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_ref_dir = delta_engine_module._REF_LAPS_DIR
        delta_engine_module._REF_LAPS_DIR = Path(self.temp_dir)
        self.engine = DeltaEngine()

    def tearDown(self):
        delta_engine_module._REF_LAPS_DIR = self.original_ref_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_clean_name(self):
        self.assertEqual(_clean_name("Circuit de Spa-Francorchamps"), "circuit_de_spa-francorchamps")
        self.assertEqual(_clean_name("Ferrari 499P / Le Mans"), "ferrari_499p___le_mans")
        self.assertEqual(_clean_name(""), "unknown")

    def test_initial_state_no_delta(self):
        """Without reference lap recorded/loaded, live_delta must be 0.0 and has_reference False."""
        self.assertFalse(self.engine.has_reference)
        self.assertEqual(self.engine.live_delta, 0.0)
        self.assertEqual(self.engine.sector1_delta, 0.0)

    def test_invalid_lap_rejection(self):
        """Verify that invalid laps (mCountLapFlag != 2) or pit laps are rejected."""
        scoring_js = {
            "mTrackName": "TestTrack",
            "mLapDist": 1000.0,
            "mVehicles": [
                {
                    "mIsPlayer": True,
                    "mVehicleName": "TestCar",
                    "mTotalLaps": 1,
                    "mTimeIntoLap": 10.0,
                    "mLapDist": 100.0,
                    "mSector": 1,
                    "mCountLapFlag": 1,  # Outlap / invalid flag
                    "mLastLapTime": 60.0,
                }
            ],
        }
        self.engine.update_scoring(scoring_js)
        # Advance lap with mCountLapFlag = 1 (Outlap)
        scoring_js["mVehicles"][0]["mTotalLaps"] = 2
        scoring_js["mVehicles"][0]["mTimeIntoLap"] = 2.0
        scoring_js["mVehicles"][0]["mLapDist"] = 20.0
        self.engine.update_scoring(scoring_js)

        # Should NOT have recorded a reference lap because lap_flag was 1
        self.assertFalse(self.engine.has_reference)

    def test_valid_lap_recording_and_delta_calc(self):
        """Simulate a valid clean lap and verify reference recording and delta calculation."""
        track_len = 1000.0
        lap_time = 50.0  # 50 seconds for 1000 meters -> 20 m/s

        # 1. Drive Lap 1 (Clean lap)
        scoring_js = {
            "mTrackName": "TestTrack",
            "mLapDist": track_len,
            "mVehicles": [
                {
                    "mIsPlayer": True,
                    "mVehicleName": "TestCar",
                    "mTotalLaps": 1,
                    "mTimeIntoLap": 0.1,
                    "mLapDist": 2.0,
                    "mSector": 1,
                    "mCountLapFlag": 2,
                    "mLastLapTime": -1.0,
                }
            ],
        }
        self.engine.update_scoring(scoring_js)

        # Feed 100 points along lap 1
        for i in range(1, 101):
            dist = i * 10.0  # 10m to 1000m
            t_into = (dist / track_len) * lap_time
            scoring_js["mVehicles"][0]["mLapDist"] = dist
            scoring_js["mVehicles"][0]["mTimeIntoLap"] = t_into
            scoring_js["mVehicles"][0]["mSector"] = 1 if dist < 333 else (2 if dist < 666 else 3)
            self.engine.update_scoring(scoring_js)

        # Complete Lap 1
        scoring_js["mVehicles"][0]["mTotalLaps"] = 2
        scoring_js["mVehicles"][0]["mLastLapTime"] = lap_time
        scoring_js["mVehicles"][0]["mLapDist"] = 5.0
        scoring_js["mVehicles"][0]["mTimeIntoLap"] = 0.25
        self.engine.update_scoring(scoring_js)

        # Now reference lap should be established!
        self.assertTrue(self.engine.has_reference)
        saved_file = Path(self.temp_dir) / "ref_testtrack_testcar.json"
        self.assertTrue(saved_file.exists())

        # 2. Drive Lap 2 faster (45 seconds pace -> delta should be negative / gain)
        # At dist 500m (halfway), ref_time was 25.0s. If current t_into is 22.5s, delta should be -2.5s
        scoring_js["mVehicles"][0]["mLapDist"] = 500.0
        scoring_js["mVehicles"][0]["mTimeIntoLap"] = 22.5
        scoring_js["mVehicles"][0]["mSector"] = 2
        self.engine.update_scoring(scoring_js)

        self.assertAlmostEqual(self.engine.live_delta, -2.5, delta=0.2)

    def test_50hz_extrapolation(self):
        """Verify 50Hz physics extrapolation smooths delta between 1Hz scoring updates."""
        # Manually set reference grid: 1000m, 50s lap time (20 m/s constant speed)
        self.engine._track_name = "TestTrack"
        self.engine._vehicle_name = "TestCar"
        self.engine._track_length = 1000.0
        self.engine._ref_lap_time = 50.0
        self.engine._ref_spatial_step = 1.0
        self.engine._ref_t_grid = [(d / 1000.0) * 50.0 for d in range(1001)]
        self.engine._ref_num_points = 1001

        self.assertTrue(self.engine.has_reference)

        # 1Hz scoring packet received at dist = 200m, time_into = 10.0s (Delta = 0.0)
        scoring_js = {
            "mTrackName": "TestTrack",
            "mLapDist": 1000.0,
            "mVehicles": [
                {
                    "mIsPlayer": True,
                    "mVehicleName": "TestCar",
                    "mTotalLaps": 1,
                    "mTimeIntoLap": 10.0,
                    "mLapDist": 200.0,
                    "mSector": 1,
                    "mCountLapFlag": 2,
                }
            ],
        }
        self.engine.update_scoring(scoring_js)
        self.assertAlmostEqual(self.engine.live_delta, 0.0, delta=0.05)

        # 100ms later (50Hz physics tick), car driving at 25 m/s (faster than 20 m/s ref speed)
        # In 0.1s, car moves 2.5m (dist 202.5m), time_into = 10.1s.
        # Ref time at 202.5m is 202.5 / 20 = 10.125s.
        # Live delta should be 10.10 - 10.125 = -0.025s (gaining time!)
        import time
        time.sleep(0.1)
        self.engine.update_physics(25.0)

        self.assertLess(self.engine.live_delta, 0.0)

    def test_session_reset_on_track_change(self):
        """Verify engine resets state when track changes."""
        self.engine._track_name = "Spa"
        self.engine._ref_t_grid = [0.0, 1.0, 2.0]
        self.engine._ref_num_points = 3

        scoring_js = {
            "mTrackName": "LeMans",
            "mLapDist": 13000.0,
            "mVehicles": [
                {
                    "mIsPlayer": True,
                    "mVehicleName": "TestCar",
                    "mTotalLaps": 1,
                    "mTimeIntoLap": 5.0,
                    "mLapDist": 100.0,
                }
            ],
        }
        self.engine.update_scoring(scoring_js)
        self.assertEqual(self.engine._track_name, "LeMans")
        self.assertFalse(self.engine.has_reference)


if __name__ == "__main__":
    unittest.main()
