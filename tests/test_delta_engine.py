import os
import shutil
import unittest
import tempfile
from pathlib import Path
import simpulse.core.telemetry.delta_engine as delta_engine_module
from simpulse.core.telemetry.delta_engine import DeltaEngine, _clean_name


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
        """Simulate a valid lap and verify reference recording and delta calculation."""
        track_len = 1000.0
        lap_time = 50.0  # 50 seconds for 1000 meters -> 20 m/s

        # 1. Drive Lap 1 (Valid lap)
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

    def test_scoring_and_flying_tick_counters_reset_per_lap(self):
        """Diagnostic-only counters (_scoring_ticks_this_lap/_flying_ticks_this_lap,
        surfaced in _finalize_completed_lap's always-on log line — see its
        docstring) must count every update_scoring() call this lap, count the
        subset that passed the is_flying_lap gate, and reset for the new lap
        on a real lap transition."""
        scoring_js = {
            "mTrackName": "TestTrack",
            "mLapDist": 1000.0,
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

        # 9 more flying ticks (mCountLapFlag=2, mTimeIntoLap>0) this lap.
        for i in range(1, 10):
            scoring_js["mVehicles"][0]["mLapDist"] = 2.0 + i * 10.0
            scoring_js["mVehicles"][0]["mTimeIntoLap"] = 0.1 + i
            self.engine.update_scoring(scoring_js)
        self.assertEqual(self.engine._scoring_ticks_this_lap, 10)
        self.assertEqual(self.engine._flying_ticks_this_lap, 10)

        # One non-flying tick (invalid flag) still counts as a scoring tick
        # received, but not as a flying one.
        scoring_js["mVehicles"][0]["mCountLapFlag"] = 1
        self.engine.update_scoring(scoring_js)
        self.assertEqual(self.engine._scoring_ticks_this_lap, 11)
        self.assertEqual(self.engine._flying_ticks_this_lap, 10)

        # Lap transition -> counters reset for the new lap.
        scoring_js["mVehicles"][0]["mCountLapFlag"] = 2
        scoring_js["mVehicles"][0]["mTotalLaps"] = 2
        scoring_js["mVehicles"][0]["mLastLapTime"] = 55.0
        scoring_js["mVehicles"][0]["mLapDist"] = 5.0
        scoring_js["mVehicles"][0]["mTimeIntoLap"] = 0.25
        self.engine.update_scoring(scoring_js)
        self.assertEqual(self.engine._scoring_ticks_this_lap, 1)
        self.assertEqual(self.engine._flying_ticks_this_lap, 1)

    def test_collect_lap_sample_accepts_strictly_increasing_distance(self):
        self.engine._collect_lap_sample(time_into=1.0, player_dist=10.0)
        self.engine._collect_lap_sample(time_into=1.1, player_dist=10.5)
        self.assertEqual(len(self.engine._current_lap_samples), 2)

    def test_collect_lap_sample_rejects_non_monotonic_distance(self):
        """A tick reporting a distance <= the last saved sample's (jitter,
        duplicate packet, dead-reckoning noise) must be silently dropped, not
        appended — this is the ONLY point that decides whether a flying-lap
        tick becomes a saved checkpoint (see its docstring)."""
        self.engine._collect_lap_sample(time_into=1.0, player_dist=10.0)
        self.engine._collect_lap_sample(time_into=1.1, player_dist=10.0)  # equal -> rejected
        self.engine._collect_lap_sample(time_into=1.2, player_dist=9.9)   # decreased -> rejected
        self.assertEqual(len(self.engine._current_lap_samples), 1)
        self.assertEqual(self.engine._sample_monotonic_rejects_this_lap, 2)

    def test_collect_lap_sample_tracks_dist_span_always_even_when_rejected(self):
        """dist_min/dist_max (surfaced as dist_span on the "Lap completed" log
        line) must reflect every player_dist OFFERED to this function, not
        just the ones that got accepted — that's the whole point: a tiny span
        despite many calls is what reveals dead-reckoning stalled, and a
        rejected/backwards value must still widen the observed range."""
        self.engine._collect_lap_sample(time_into=1.0, player_dist=10.0)
        self.engine._collect_lap_sample(time_into=1.1, player_dist=10.0)   # rejected, still tracked
        self.engine._collect_lap_sample(time_into=1.2, player_dist=9.5)    # rejected, widens the min
        self.engine._collect_lap_sample(time_into=1.3, player_dist=10.5)   # accepted, widens the max
        self.assertAlmostEqual(self.engine._sample_dist_min_this_lap, 9.5)
        self.assertAlmostEqual(self.engine._sample_dist_max_this_lap, 10.5)

    def test_collect_lap_sample_rejects_invalid_inputs(self):
        self.engine._collect_lap_sample(time_into=0.0, player_dist=10.0)
        self.engine._collect_lap_sample(time_into=1.0, player_dist=-1.0)
        self.assertEqual(len(self.engine._current_lap_samples), 0)

    def test_collect_lap_sample_rejects_beyond_track_length_plus_margin(self):
        self.engine._track_length = 1000.0
        self.engine._collect_lap_sample(time_into=1.0, player_dist=1000.0)
        self.engine._collect_lap_sample(time_into=2.0, player_dist=1201.0)  # > 1000+200
        self.assertEqual(len(self.engine._current_lap_samples), 1)

    def test_physics_tick_counters_track_calls_and_dead_reckon_gate(self):
        """Diagnostic-only counters (surfaced on the "Lap completed" log line
        — see their field docstring): every update_physics() call increments
        physics_ticks_this_lap; only the ones that actually run the dead-
        reckoning integration (dt>0, speed>0) increment dead_reckon_ticks —
        this is what tells apart "TelemInfo isn't reaching DeltaEngine" from
        "it is, but dt/speed are zero"."""
        self.engine.update_physics(veh_speed_ms=20.0, dt=0.01)  # both > 0 -> dead-reckons
        self.engine.update_physics(veh_speed_ms=0.0, dt=0.01)   # speed == 0 -> gate fails
        self.engine.update_physics(veh_speed_ms=20.0, dt=0.0)   # dt == 0 -> gate fails
        self.assertEqual(self.engine._physics_ticks_this_lap, 3)
        self.assertEqual(self.engine._physics_dead_reckon_ticks_this_lap, 1)

    def test_lap_sample_reset_survives_finalize_completed_lap_raising(self):
        """Real-session bug: _current_lap_samples was found still holding
        the JUST-FINISHED lap's last sample deep into the NEXT one — poisoning
        its every reading exactly like the crossing-tick bug (see the test
        below), except this time _finalize_completed_lap() itself (profile
        resampling, disk I/O, WallOfFame update — all real ways to fail) had
        visibly completed (its own success log lines printed) yet the reset
        right after it apparently never ran, with no traceback surfacing
        anywhere. _handle_lap_transition now wraps the finalize call in
        try/finally specifically so the reset is unconditional."""
        from isimotor_rawudp_client import CompactScoring

        def compact(current_et, total_laps, last_lap_time=-1.0):
            return CompactScoring(
                track_name="TestTrack", lap_dist=1000.0, current_et=current_et,
                sector=1, count_lap_flag=2, last_lap_time=last_lap_time, total_laps=total_laps,
            )

        self.engine.update_scoring(compact(current_et=1.0, total_laps=1))
        self.engine._last_scoring_dist = 500.0
        self.engine.update_scoring(compact(current_et=10.0, total_laps=1))
        self.assertEqual(len(self.engine._current_lap_samples), 1)

        # Force _finalize_completed_lap to blow up, exactly like a real but
        # unidentified failure there would.
        self.engine._finalize_completed_lap = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
        self.engine.update_scoring(compact(current_et=70.0, total_laps=2, last_lap_time=60.0))

        # Despite the crash, the new lap's sample bookkeeping must still be
        # clean — not left holding the old lap's last sample forever. (The
        # counters read 1, not 0: this same crossing tick counts toward the
        # new lap's scoring_ticks/flying_ticks — see is_real_lap_crossing's
        # docstring — the reset in `finally` runs BEFORE that increment.)
        self.assertEqual(len(self.engine._current_lap_samples), 0)
        self.assertEqual(self.engine._scoring_ticks_this_lap, 1)
        self.assertEqual(self.engine._flying_ticks_this_lap, 1)

    def test_lap_crossing_tick_does_not_poison_next_lap_with_stale_distance(self):
        """Real-session bug: for a CompactScoring tick (no player_vehicle —
        player_dist falls back to self._last_scoring_dist, see
        update_scoring()'s CompactScoring branch), the tick that DETECTS a
        lap crossing reads player_dist BEFORE _handle_lap_transition runs —
        if _last_scoring_dist hadn't been wrapped back near 0 yet (no
        physics tick had a chance to, see update_physics's dead-reckoning),
        that tick's own player_dist is still near the OLD lap's tail (~track_
        length). Two compounding bugs made this poison the WHOLE lap, not
        just its first sample: (1) _current_lap_samples was just emptied, so
        that stale value used to get accepted unconditionally as the first
        sample, and (2) it was then written back into self._last_scoring_dist
        completely unconditionally at the tail of _apply_scoring_update —
        UNDOING _handle_lap_transition's own wrap-on-crossing correction the
        very same tick it ran, leaving every SUBSEQUENT CompactScoring tick
        for the rest of that lap reading the same stale near-track-length
        baseline. This is what a real session's 823/825 or 867/869 flying-
        tick monotonic-rejection rate — for an ENTIRE lap, not just its
        first tick — was actually coming from."""
        from isimotor_rawudp_client import CompactScoring

        def compact(current_et, total_laps, last_lap_time=-1.0):
            return CompactScoring(
                track_name="TestTrack", lap_dist=1000.0, current_et=current_et,
                sector=1, count_lap_flag=2, last_lap_time=last_lap_time, total_laps=total_laps,
            )

        # Tick 0: first-ever packet for this track — establishes track_name
        # (time_into is inherently 0 on this exact tick, see
        # _apply_scoring_update's track-change block resetting
        # _local_lap_start_et to current_et itself; not what's under test).
        self.engine.update_scoring(compact(current_et=1.0, total_laps=1))
        self.assertEqual(self.engine._flying_ticks_this_lap, 0)

        # Tick 1: now flying — establishes lap 1's first (and only, for this
        # test) sample at 500m.
        self.engine._last_scoring_dist = 500.0
        self.engine.update_scoring(compact(current_et=10.0, total_laps=1))
        self.assertEqual(len(self.engine._current_lap_samples), 1)
        self.assertAlmostEqual(self.engine._current_lap_samples[0][0], 500.0)

        # Tick 2: the crossing tick itself — stale dead-reckoned distance,
        # NOT yet wrapped back near 0 (the exact race this fix closes).
        self.engine._last_scoring_dist = 995.0
        self.engine.update_scoring(compact(current_et=70.0, total_laps=2, last_lap_time=60.0))
        # The crossing tick's own (stale, 995.0) sample must NOT have been
        # recorded as the new lap's first sample...
        self.assertEqual(len(self.engine._current_lap_samples), 0)
        # ...AND self._last_scoring_dist itself must have been corrected,
        # not left at 995.0 to poison every tick after this one too (bug 2
        # above — the actual gap in the first version of this fix).
        self.assertAlmostEqual(self.engine._last_scoring_dist, 0.0)

        # Tick 3: NO manual override this time — a real physics tick dead-
        # reckons forward from whatever self._last_scoring_dist now holds,
        # exactly like a live session would, then a scoring tick reads it.
        self.engine.update_physics(veh_speed_ms=30.0, dt=0.1)  # +3.0m
        self.engine.update_scoring(compact(current_et=70.2, total_laps=2))
        self.assertEqual(len(self.engine._current_lap_samples), 1)
        self.assertAlmostEqual(self.engine._current_lap_samples[0][0], 3.0)

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
        from simpulse.core.telemetry.delta_engine import DeltaReferenceMode
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

        # reference_mode is stored (config/API compatibility) but no longer
        # selects which profile drives the live delta/HUD — that's always the
        # All-Time Best profile, regardless of mode. See
        # DeltaEngine._apply_active_profile.
        self.engine.reference_mode = DeltaReferenceMode.LAST_LAP
        self.assertEqual(self.engine.current_profile.lap_time, 48.0)

        self.engine.reference_mode = DeltaReferenceMode.SESSION_BEST
        self.assertEqual(self.engine.current_profile.lap_time, 48.0)

        self.engine.reference_mode = DeltaReferenceMode.ALL_TIME_BEST
        self.assertEqual(self.engine.current_profile.lap_time, 48.0)

    def test_reference_mode_never_switches_active_profile(self):
        """The live delta/HUD spatial reference is ALWAYS the All-Time Best
        profile — reference_mode (all_time/session/stint/last-lap) no longer
        selects which profile drives it (see DeltaEngine._apply_active_profile).
        Switching mode mid-sector must not perturb an in-progress delta/sector
        calculation at all: it's a pure no-op on current_profile."""
        from simpulse.core.telemetry.delta_engine import DeltaReferenceMode
        from simpulse.core.telemetry.reference_profile import ReferenceLapProfile

        # Profile A (All-Time Best): 50.0s lap (S1=16.65s at 333m, S2=33.3s at 666m)
        prof_a = ReferenceLapProfile(
            track_name="TestTrack",
            lap_time=50.0,
            track_length=1000.0,
            spatial_step=1.0,
            num_points=1001,
            t_grid=[(d / 1000.0) * 50.0 for d in range(1001)],
        )
        # Profile B (Session Best): a different lap — must NOT affect anything below.
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
        self.engine._apply_active_profile()
        self.assertIs(self.engine.current_profile, prof_a)

        # Drive Sector 1 and cross into Sector 2 at 333m in 15.0s (vs Prof A S1=16.65s -> Delta S1 = -1.65s)
        self.engine._handle_sector_transition(2, time_into=15.0, player_dist=333.0)
        # Drive inside Sector 2 at 500m in 23.0s (Prof A ref=25.0s -> live delta = -2.0s)
        self.engine._calculate_delta(500.0, 23.0)
        self.assertAlmostEqual(self.engine._sector1_delta, -1.65, delta=0.01)
        self.assertAlmostEqual(self.engine._sector2_delta, -0.35, delta=0.01)  # -2.0 - (-1.65) = -0.35s

        # Switching reference_mode to SESSION_BEST mid-sector must be a no-op:
        # current_profile stays Profile A, and the delta recomputed against the
        # SAME profile must match exactly (Profile B is never consulted).
        self.engine.reference_mode = DeltaReferenceMode.SESSION_BEST
        self.assertIs(self.engine.current_profile, prof_a)
        self.engine._calculate_delta(500.0, 23.0)
        self.assertAlmostEqual(self.engine._sector1_delta, -1.65, delta=0.01)
        self.assertAlmostEqual(self.engine._sector2_delta, -0.35, delta=0.01)
        self.assertAlmostEqual(self.engine.live_delta, -2.0, delta=0.01)

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
        # Session best from an earlier lap this session, so the 48.0s crossing
        # below has something meaningful to beat (no paddock data -> green, not
        # purple/default; see test_lap_transition_status_colors for the full
        # purple/green/yellow matrix).
        self.engine._session_best_lap_time = 50.0

        # End of flying lap: dist = 999m, time_into = 48.0s -> Delta = -1.95s
        self.engine._calculate_delta(999.0, 48.0)
        self.assertLess(self.engine.live_delta, 0.0)

        # Cross finish line (first valid lap 48.0s -> faster than 50.0s session best -> green)
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
        self.assertEqual(self.engine.last_completed_lap_status, "green")

    def _seed_reference(self):
        """Shared setup for the smoothing tests below: a flat 50s reference
        lap over 1000m, so ref_time == player_dist / 20."""
        self.engine._track_name = "TestTrack"
        self.engine._track_length = 1000.0
        self.engine._ref_lap_time = 50.0
        self.engine._ref_spatial_step = 1.0
        self.engine._ref_t_grid = [(d / 1000.0) * 50.0 for d in range(1001)]
        self.engine._ref_num_points = 1001

    def test_smoothing_window_filter(self):
        """Verify the moving-average smoothing window on smoothed_live_delta —
        replaces the old EMA mechanism (now removed)."""
        self._seed_reference()
        self.engine.delta_smoothing_window_s = 2.0  # 2s moving-average window (game time)

        # Raw delta = 0.0 at game time 25.0s.
        self.engine._calculate_delta(500.0, 25.0)
        self.assertEqual(self.engine.live_delta, 0.0)
        self.assertEqual(self.engine.smoothed_live_delta, 0.0)

        # 2s later (still inside the 2s window): raw delta jumps to +2.0s.
        self.engine._calculate_delta(500.0, 27.0)
        self.assertAlmostEqual(self.engine.live_delta, 2.0, delta=0.001)
        # Moving average of [0.0, 2.0] = 1.0 — the raw value is untouched,
        # only smoothed_live_delta lags behind it.
        self.assertAlmostEqual(self.engine.smoothed_live_delta, 1.0, delta=0.001)

    def test_time_status_smoothed_differs_from_time_status_under_changing_delta(self):
        """time_status (raw) and time_status_smoothed (moving average) must
        diverge mid-transient, while time_status.lap.delta_time always tracks
        live_delta exactly (never smoothed)."""
        self._seed_reference()
        self.engine.delta_smoothing_window_s = 2.0

        self.engine._calculate_delta(500.0, 25.0)
        self.engine._calculate_delta(500.0, 27.0)

        self.assertAlmostEqual(self.engine.time_status.lap.delta_time, self.engine.live_delta, delta=0.001)
        self.assertAlmostEqual(self.engine.time_status_smoothed.lap.delta_time, self.engine.smoothed_live_delta, delta=0.001)
        self.assertNotAlmostEqual(
            self.engine.time_status.lap.delta_time,
            self.engine.time_status_smoothed.lap.delta_time,
            delta=0.001,
        )

    def test_sector_decomposition_matches_for_raw_and_smoothed(self):
        """Sector split decomposition must hold the same relationship for
        both the raw and smoothed TimeStatus — see
        SectorEngine.compute_split_deltas_pure."""
        self._seed_reference()
        self.engine.delta_smoothing_window_s = 2.0
        # Force "current sector" to 2 so the decomposition exercises the
        # delta_s1_end-relative branch, not just the trivial S1 passthrough.
        self.engine._sectors.last_current_sector = 2

        self.engine._calculate_delta(500.0, 25.0)
        self.engine._calculate_delta(500.0, 27.0)

        raw_s2 = self.engine.time_status.sectors[1].delta_time
        smoothed_s2 = self.engine.time_status_smoothed.sectors[1].delta_time
        self.assertAlmostEqual(raw_s2, self.engine.live_delta, delta=0.001)
        self.assertAlmostEqual(smoothed_s2, self.engine.smoothed_live_delta, delta=0.001)

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

    def test_invalid_lap_not_recorded(self):
        """Verify invalid laps (lap_flag == 0) are strictly rejected from becoming reference laps."""
        self.engine._track_name = "TestTrack"
        self.engine._track_length = 1000.0
        self.engine._last_laps_completed = 1

        # Fake samples
        self.engine._current_lap_samples = [(i * 100.0, i * 4.0, 25.0, 1.0, 0.0, 0.0) for i in range(11)]

        # Finalize lap with lap_flag = 0 (Invalid / Cut track)
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
        from simpulse.core.telemetry.delta_engine import DeltaReferenceMode
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
        from simpulse.core.telemetry.reference_profile import ReferenceLapProfile
        
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
        from simpulse.core.telemetry.delta_engine import format_lap_time
        self.assertEqual(format_lap_time(92.45), "01:32.450")
        self.assertEqual(format_lap_time(125.008), "02:05.008")
        self.assertEqual(format_lap_time(58.123), "00:58.123")
        self.assertEqual(format_lap_time(0.0), "--:--.---")
        self.assertEqual(format_lap_time(-1.0), "--:--.---")
        self.assertEqual(format_lap_time(999999.0), "--:--.---")

    def test_lap_transition_status_colors(self):
        """Verify status colors, delegated to sector_colors.expected_status (single
        source of truth shared with the live projection and sector splits):
        purple = beats the paddock (other cars) this session, green = beats my own
        session best (no paddock reference beaten), yellow = valid but no
        improvement, grey/default = invalid or nothing to compare against yet."""
        self.engine._track_name = "TestTrack"
        self.engine._track_length = 1000.0
        self.engine.freeze_duration = 3.5

        # Initial state: session best = 90.0s, no paddock (other cars) data yet.
        self.engine._session_best_lap_time = 90.0
        self.engine._all_time_best_lap_time = 90.0
        self.engine._last_laps_completed = 1

        # Case 1: Driver runs 89.5s, beats session best, no paddock reference -> Green
        self.engine._handle_lap_transition(laps_comp=2, last_lap_time=89.5, lap_flag=2, in_garage=False, in_pits=False)
        self.assertEqual(self.engine.last_completed_lap_status, "green")
        self.assertEqual(self.engine.last_completed_lap_time_str, "01:29.500")
        self.assertTrue(self.engine.is_lap_freeze_active)

        # Case 2: Now a paddock (rival) best of 89.0s is known. Session best is
        # 89.5s. Driver runs 88.5s -> beats BOTH paddock and session -> Purple.
        self.engine._session_best_lap_time = 89.5
        self.engine._paddock_known = True
        self.engine._paddock_best_lap = 89.0
        self.engine._handle_lap_transition(laps_comp=3, last_lap_time=88.5, lap_flag=2, in_garage=False, in_pits=False)
        self.assertEqual(self.engine.last_completed_lap_status, "purple")
        self.assertEqual(self.engine.last_completed_lap_time_str, "01:28.500")

        # Case 3: Paddock best is still 89.0s, but session best regressed to 90.0s
        # (e.g. a rival set 89.0s in between). Driver runs 89.5s -> beats their own
        # session best (90.0s) but NOT the paddock (89.0s) -> Green.
        self.engine._session_best_lap_time = 90.0
        self.engine._handle_lap_transition(laps_comp=4, last_lap_time=89.5, lap_flag=2, in_garage=False, in_pits=False)
        self.assertEqual(self.engine.last_completed_lap_status, "green")
        self.assertEqual(self.engine.last_completed_lap_time_str, "01:29.500")

        # Case 4: Session best is 88.5s. Driver runs 91.8s -> Slower / No improvement -> Yellow
        self.engine._session_best_lap_time = 88.5
        self.engine._handle_lap_transition(laps_comp=5, last_lap_time=91.8, lap_flag=2, in_garage=False, in_pits=False)
        self.assertEqual(self.engine.last_completed_lap_status, "yellow")
        self.assertEqual(self.engine.last_completed_lap_time_str, "01:31.800")

        # Case 5: Driver runs 88.0s but cut track (lap_flag = 0) -> Invalid / Grey
        self.engine._handle_lap_transition(laps_comp=6, last_lap_time=88.0, lap_flag=0, in_garage=False, in_pits=False)
        self.assertEqual(self.engine.last_completed_lap_status, "invalid")

    def test_mixed_udp_stream_continuous_delta_and_locked_sectors(self):
        """Verify that delta remains smooth and prior sector deltas remain locked without flickering
        when alternating between TelemInfo (120Hz) and CompactScoring (10Hz)."""
        from simpulse.core.telemetry.reference_profile import ReferenceLapProfile

        track_length = 3000.0
        # Reference: 90 seconds lap, S1 at 1000m (30s), S2 at 2000m (60s), S3 finish at 3000m (90s)
        prof = ReferenceLapProfile(
            track_name="TestTrack",
            vehicle_name="TestCar",
            lap_time=90.0,
            track_length=track_length,
            sector_1_dist=1000.0,
            sector_2_dist=2000.0,
            sector_1_time=30.0,
            sector_2_time=60.0,
            spatial_step=1.0,
            num_points=3001,
            t_grid=[(d / track_length) * 90.0 for d in range(3001)],
        )
        self.engine._track_name = "TestTrack"
        self.engine._vehicle_name = "TestCar"
        self.engine._all_time_best_profile = prof
        self.engine._all_time_best_lap_time = 90.0
        self.engine._apply_active_profile()
        self.assertTrue(self.engine.has_reference)

        lap_start_et = 100.0

        # --- SECTOR 1 ---
        # Driver is running at 33.33 m/s, perfectly on reference pace (lap_start_et = 100.0)
        # Update via physics at 500m (t = 115.0s, elapsed in lap = 15.0s)
        self.engine._last_scoring_dist = 500.0
        self.engine.update_physics(
            veh_speed_ms=33.33,
            elapsed_time=115.0,
            lap_start_et=lap_start_et,
            current_sector=1,
        )
        self.assertAlmostEqual(self.engine.live_delta, 0.0, delta=0.05)
        self.assertEqual(self.engine.current_sector, 1)

        # CompactScoring arrives at 10Hz (has NO player_vehicle)
        compact_scoring = {
            "mTrackName": "TestTrack",
            "mLapDist": 3000.0,
            "mCurrentET": 115.1,
            "mSector": 1,
            "mCountLapFlag": 2,
            "mLastLapTime": -1.0,
            "mTotalLaps": 1,
        }
        self.engine.update_scoring(compact_scoring)
        # Live delta must NOT reset to 0.0 or blink!
        self.assertAlmostEqual(self.engine.live_delta, 0.0, delta=0.05)
        self.assertEqual(self.engine.current_sector, 1)

        # Cross into Sector 2 at 1000m (t = 130.5s -> S1 took 30.5s, reference was 30.0s -> S1 split delta = +0.5s)
        self.engine._last_scoring_dist = 1000.0
        self.engine.update_physics(
            veh_speed_ms=33.33,
            elapsed_time=130.5,
            lap_start_et=lap_start_et,
            current_sector=2,
        )
        self.assertEqual(self.engine.current_sector, 2)
        self.assertTrue(self.engine._s1_captured)
        self.assertAlmostEqual(self.engine.sector1_delta, 0.5, delta=0.05)

        # --- SECTOR 2 ---
        # Now drive in Sector 2 at 1500m (t = 145.5s, delta = +0.5s)
        self.engine._last_scoring_dist = 1500.0
        self.engine.update_physics(
            veh_speed_ms=33.33,
            elapsed_time=145.5,
            lap_start_et=lap_start_et,
            current_sector=2,
        )
        self.assertAlmostEqual(self.engine.live_delta, 0.5, delta=0.05)
        # S1 delta MUST REMAIN EXACTLY LOCKED at 0.5s while in Sector 2 (no flickering!)
        self.assertAlmostEqual(self.engine.sector1_delta, 0.5, delta=0.05)

        # CompactScoring arrives in Sector 2
        compact_scoring["mCurrentET"] = 145.6
        compact_scoring["mSector"] = 2
        self.engine.update_scoring(compact_scoring)
        # S1 delta must NOT flicker or reset
        self.assertAlmostEqual(self.engine.sector1_delta, 0.5, delta=0.05)
        self.assertAlmostEqual(self.engine.live_delta, 0.5, delta=0.05)

        # Cross into Sector 3 at 2000m (t = 161.0s -> S2 split time was 30.5s -> total time = 61.0s, ref = 60.0s -> S2 delta = +0.5s)
        self.engine._last_scoring_dist = 2000.0
        self.engine.update_physics(
            veh_speed_ms=33.33,
            elapsed_time=161.0,
            lap_start_et=lap_start_et,
            current_sector=3,
        )
        self.assertEqual(self.engine.current_sector, 3)
        self.assertTrue(self.engine._s2_captured)
        self.assertAlmostEqual(self.engine.sector1_delta, 0.5, delta=0.05)
        self.assertAlmostEqual(self.engine.sector2_delta, 0.5, delta=0.05)

        # --- SECTOR 3 ---
        # Drive in Sector 3 at 2500m (t = 176.0s)
        self.engine._last_scoring_dist = 2500.0
        self.engine.update_physics(
            veh_speed_ms=33.33,
            elapsed_time=176.0,
            lap_start_et=lap_start_et,
            current_sector=3,
        )
        # In Sector 3: both S1 and S2 deltas MUST STAY LOCKED (no flickering!)
        self.assertAlmostEqual(self.engine.sector1_delta, 0.5, delta=0.05)
        self.assertAlmostEqual(self.engine.sector2_delta, 0.5, delta=0.05)
        self.assertAlmostEqual(self.engine.live_delta, 1.0, delta=0.05)

        # CompactScoring in Sector 3
        compact_scoring["mCurrentET"] = 176.1
        compact_scoring["mSector"] = 3
        self.engine.update_scoring(compact_scoring)
        self.assertAlmostEqual(self.engine.sector1_delta, 0.5, delta=0.05)
        self.assertAlmostEqual(self.engine.sector2_delta, 0.5, delta=0.05)
        self.assertAlmostEqual(self.engine.live_delta, 1.0, delta=0.05)


class TestUpdateScoringFromView(unittest.TestCase):
    """update_scoring_from_view() must reproduce update_scoring()'s exact behaviour when
    fed the View-typed equivalent of the same packet — Phase 2 of the SRP telemetry
    refactor (engines consume TelemetryStateStore.timing/.grid instead of re-parsing
    the raw packet). Both callers share the same core (_apply_scoring_update); these
    tests lock the two field-extraction paths (CompactScoring<->BaseTimingState-only,
    FullScoringSession<->FullGridScoringState) against each other.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_ref_dir = delta_engine_module._REF_LAPS_DIR
        delta_engine_module._REF_LAPS_DIR = Path(self.temp_dir)

    def tearDown(self):
        delta_engine_module._REF_LAPS_DIR = self.original_ref_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @staticmethod
    def _state(eng):
        return (
            eng.current_sector,
            round(eng.live_delta, 6),
            round(eng.sector1_delta, 6),
            round(eng.sector2_delta, 6),
            eng._last_laps_completed,
        )

    def test_compact_equivalent_matches_raw_compact_scoring(self):
        """grid=None path (BaseTimingState only) must match feeding the equivalent
        CompactScoring packet directly — including the dead-reckoned player_dist
        CompactScoring never carries (kept in sync manually here, exactly like the
        engine's own 100Hz update_physics would)."""
        from isimotor_rawudp_client import CompactScoring
        from simpulse_sdk.models.scoring import BaseTimingState

        raw_engine = DeltaEngine()
        view_engine = DeltaEngine()
        raw_engine._vehicle_name = view_engine._vehicle_name = "TestCar"
        raw_engine._vehicle_class = view_engine._vehicle_class = "GT3"

        def compact(sec):
            return CompactScoring(
                track_name="TestTrack", lap_dist=5000.0, current_et=13.0,
                total_laps=2, sector=sec, count_lap_flag=2, in_garage_stall=False,
                last_lap_time=100.0, cur_sector1=0.0, cur_sector2=0.0,
                last_sector1=30.0, last_sector2=75.0, best_sector1=19.0,
                best_sector2=37.5, best_lap_time=55.0,
            )

        def timing(sec):
            return BaseTimingState(
                track_name="TestTrack", track_length=5000.0, current_et=13.0,
                total_laps=2, sector=sec, count_lap_flag=2, in_garage=False,
                last_lap_time=100.0, cur_sector1=0.0, cur_sector2=0.0,
                last_sector1=30.0, last_sector2=75.0, best_sector1=19.0,
                best_sector2=37.5, best_lap_time=55.0,
            )

        for sec, dist in ((1, 200.0), (2, 1800.0), (3, 4900.0)):
            raw_engine._last_scoring_dist = dist
            view_engine._last_scoring_dist = dist
            raw_engine.update_scoring(compact(sec))
            view_engine.update_scoring_from_view(timing(sec), None)
            self.assertEqual(self._state(raw_engine), self._state(view_engine))
        self.assertEqual(raw_engine.current_sector, 3)

    def test_full_equivalent_matches_raw_full_scoring_with_paddock(self):
        """grid path (FullGridScoringState) must match feeding the equivalent
        FullScoringSession directly, including the paddock/session-bests scan over
        grid.vehicles (typed VehicleScoring, no dict branch involved)."""
        from isimotor_rawudp_client import FullScoringSession, VehicleScoring
        from simpulse_sdk.models.scoring import BaseTimingState, FullGridScoringState

        player = VehicleScoring(
            id=1, is_player=True, vehicle_name="Me", vehicle_class="GT3",
            total_laps=1, sector=2, count_lap_flag=2, lap_dist=100.0,
            time_into_lap=1.0, cur_sector1=9.5, cur_sector2=0.0,
            last_sector1=20.0, last_sector2=50.0, last_lap_time=40.0,
            best_sector1=19.0, best_sector2=49.0, best_lap_time=60.0,
        )
        rival = VehicleScoring(
            id=2, is_player=False, control=1, vehicle_name="Riv", vehicle_class="GT3",
            total_laps=3, sector=2, count_lap_flag=2, lap_dist=100.0,
            time_into_lap=1.0, cur_sector1=0.0, cur_sector2=0.0,
            last_sector1=10.0, last_sector2=30.0, last_lap_time=40.0,
            best_sector1=10.0, best_sector2=30.0, best_lap_time=40.0,
        )

        raw_engine = DeltaEngine()
        view_engine = DeltaEngine()

        session = FullScoringSession(
            track_name="T1", lap_dist=3000.0, current_et=1.0, vehicles=[player, rival],
        )
        raw_engine.update_scoring(session)

        common = dict(
            track_name="T1", track_length=3000.0, current_et=1.0, total_laps=1, sector=2,
            in_garage=False, count_lap_flag=2, cur_sector1=9.5, cur_sector2=0.0,
            last_sector1=20.0, last_sector2=50.0, last_lap_time=40.0, best_sector1=19.0,
            best_sector2=49.0, best_lap_time=60.0,
        )
        grid = FullGridScoringState(
            **common, vehicle_name="Me", vehicle_class="GT3", in_pits=False,
            lap_start_et=0.0, time_into_lap=1.0, car_lap_dist=100.0,
            vehicles=[player, rival],
        )
        view_engine.update_scoring_from_view(BaseTimingState(**common), grid)

        self.assertEqual(self._state(raw_engine), self._state(view_engine))
        self.assertEqual(raw_engine._paddock_cum_s1, view_engine._paddock_cum_s1)
        self.assertEqual(raw_engine._paddock_cum_s1, 10.0)
        self.assertEqual(raw_engine._last_sector1_status, view_engine._last_sector1_status)
        self.assertEqual(raw_engine._last_sector1_status, "purple")


class TestTrackChangeClearsStalePosition(unittest.TestCase):
    """A track/vehicle change must not leave _last_scoring_dist/
    _last_scoring_time_into holding the PREVIOUS track's position — otherwise
    _load_reference_profile() -> _apply_active_profile() computes (or clears
    sector deltas against) a delta using cross-track distance/time, right at
    every track change."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_ref_dir = delta_engine_module._REF_LAPS_DIR
        delta_engine_module._REF_LAPS_DIR = Path(self.temp_dir)

    def tearDown(self):
        delta_engine_module._REF_LAPS_DIR = self.original_ref_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_stale_position_cleared_on_track_change(self):
        eng = DeltaEngine()
        eng._apply_scoring_update(
            now=0.0, track_name="TrackA", track_len=1000.0, current_et=0.0,
            veh_name="Car", veh_class="GT3", laps_comp=0,
            lap_start_et=0.0, time_into_lap=0.0, player_dist=0.0,
            raw_sec=1, in_garage=False, in_pits=False, lap_flag=2,
            last_lap_time=0.0, cur_s1=0.0, cur_s2=0.0, last_s1=0.0, last_s2=0.0,
            best_s1=0.0, best_s2=0.0, best_lap=0.0, vehicles_src=[],
        )
        # Drive out on TrackA, well past the origin.
        eng._apply_scoring_update(
            now=1.0, track_name="TrackA", track_len=1000.0, current_et=25.0,
            veh_name="Car", veh_class="GT3", laps_comp=0,
            lap_start_et=0.0, time_into_lap=25.0, player_dist=500.0,
            raw_sec=2, in_garage=False, in_pits=False, lap_flag=2,
            last_lap_time=0.0, cur_s1=0.0, cur_s2=0.0, last_s1=0.0, last_s2=0.0,
            best_s1=0.0, best_s2=0.0, best_lap=0.0, vehicles_src=[],
        )
        self.assertEqual(eng._last_scoring_dist, 500.0)
        self.assertEqual(eng._last_scoring_time_into, 25.0)

        # Spy on _calculate_delta to prove _apply_active_profile() (called
        # synchronously inside the track-change handling below, well before
        # this function's own end-of-call position update) never sees
        # TrackA's stale (500.0, 25.0) position while switching to TrackB.
        seen_calls = []
        original_calculate_delta = eng._calculate_delta
        eng._calculate_delta = lambda dist, t: (seen_calls.append((dist, t)), original_calculate_delta(dist, t))[1]

        # Change track — must reset the stale position, not carry it over.
        eng._apply_scoring_update(
            now=2.0, track_name="TrackB", track_len=2000.0, current_et=0.0,
            veh_name="Car", veh_class="GT3", laps_comp=0,
            lap_start_et=0.0, time_into_lap=0.0, player_dist=0.0,
            raw_sec=1, in_garage=False, in_pits=False, lap_flag=2,
            last_lap_time=0.0, cur_s1=0.0, cur_s2=0.0, last_s1=0.0, last_s2=0.0,
            best_s1=0.0, best_s2=0.0, best_lap=0.0, vehicles_src=[],
        )
        self.assertNotIn((500.0, 25.0), seen_calls, "TrackA's stale position leaked into TrackB's delta calc")
        self.assertEqual(eng._last_scoring_dist, 0.0)
        self.assertEqual(eng._last_scoring_time_into, 0.0)
        self.assertEqual(eng.live_delta, 0.0)


class TestLiveDeltaSurvivesInvalidLap(unittest.TestCase):
    """Live delta/expected must keep updating during an invalidated lap
    (lap_flag != 2, e.g. a track-limits cut) — the driver has separate
    visual/audio invalid-lap indicators elsewhere, so freezing/blanking the
    live number too is an unwanted redundant one. Only pits/garage (where
    there's genuinely no meaningful delta) should still zero it."""

    def setUp(self):
        self.engine = DeltaEngine()
        self.engine._apply_scoring_update(
            now=0.0, track_name="T1", track_len=1000.0, current_et=0.0,
            veh_name="Car", veh_class="GT3", laps_comp=0,
            lap_start_et=0.0, time_into_lap=0.0, player_dist=0.0,
            raw_sec=1, in_garage=False, in_pits=False, lap_flag=2,
            last_lap_time=0.0, cur_s1=0.0, cur_s2=0.0, last_s1=0.0, last_s2=0.0,
            best_s1=0.0, best_s2=0.0, best_lap=0.0, vehicles_src=[],
        )
        self.engine._ref_lap_time = 50.0
        self.engine._ref_spatial_step = 1.0
        self.engine._ref_t_grid = [(d / 1000.0) * 50.0 for d in range(1001)]
        self.engine._ref_num_points = 1001

    def _update(self, **overrides):
        base = dict(
            now=1.0, track_name="T1", track_len=1000.0, current_et=45.0,
            veh_name="Car", veh_class="GT3", laps_comp=0,
            lap_start_et=0.0, time_into_lap=45.0, player_dist=200.0,
            raw_sec=1, in_garage=False, in_pits=False, lap_flag=1,
            last_lap_time=0.0, cur_s1=0.0, cur_s2=0.0, last_s1=0.0, last_s2=0.0,
            best_s1=0.0, best_s2=0.0, best_lap=0.0, vehicles_src=[],
        )
        base.update(overrides)
        self.engine._apply_scoring_update(**base)

    def test_invalidated_lap_keeps_live_delta(self):
        # dist=200m -> ref_time=10.0s; actual time_into=45.0s -> delta=+35.0s,
        # same as test_slow_driving_delta_explodes_positive, but lap_flag=1
        # (invalidated) instead of 2 (valid).
        self._update(lap_flag=1)
        self.assertAlmostEqual(self.engine.live_delta, 35.0)

    def test_pits_still_zero_live_delta(self):
        self._update(lap_flag=1, in_pits=True)
        self.assertEqual(self.engine.live_delta, 0.0)

    def test_garage_still_zero_live_delta(self):
        self._update(lap_flag=1, in_garage=True)
        self.assertEqual(self.engine.live_delta, 0.0)

    def test_update_physics_also_keeps_live_delta_during_invalid_lap(self):
        """Same gating fix on the 100Hz physics path (update_physics), not
        just the scoring path (_apply_scoring_update)."""
        self._update(lap_flag=1)
        self.assertAlmostEqual(self.engine.live_delta, 35.0)
        # A subsequent 100Hz physics tick (no new scoring packet) must not
        # zero it back out just because the last known lap_flag was 1.
        self.engine.update_physics(
            veh_speed_ms=50.0, dt=0.01, elapsed_time=45.01, lap_start_et=0.0, current_sector=1,
        )
        self.assertGreater(self.engine.live_delta, 0.0)


class TestGarageResetsSectorTracking(unittest.TestCase):
    """Entering the garage must not leave current_sector reporting S2/S3 from
    before — the driver can re-emerge anywhere, so there's no valid position
    to keep. See _apply_scoring_update's `if in_garage:` block."""

    def _update(self, **overrides):
        base = dict(
            now=0.0, track_name="T1", track_len=1000.0, current_et=0.0,
            veh_name="Car", veh_class="GT3", laps_comp=0,
            lap_start_et=0.0, time_into_lap=0.0, player_dist=0.0,
            raw_sec=1, in_garage=False, in_pits=False, lap_flag=2,
            last_lap_time=0.0, cur_s1=0.0, cur_s2=0.0, last_s1=0.0, last_s2=0.0,
            best_s1=0.0, best_s2=0.0, best_lap=0.0, vehicles_src=[],
        )
        base.update(overrides)
        self.engine._apply_scoring_update(**base)

    def setUp(self):
        self.engine = DeltaEngine()
        self._update(raw_sec=1)
        self._update(now=1.0, current_et=40.0, time_into_lap=40.0, player_dist=400.0, raw_sec=2)
        self._update(now=2.0, current_et=80.0, time_into_lap=80.0, player_dist=800.0, raw_sec=3)
        self.assertEqual(self.engine.current_sector, 3)

    def test_garage_entry_resets_to_sector_1(self):
        self._update(now=3.0, raw_sec=3, in_garage=True, in_pits=True)
        self.assertEqual(self.engine.current_sector, 1)

    def test_garage_stays_reset_across_multiple_packets(self):
        """A stale raw_sec reported repeatedly while parked must not re-lock
        the tracking back onto it."""
        self._update(now=3.0, raw_sec=3, in_garage=True, in_pits=True)
        self._update(now=4.0, raw_sec=3, in_garage=True, in_pits=True)
        self._update(now=5.0, raw_sec=3, in_garage=True, in_pits=True)
        self.assertEqual(self.engine.current_sector, 1)

    def test_exiting_garage_reprimes_cleanly(self):
        self._update(now=3.0, raw_sec=3, in_garage=True, in_pits=True)
        # Drive back out, reporting S1 again for the new lap.
        self._update(now=4.0, current_et=1.0, time_into_lap=1.0, player_dist=10.0,
                     raw_sec=1, in_garage=False, in_pits=False)
        self.assertEqual(self.engine.current_sector, 1)


if __name__ == "__main__":
    unittest.main()

