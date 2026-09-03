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
        self.assertEqual(self.engine.sector_1_time, 0.0)
        self.assertEqual(self.engine.sector_2_time, 0.0)

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
        self.assertAlmostEqual(self.engine.sector_1_dist, 340.0, delta=10.0)
        self.assertAlmostEqual(self.engine.sector_2_dist, 670.0, delta=10.0)
        self.assertGreater(self.engine.sector_1_time, 0.0)
        self.assertGreater(self.engine.sector_2_time, 0.0)
        self.assertAlmostEqual(self.engine.all_time_best_profile.sector_1_dist, 340.0, delta=10.0)
        self.assertAlmostEqual(self.engine.all_time_best_profile.sector_2_dist, 670.0, delta=10.0)
        self.assertAlmostEqual(self.engine.all_time_best_profile.sector_1_time, self.engine.sector_1_time)
        self.assertAlmostEqual(self.engine.all_time_best_profile.sector_2_time, self.engine.sector_2_time)

        # 2. Drive Lap 2 faster (45 seconds pace -> delta should be negative / gain)
        # At dist 500m (halfway), ref_time was 25.0s. If current t_into is 22.5s, delta should be -2.5s
        scoring_js["mVehicles"][0]["mLapDist"] = 500.0
        scoring_js["mVehicles"][0]["mTimeIntoLap"] = 22.5
        scoring_js["mVehicles"][0]["mSector"] = 2
        self.engine.update_scoring(scoring_js)

        self.assertAlmostEqual(self.engine.live_delta, -2.5, delta=0.2)

    def test_50hz_extrapolation(self):
        """Verify delta calculation on scoring updates."""
        # Manually set reference grid: 1000m, 50s lap time (20 m/s constant speed)
        self.engine._track_name = "TestTrack"
        self.engine._vehicle_name = "TestCar"
        self.engine._track_length = 1000.0
        self.engine._ref_lap_time = 50.0
        self.engine._ref_spatial_step = 1.0
        self.engine._ref_t_grid = [(d / 1000.0) * 50.0 for d in range(1001)]
        self.engine._ref_num_points = 1001

        self.assertTrue(self.engine.has_reference)

        # Scoring packet received at dist = 200m, time_into = 10.0s (Delta = 0.0)
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

        # Next packet at dist = 250m (ref_time = 12.5s) with time_into = 12.0s -> Delta = -0.5s (gaining time)
        scoring_js["mVehicles"][0]["mLapDist"] = 250.0
        scoring_js["mVehicles"][0]["mTimeIntoLap"] = 12.0
        self.engine.update_scoring(scoring_js)
        self.assertAlmostEqual(self.engine.live_delta, -0.5, delta=0.05)

    def test_session_reset_on_track_change(self):
        """Verify engine resets state when track changes."""
        self.engine._track_name = "Spa"
        self.engine._ref_t_grid = [0.0, 1.0, 2.0]
        self.engine._ref_num_points = 3
        self.engine._last_laps_completed = 5

        scoring_js = {
            "mTrackName": "LeMans",
            "mLapDist": 13000.0,
            "mVehicles": [
                {
                    "mIsPlayer": True,
                    "mVehicleName": "TestCar",
                    "mTotalLaps": 0,
                    "mTimeIntoLap": 5.0,
                    "mLapDist": 100.0,
                }
            ],
        }
        self.engine.update_scoring(scoring_js)
        self.assertEqual(self.engine._track_name, "LeMans")
        self.assertEqual(self.engine._last_laps_completed, 0)
        self.assertFalse(self.engine.has_reference)

    def test_track_change_records_new_lap_properly(self):
        """Verify that after doing 5 laps on Track A, switching to Track B allows recording lap 1."""
        # 1. Simulate track A with 5 laps completed
        self.engine._track_name = "TrackA"
        self.engine._last_laps_completed = 5

        # 2. Switch to Track B at lap 0 (Outlap / Start)
        track_len = 1000.0
        lap_time = 45.0
        scoring_js = {
            "mTrackName": "TrackB",
            "mLapDist": track_len,
            "mVehicles": [
                {
                    "mIsPlayer": True,
                    "mVehicleName": "TestCar",
                    "mTotalLaps": 0,
                    "mTimeIntoLap": 0.1,
                    "mLapDist": 5.0,
                    "mSector": 1,
                    "mCountLapFlag": 2,
                    "mLastLapTime": -1.0,
                }
            ],
        }
        self.engine.update_scoring(scoring_js)
        self.assertEqual(self.engine._last_laps_completed, 0)

        # Drive flying lap 0 -> 1 on Track B
        for i in range(1, 20):
            dist = i * 50.0
            t_into = (dist / track_len) * lap_time
            scoring_js["mVehicles"][0]["mLapDist"] = dist
            scoring_js["mVehicles"][0]["mTimeIntoLap"] = t_into
            scoring_js["mVehicles"][0]["mSector"] = 1 if dist < 333 else (2 if dist < 666 else 3)
            self.engine.update_scoring(scoring_js)

        # Cross finish line -> mTotalLaps becomes 1
        scoring_js["mVehicles"][0]["mTotalLaps"] = 1
        scoring_js["mVehicles"][0]["mLastLapTime"] = lap_time
        scoring_js["mVehicles"][0]["mLapDist"] = 2.0
        scoring_js["mVehicles"][0]["mTimeIntoLap"] = 0.1
        self.engine.update_scoring(scoring_js)

        # Must have recorded the reference lap on Track B!
        self.assertTrue(self.engine.has_reference)
        saved_file = Path(self.temp_dir) / "ref_trackb_testcar.json"
        self.assertTrue(saved_file.exists())



    def test_multi_reference_modes(self):
        """Verify hierarchy and switching between All-Time Best, Session Best, Stint Best, and Last Lap."""
        from src.telemetry.delta_engine import DeltaReferenceMode
        track_len = 1000.0

        # Helper to simulate completing a lap with given lap_time
        def complete_lap(lap_idx, lap_time):
            scoring_js = {
                "mTrackName": "TestTrack",
                "mLapDist": track_len,
                "mVehicles": [{
                    "mIsPlayer": True,
                    "mVehicleName": "TestCar",
                    "mTotalLaps": lap_idx - 1,
                    "mTimeIntoLap": 0.1,
                    "mLapDist": 1.0,
                    "mSector": 1,
                    "mCountLapFlag": 2,
                    "mLastLapTime": -1.0,
                }],
            }
            self.engine.update_scoring(scoring_js)
            for i in range(1, 11):
                dist = i * 100.0
                t_into = (dist / track_len) * lap_time
                scoring_js["mVehicles"][0]["mLapDist"] = dist
                scoring_js["mVehicles"][0]["mTimeIntoLap"] = t_into
                self.engine.update_scoring(scoring_js)
            # Complete
            scoring_js["mVehicles"][0]["mTotalLaps"] = lap_idx
            scoring_js["mVehicles"][0]["mLastLapTime"] = lap_time
            scoring_js["mVehicles"][0]["mLapDist"] = 1.0
            scoring_js["mVehicles"][0]["mTimeIntoLap"] = 0.05
            self.engine.update_scoring(scoring_js)

        # Lap 1: 50.0s (Best, Session, Stint, Last)
        complete_lap(1, 50.0)
        self.assertEqual(self.engine._all_time_best_lap_time, 50.0)
        self.assertEqual(self.engine._session_best_lap_time, 50.0)
        self.assertEqual(self.engine._stint_best_lap_time, 50.0)
        self.assertEqual(self.engine._last_lap_time, 50.0)

        # Lap 2: 48.0s (New All-time / Session / Stint Best, Last = 48s)
        complete_lap(2, 48.0)
        self.assertEqual(self.engine._all_time_best_lap_time, 48.0)
        self.assertEqual(self.engine._last_lap_time, 48.0)

        # Lap 3: 52.0s (Slower lap. All-time Best remains 48s, Last Lap becomes 52s)
        complete_lap(3, 52.0)
        self.assertEqual(self.engine._all_time_best_lap_time, 48.0)
        self.assertEqual(self.engine._last_lap_time, 52.0)

        # Check switching reference mode
        self.engine.reference_mode = DeltaReferenceMode.LAST_LAP
        self.assertEqual(self.engine.current_profile.lap_time, 52.0)

        self.engine.reference_mode = DeltaReferenceMode.ALL_TIME_BEST
        self.assertEqual(self.engine.current_profile.lap_time, 48.0)

    def test_mid_sector_reference_mode_switch(self):
        """Verify that changing reference mode in the middle of Sector 2 dynamically recalculates sector deltas."""
        from src.telemetry.delta_engine import DeltaReferenceMode
        from src.telemetry.reference_profile import ReferenceLapProfile

        # Setup 2 distinct reference profiles for a 1000m track
        # Profile A (All-Time Best): 50.0s lap (S1=16.65s at 333m, S2=33.3s at 666m)
        prof_a = ReferenceLapProfile(
            track_name="TestTrack",
            lap_time=50.0,
            track_length=1000.0,
            spatial_step=1.0,
            num_points=1001,
            t_grid=[(d / 1000.0) * 50.0 for d in range(1001)],
        )
        # Profile B (Session Best): 60.0s lap (S1=19.98s at 333m, S2=39.96s at 666m)
        prof_b = ReferenceLapProfile(
            track_name="TestTrack",
            lap_time=60.0,
            track_length=1000.0,
            spatial_step=1.0,
            num_points=1001,
            t_grid=[(d / 1000.0) * 60.0 for d in range(1001)],
        )

        self.engine._all_time_best_profile = prof_a
        self.engine._session_best_profile = prof_b
        self.engine.reference_mode = DeltaReferenceMode.ALL_TIME_BEST

        # 1. Drive Sector 1 and cross into Sector 2 at 333m in 15.0s (vs Prof A S1=16.65s -> Delta S1 = -1.65s)
        self.engine._handle_sector_transition(2, time_into=15.0, player_dist=333.0)
        # Drive inside Sector 2 at 500m in 23.0s (Prof A ref=25.0s -> live delta = -2.0s)
        self.engine._calculate_delta(500.0, 23.0)

        self.assertAlmostEqual(self.engine._sector1_delta, -1.65, delta=0.01)
        self.assertAlmostEqual(self.engine._sector2_delta, -0.35, delta=0.01)  # -2.0 - (-1.65) = -0.35s

        # 2. Switch reference mode to SESSION_BEST (Profile B) in the middle of Sector 2!
        self.engine.reference_mode = DeltaReferenceMode.SESSION_BEST

        # With Profile B:
        # Ref time at 333m was 19.98s -> S1 Delta should now be: 15.0 - 19.98 = -4.98s
        # Ref time at 500m is 30.0s -> Live Delta should now be: 23.0 - 30.0 = -7.0s
        # S2 Delta should now be: -7.0 - (-4.98) = -2.02s
        self.engine._calculate_delta(500.0, 23.0)
        self.assertAlmostEqual(self.engine._sector1_delta, -4.98, delta=0.01)
        self.assertAlmostEqual(self.engine._sector2_delta, -2.02, delta=0.01)
        self.assertAlmostEqual(self.engine.live_delta, -7.0, delta=0.01)

    def test_estimated_lap_time(self):
        """Verify estimated lap time projection and formatting."""
        self.engine._track_name = "TestTrack"
        self.engine._track_length = 1000.0
        self.engine._ref_lap_time = 60.0
        self.engine._ref_spatial_step = 1.0
        self.engine._ref_t_grid = [(d / 1000.0) * 60.0 for d in range(1001)]
        self.engine._ref_num_points = 1001

        # Car at 500m (ref_time = 30.0s), current time_into = 28.5s (delta = -1.5s)
        self.engine._calculate_delta(500.0, 28.5)
        self.assertAlmostEqual(self.engine.live_delta, -1.5)
        self.assertAlmostEqual(self.engine.estimated_lap_time, 58.5)
        self.assertEqual(self.engine.estimated_lap_time_str, "00:58.500")

    def test_finish_line_delta_freeze(self):
        """Verify delta and lap time are frozen upon crossing the finish line for driver HUD visibility."""
        self.engine._track_name = "TestTrack"
        self.engine._track_length = 1000.0
        self.engine._ref_lap_time = 50.0
        self.engine._ref_spatial_step = 1.0
        self.engine._ref_t_grid = [(d / 1000.0) * 50.0 for d in range(1001)]
        self.engine._ref_num_points = 1001
        self.engine.freeze_duration = 2.0  # 2 seconds freeze
        self.engine._last_laps_completed = 0

        # End of flying lap: dist = 999m, time_into = 48.0s -> Delta = -1.95s
        self.engine._calculate_delta(999.0, 48.0)
        self.assertLess(self.engine.live_delta, 0.0)

        # Cross finish line (first clean lap 48.0s -> faster than 50.0s ref -> purple/green)
        self.engine._handle_lap_transition(
            laps_comp=1,
            last_lap_time=48.0,
            lap_flag=2,
            in_garage=False,
            in_pits=False,
        )

        # New lap starts: time_into is 0.1s, dist is 5m -> live_delta is near 0.0
        self.engine._calculate_delta(5.0, 0.25)

        # display_delta must be frozen at the final delta of lap 1!
        self.assertAlmostEqual(self.engine.display_delta, self.engine._frozen_final_delta, delta=0.01)
        # Lap time and status must be frozen!
        self.assertTrue(self.engine.is_lap_freeze_active)
        self.assertEqual(self.engine.last_completed_lap_time, 48.0)
        self.assertEqual(self.engine.last_completed_lap_time_str, "00:48.000")
        self.assertIn(self.engine.last_completed_lap_status, ("purple", "green"))

    def test_ema_smoothing_filter(self):
        """Verify exponential moving average smoothing filter on live delta."""
        self.engine._track_name = "TestTrack"
        self.engine._track_length = 1000.0
        self.engine._ref_lap_time = 50.0
        self.engine._ref_spatial_step = 1.0
        self.engine._ref_t_grid = [(d / 1000.0) * 50.0 for d in range(1001)]
        self.engine._ref_num_points = 1001
        self.engine.ema_samples = 5  # Enable EMA with 5 samples

        # Feed a sudden jump at dist 500m (ref_time = 25.0s) from time_into = 25.0s to 27.0s (raw delta = +2.0s)
        self.engine._calculate_delta(500.0, 25.0)  # delta = 0.0
        self.assertEqual(self.engine.live_delta, 0.0)

        self.engine._calculate_delta(500.0, 27.0)  # raw delta = +2.0s
        # EMA factor = 2 / (5 + 1) = 0.333 -> EMA delta should be 0 + 0.333 * (2 - 0) = ~0.667
        self.assertAlmostEqual(self.engine.live_delta, 2.0 * (2.0 / 6.0), delta=0.01)

    def test_standstill_delta_freeze(self):
        """Verify delta is calculated correctly when stationary."""
        self.engine._track_name = "TestTrack"
        self.engine._track_length = 1000.0
        self.engine._ref_lap_time = 50.0
        self.engine._ref_spatial_step = 1.0
        self.engine._ref_t_grid = [(d / 1000.0) * 50.0 for d in range(1001)]
        self.engine._ref_num_points = 1001

        # Car reached checkpoint at 200m in 10.0s (ref_time = 10.0s, delta = 0.0)
        self.engine._calculate_delta(200.0, 10.0)
        self.assertEqual(self.engine.live_delta, 0.0)

        # Vehicle inputs update at standstill (speed = 0.0 m/s)
        self.engine.update_physics(veh_speed_ms=0.0)

        # Delta remains unchanged at 0.0
        self.assertEqual(self.engine.live_delta, 0.0)

    def test_dirty_lap_not_recorded(self):
        """Verify dirty laps (lap_flag == 0) are strictly rejected from becoming reference laps."""
        self.engine._track_name = "TestTrack"
        self.engine._track_length = 1000.0
        self.engine._last_laps_completed = 1

        # Fake samples
        self.engine._current_lap_samples = [(i * 100.0, i * 4.0, 25.0, 1.0, 0.0, 0.0) for i in range(11)]

        # Finalize lap with lap_flag = 0 (Dirty / Cut track)
        self.engine._finalize_completed_lap(
            lap_time=40.0,
            lap_flag=0,
            in_garage=False,
            in_pits=False,
        )

        # Must not be saved as reference
        self.assertFalse(self.engine.has_reference)
        self.assertEqual(self.engine._all_time_best_lap_time, 999999.0)

    def test_session_ref_no_lap_initially(self):
        """Verify that when in SESSION_BEST mode with no session lap completed, has_reference is False."""
        from src.telemetry.delta_engine import DeltaReferenceMode
        # Simulate having an All-Time Best on disk
        self.engine._all_time_best_lap_time = 45.0
        self.engine._all_time_best_profile = "fake"  # Mock

        # Switch to SESSION_BEST mode
        self.engine.reference_mode = DeltaReferenceMode.SESSION_BEST
        # Since _session_best_profile is None, current_profile must be None and has_reference False!
        self.assertIsNone(self.engine.current_profile)
        self.assertFalse(self.engine.has_reference)
        self.assertEqual(self.engine.live_delta, 0.0)

    def test_slow_driving_delta_explodes_positive(self):
        """Verify that driving slowly causes delta to explode positive (massive lap time loss in RED)."""
        self.engine._track_name = "TestTrack"
        self.engine._track_length = 1000.0
        self.engine._ref_lap_time = 50.0  # 50s lap
        self.engine._ref_spatial_step = 1.0
        self.engine._ref_t_grid = [(d / 1000.0) * 50.0 for d in range(1001)]  # At 200m -> 10.0s
        self.engine._ref_num_points = 1001

        # Car reached 200m (ref_time = 10.0s) but took 45.0s because driving at crawl speed!
        self.engine._calculate_delta(200.0, 45.0)
        # Delta must be +35.0s!
        self.assertAlmostEqual(self.engine.live_delta, 35.0)
        self.assertAlmostEqual(self.engine.estimated_lap_time, 85.0)
        self.assertEqual(self.engine.estimated_lap_time_str, "01:25.000")

    def test_scoring_elapsed_time_crawl_and_stop(self):
        """Verify that update_scoring and update_physics use real clock elapsed time (mCurrentET - mLapStartET)."""
        from src.telemetry.reference_profile import ReferenceLapProfile
        
        prof = ReferenceLapProfile(
            track_name="TestTrack",
            vehicle_name="TestCar",
            lap_time=50.0,
            track_length=1000.0,
            spatial_step=1.0,
            num_points=1001,
            t_grid=[(d / 1000.0) * 50.0 for d in range(1001)],  # 200m -> 10.0s
        )
        self.engine._track_name = "TestTrack"
        self.engine._vehicle_name = "TestCar"
        self.engine._all_time_best_profile = prof
        self.engine._all_time_best_lap_time = 50.0
        self.engine._apply_active_profile()

        scoring_packet = {
            "mTrackName": "TestTrack",
            "mLapDist": 1000.0,
            "mCurrentET": 160.0,  # Lap started at 100.0 -> 60s elapsed in lap
            "mVehicles": [{
                "mIsPlayer": True,
                "mVehicleName": "TestCar",
                "mLapDist": 200.0,  # Car is at 200m (ref is 10.0s)
                "mLapStartET": 100.0,
                "mTimeIntoLap": 10.0,  # Bogus distance-based estimated time from rF2/LMU
                "mCountLapFlag": 2,
                "mSector": 1,
            }]
        }

        self.engine.update_scoring(scoring_packet)
        # Real time_into = 160.0 - 100.0 = 60.0s -> delta = 60.0 - 10.0 = +50.0s (MASSIVE DELAY!)
        self.assertAlmostEqual(self.engine.live_delta, 50.0)

        # Now car is stationary at 200m for 10 more seconds (physics at 170.0s)
        self.engine.update_physics(
            veh_speed_ms=0.0,
            elapsed_time=170.0,
            lap_start_et=100.0,
        )
        # Delta must now be 70.0 - 10.0 = +60.0s!
        self.assertAlmostEqual(self.engine.live_delta, 60.0)

    def test_truncated_and_out_laps_rejected(self):
        """Verify that out-laps with lap_time <= 0, partial track coverage, or impossible speed are rejected."""
        self.engine._track_name = "TestTrack"
        self.engine._track_length = 5000.0
        self.engine._all_time_best_lap_time = 120.0

        # Case 1: Out-lap with lap_time = -1.0 (from game) and only 100 samples
        self.engine._current_lap_samples = [(i * 20.0, i * 0.3, 20.0, 1.0, 0.0, 0.0) for i in range(100)]
        self.engine._finalize_completed_lap(lap_time=-1.0, lap_flag=2, in_garage=False, in_pits=False)
        self.assertEqual(self.engine._all_time_best_lap_time, 120.0)

        # Case 2: Physically impossible lap time (35.0s on 5000m track -> > 500 km/h)
        self.engine._current_lap_samples = [(i * 50.0, i * 0.35, 50.0, 1.0, 0.0, 0.0) for i in range(101)]
        self.engine._finalize_completed_lap(lap_time=35.0, lap_flag=2, in_garage=False, in_pits=False)
        self.assertEqual(self.engine._all_time_best_lap_time, 120.0)

        # Case 3: Incomplete spatial coverage (samples only start at 2000m and end at 3000m)
        self.engine._current_lap_samples = [(2000.0 + i * 10.0, 50.0 + i * 0.5, 20.0, 1.0, 0.0, 0.0) for i in range(100)]
        self.engine._finalize_completed_lap(lap_time=110.0, lap_flag=2, in_garage=False, in_pits=False)
        self.assertEqual(self.engine._all_time_best_lap_time, 120.0)

    def test_format_lap_time(self):
        """Verify format_lap_time formats in MM:ss.mmm."""
        from src.telemetry.delta_engine import format_lap_time
        self.assertEqual(format_lap_time(92.45), "01:32.450")
        self.assertEqual(format_lap_time(125.008), "02:05.008")
        self.assertEqual(format_lap_time(58.123), "00:58.123")
        self.assertEqual(format_lap_time(0.0), "--:--.---")
        self.assertEqual(format_lap_time(-1.0), "--:--.---")
        self.assertEqual(format_lap_time(999999.0), "--:--.---")

    def test_lap_transition_status_colors(self):
        """Verify status colors: purple for session best, green for personal improvement, yellow for slower, grey for invalid."""
        self.engine._track_name = "TestTrack"
        self.engine._track_length = 1000.0
        self.engine.freeze_duration = 3.5

        # Initial state: session best = 90.0s, reference = 92.0s
        self.engine._session_best_lap_time = 90.0
        self.engine._all_time_best_lap_time = 90.0
        self.engine._ref_lap_time = 92.0
        self.engine._last_laps_completed = 1

        # Case 1: Driver runs 89.5s -> New Session / All-time Best -> Purple
        self.engine._handle_lap_transition(laps_comp=2, last_lap_time=89.5, lap_flag=2, in_garage=False, in_pits=False)
        self.assertEqual(self.engine.last_completed_lap_status, "purple")
        self.assertEqual(self.engine.last_completed_lap_time_str, "01:29.500")
        self.assertTrue(self.engine.is_lap_freeze_active)

        # Case 2: Session best is 89.5s, active ref is 91.0s. Driver runs 90.2s -> Personal Improvement -> Green
        self.engine._session_best_lap_time = 89.5
        self.engine._ref_lap_time = 91.0
        self.engine._handle_lap_transition(laps_comp=3, last_lap_time=90.2, lap_flag=2, in_garage=False, in_pits=False)
        self.assertEqual(self.engine.last_completed_lap_status, "green")
        self.assertEqual(self.engine.last_completed_lap_time_str, "01:30.200")

        # Case 3: Active ref is 90.2s. Driver runs 91.8s -> Slower / No improvement -> Yellow
        self.engine._session_best_lap_time = 89.5
        self.engine._ref_lap_time = 90.2
        self.engine._handle_lap_transition(laps_comp=4, last_lap_time=91.8, lap_flag=2, in_garage=False, in_pits=False)
        self.assertEqual(self.engine.last_completed_lap_status, "yellow")
        self.assertEqual(self.engine.last_completed_lap_time_str, "01:31.800")

        # Case 4: Driver runs 88.0s but cut track (lap_flag = 0) -> Invalid / Grey
        self.engine._handle_lap_transition(laps_comp=5, last_lap_time=88.0, lap_flag=0, in_garage=False, in_pits=False)
        self.assertEqual(self.engine.last_completed_lap_status, "invalid")


if __name__ == "__main__":
    unittest.main()

