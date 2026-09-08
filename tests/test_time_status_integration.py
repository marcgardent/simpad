"""
Cross-check: DeltaEngine.time_status and the legacy expected_*/sector*_status
properties compute the same underlying truth through two different paths
during the TIME_STATUS_SPEC.md migration (Step 2's "bonus" consistency test).
"""
import unittest

from simpulse.core.telemetry.delta_engine import DeltaEngine
from simpulse.core.telemetry.reference_profile import ReferenceLapProfile
from simpulse_sdk.models.timing import TimeLap, TimeTarget


class TestTimeStatusMatchesLegacyLap(unittest.TestCase):
    def test_lap_target_and_pr_flag(self):
        eng = DeltaEngine()
        eng._ref_lap_time = 100.0
        eng._ref_t_grid = [float(i) for i in range(101)]
        eng._ref_num_points = 101
        eng._ref_spatial_step = 1.0
        eng._live_delta = -2.0                  # projected 98.0
        eng._all_time_best_profile = ReferenceLapProfile(lap_time=99.0)
        eng._all_time_best_lap_time = 99.0
        eng._wall_of_fame.load_all_time_from_disk(eng._all_time_best_profile)
        eng._session_best_lap_time = 100.0
        eng._wall_of_fame.update_from_lap_completed(TimeLap(total=100.0), is_valid=True)
        eng._paddock_known = True
        eng._paddock_best_lap = 99.5
        eng._wall_of_fame.update_from_scoring(game_best_lap_time=0.0, vehicles_src=[
            {"mIsPlayer": False, "mBestLapTime": 99.5},
        ])
        eng._last_lap_flag = 2

        status = eng.time_status
        self.assertEqual(eng.expected_lap_status, "purple")
        self.assertEqual(status.lap.target, TimeTarget.PADDOCK)
        self.assertTrue(eng.expected_lap_is_pr)
        self.assertTrue(status.lap.is_personal_record_target)
        self.assertAlmostEqual(status.lap.expected_time, eng.estimated_lap_time)
        # wall_of_fame carries the raw reference clocks (independent of the
        # live projection) — what my_session_best_lap_time_str/
        # session_best_lap_time_str used to expose as plain strings.
        self.assertEqual(status.wall_of_fame.my_best_session.total_str, eng.my_session_best_lap_time_str)
        self.assertEqual(status.wall_of_fame.paddock_session_best.total_str, eng.session_best_lap_time_str)


class TestTimeStatusMatchesLegacySector(unittest.TestCase):
    def test_sector1_target_and_pr_flag(self):
        eng = DeltaEngine()
        eng._current_profile = ReferenceLapProfile(lap_time=100.0, sector_1_time=30.0, sector_2_time=60.0)
        eng._all_time_best_profile = ReferenceLapProfile(lap_time=99.0, sector_1_time=29.0, sector_2_time=60.0)
        eng._wall_of_fame.load_all_time_from_disk(eng._all_time_best_profile)
        eng._paddock_known = True
        eng._paddock_cum_s1 = 29.5
        eng._paddock_cum_s2 = 60.0
        eng._paddock_best_lap = 100.0
        eng._wall_of_fame.update_from_scoring(game_best_lap_time=0.0, vehicles_src=[
            {"mIsPlayer": False, "mBestSector1": 29.5, "mBestSector2": 60.0, "mBestLapTime": 100.0},
        ])
        eng._ref_t_grid = [float(i) for i in range(101)]
        eng._ref_num_points = 101
        eng._sector1_delta = -1.5   # projected S1 = 30.0 - 1.5 = 28.5

        status = eng.time_status
        self.assertEqual(eng.expected_sector1_status, "purple")
        self.assertEqual(status.sector1.target, TimeTarget.PADDOCK)
        self.assertTrue(eng.expected_sector1_is_pr)
        self.assertTrue(status.sector1.is_personal_record_target)


class TestFrozenLapBadge(unittest.TestCase):
    """The frozen lap badge (right after crossing the line, held for
    freeze_duration) must resolve target/PR against WallOfFameTimes as it
    stood BEFORE this lap updated it — not the live, continuously-recomputed
    projection, which would self-compare a brand-new best against itself and
    report it as merely equalled, never beaten."""

    def test_new_all_time_best_is_pr_during_freeze(self):
        eng = DeltaEngine()
        eng._all_time_best_lap_time = 100.0
        eng._wall_of_fame.load_all_time_from_disk(ReferenceLapProfile(lap_time=100.0))
        eng._handle_lap_transition(laps_comp=0, last_lap_time=0.0, lap_flag=2, in_garage=False, in_pits=False, current_et=0.0)

        # Enough clean spatial samples for _finalize_completed_lap to actually
        # accept & record the lap (>=10 pts, monotonic distance).
        eng._current_lap_samples = [
            (float(d), float(d) * 95.0 / 1000.0, 50.0, 1.0, 0.0, 0.0, 4) for d in range(0, 1100, 100)
        ]

        # New lap: 95.0s, beats the 100.0s all-time best.
        eng._live_delta = -5.0
        eng._handle_lap_transition(laps_comp=1, last_lap_time=95.0, lap_flag=2, in_garage=False, in_pits=False, current_et=95.0)

        # WallOfFameEngine has ALREADY absorbed this lap as the new all-time
        # best (_finalize_completed_lap -> update_from_lap_completed ran
        # inside the transition above) — a naive live re-projection would now
        # compare 95.0 against ever=95.0 and report is_personal_record_target
        # False. The frozen badge must not.
        self.assertTrue(eng._wall_of_fame.snapshot().my_best_all_time.is_valid)
        self.assertEqual(eng._wall_of_fame.snapshot().my_best_all_time.total, 95.0)
        self.assertTrue(eng.is_lap_freeze_active)
        status = eng.time_status
        self.assertTrue(status.lap.is_personal_record_target)
        self.assertEqual(status.lap.expected_time, 95.0)

    def test_invalid_lap_never_pr_during_freeze(self):
        eng = DeltaEngine()
        eng._all_time_best_lap_time = 100.0
        eng._wall_of_fame.load_all_time_from_disk(ReferenceLapProfile(lap_time=100.0))
        eng._handle_lap_transition(laps_comp=0, last_lap_time=0.0, lap_flag=2, in_garage=False, in_pits=False, current_et=0.0)
        eng._handle_lap_transition(laps_comp=1, last_lap_time=95.0, lap_flag=1, in_garage=False, in_pits=True, current_et=95.0)

        self.assertEqual(eng.time_status.lap.target, TimeTarget.NONE)
        self.assertFalse(eng.time_status.lap.is_personal_record_target)


if __name__ == "__main__":
    unittest.main()
