"""
Unit tests for WallOfFameEngine in isolation — see TIME_STATUS_SPEC.md.
"""
import unittest

from simpulse.core.telemetry.wall_of_fame_engine import WallOfFameEngine
from simpulse_sdk.models.timing import TimeLap


class _Profile:
    """Minimal stand-in for ReferenceLapProfile (only the fields
    load_all_time_from_disk reads)."""
    def __init__(self, sector_1_time, sector_2_time, lap_time):
        self.sector_1_time = sector_1_time
        self.sector_2_time = sector_2_time
        self.lap_time = lap_time


class TestAllTimeBest(unittest.TestCase):
    def test_no_profile_clears_all_time(self):
        eng = WallOfFameEngine()
        eng.load_all_time_from_disk(_Profile(30.0, 60.0, 90.0))
        self.assertTrue(eng.snapshot().my_best_all_time.is_valid)
        eng.load_all_time_from_disk(None)
        self.assertFalse(eng.snapshot().my_best_all_time.is_valid)

    def test_profile_decomposed_into_standalone_splits(self):
        eng = WallOfFameEngine()
        eng.load_all_time_from_disk(_Profile(sector_1_time=30.0, sector_2_time=65.0, lap_time=95.0))
        lap = eng.snapshot().my_best_all_time
        self.assertEqual(lap.sector1, 30.0)
        self.assertEqual(lap.sector2, 35.0)
        self.assertEqual(lap.sector3, 30.0)
        self.assertEqual(lap.total, 95.0)


class TestMySessionBest(unittest.TestCase):
    def test_lap_completed_updates_session_best_if_better(self):
        eng = WallOfFameEngine()
        eng.update_from_lap_completed(TimeLap(sector1=30, sector2=30, sector3=30, total=90.0), is_valid=True)
        self.assertEqual(eng.snapshot().my_best_session.total, 90.0)
        # Slower lap does not overwrite.
        eng.update_from_lap_completed(TimeLap(total=95.0), is_valid=True)
        self.assertEqual(eng.snapshot().my_best_session.total, 90.0)
        # Faster lap does overwrite.
        eng.update_from_lap_completed(TimeLap(sector1=29, sector2=29, sector3=29, total=87.0), is_valid=True)
        self.assertEqual(eng.snapshot().my_best_session.total, 87.0)

    def test_invalid_lap_ignored(self):
        eng = WallOfFameEngine()
        eng.update_from_lap_completed(TimeLap(total=90.0), is_valid=False)
        self.assertFalse(eng.snapshot().my_best_session.is_valid)

    def test_game_reported_total_tighter_than_our_capture_wins(self):
        """The game's own bestLapTime report is authoritative and always
        available once a timed lap is set — it must win even when our own
        capture pipeline missed a faster lap (see WallOfFameEngine docstring:
        the historical _session_lap_bound "tighter of the two" rule)."""
        eng = WallOfFameEngine()
        eng.update_from_lap_completed(TimeLap(sector1=31, sector2=31, sector3=31, total=93.0), is_valid=True)
        eng.update_from_scoring(game_best_lap_time=90.0, vehicles_src=[])
        self.assertEqual(eng.snapshot().my_best_session.total, 90.0)

    def test_our_capture_wins_when_tighter_than_game_report(self):
        eng = WallOfFameEngine()
        eng.update_from_lap_completed(TimeLap(sector1=29, sector2=29, sector3=29, total=87.0), is_valid=True)
        eng.update_from_scoring(game_best_lap_time=90.0, vehicles_src=[])
        self.assertEqual(eng.snapshot().my_best_session.total, 87.0)

    def test_reset_session_clears_everything(self):
        eng = WallOfFameEngine()
        eng.load_all_time_from_disk(_Profile(30.0, 60.0, 90.0))
        eng.update_from_lap_completed(TimeLap(total=90.0), is_valid=True)
        eng.update_from_scoring(game_best_lap_time=91.0, vehicles_src=[])
        eng.reset_session()
        snap = eng.snapshot()
        self.assertFalse(snap.my_best_all_time.is_valid)
        self.assertFalse(snap.my_best_session.is_valid)
        self.assertFalse(snap.paddock_session_best.is_valid)


class TestPaddockSessionBest(unittest.TestCase):
    """Player-exclusion filter (_is_player) — a rival's own best split/lap
    must never count as "the paddock", and the player's own bests must never
    leak into paddock_session_best."""

    def _vehicles(self, player_best_lap, rival_best_lap):
        player = {"mIsPlayer": True, "mBestSector1": 30.0, "mBestSector2": 60.0, "mBestLapTime": player_best_lap}
        rival = {"mIsPlayer": False, "mBestSector1": 29.0, "mBestSector2": 58.0, "mBestLapTime": rival_best_lap}
        return [player, rival]

    def test_excludes_player_own_best(self):
        eng = WallOfFameEngine()
        eng.update_from_scoring(game_best_lap_time=0.0, vehicles_src=self._vehicles(85.0, 89.0))
        paddock = eng.snapshot().paddock_session_best
        self.assertEqual(paddock.total, 89.0)   # the rival's, not the player's 85.0
        self.assertEqual(paddock.sector1, 29.0)
        self.assertEqual(paddock.sector2, 29.0)  # 58 - 29
        self.assertEqual(paddock.sector3, 31.0)  # 89 - 58

    def test_multiple_rivals_takes_min(self):
        eng = WallOfFameEngine()
        vehicles = [
            {"mIsPlayer": True, "mBestLapTime": 80.0},
            {"mIsPlayer": False, "mBestLapTime": 92.0},
            {"mIsPlayer": False, "mBestLapTime": 88.0},
        ]
        eng.update_from_scoring(game_best_lap_time=0.0, vehicles_src=vehicles)
        self.assertEqual(eng.snapshot().paddock_session_best.total, 88.0)

    def test_empty_vehicles_leaves_paddock_unknown(self):
        eng = WallOfFameEngine()
        eng.update_from_scoring(game_best_lap_time=90.0, vehicles_src=[])
        self.assertFalse(eng.snapshot().paddock_session_best.is_valid)

    def test_typed_scoring_vehicle_objects(self):
        """The non-dict branch requires the real isimotor_rawudp_client.VehicleScoring
        interface (is_player/control/best_sector1/best_sector2/best_lap_time
        are real, always-present fields — no getattr fallback)."""
        from isimotor_rawudp_client import VehicleScoring

        eng = WallOfFameEngine()
        eng.update_from_scoring(
            game_best_lap_time=0.0,
            vehicles_src=[
                VehicleScoring(id=1, is_player=True, control=0, best_sector1=30.0, best_sector2=60.0, best_lap_time=85.0),
                VehicleScoring(id=2, is_player=False, control=1, best_sector1=29.0, best_sector2=58.0, best_lap_time=89.0),
            ],
        )
        self.assertEqual(eng.snapshot().paddock_session_best.total, 89.0)


if __name__ == "__main__":
    unittest.main()
