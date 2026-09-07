"""
Unit tests for LMU Race Control cut advantage / time debt calculation and 5Hz diagnostic logging.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from simpulse.core.telemetry.delta_engine import DeltaEngine
from simpulse.core.telemetry.reference_profile import ReferenceLapProfile
from simpulse.core.telemetry.track_limits_logger import TrackLimitsLogger
from simpulse.core.reference_lap import ReferenceLapManager


class TestTrackLimitsCutDebt(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.temp_dir, "track_limits_debug.log")
        self.logger = TrackLimitsLogger(log_path=self.log_path, enabled=True)
        self.engine = DeltaEngine()

    def tearDown(self):
        ReferenceLapManager.get_instance().delta_engine.reset_session()
        shutil.rmtree(self.temp_dir, ignore_errors=True)



    def test_no_compact_scoring_distance_jumping(self):
        """Verify that CompactScoring packets (where lap_dist=5781m is track length) do not corrupt car distance."""
        from isimotor_rawudp_client import CompactScoring, FullScoringSession, VehicleScoring, TelemInfo

        rlm = ReferenceLapManager.get_instance()
        de = rlm.delta_engine

        # Setup reference profile on 5781m track (Monza)
        prof = ReferenceLapProfile(
            track_name="Monza",
            lap_time=95.0,
            track_length=5781.0,
            spatial_step=1.0,
            num_points=5782,
            t_grid=[(d / 5781.0) * 95.0 for d in range(5782)],
        )
        de._all_time_best_profile = prof
        de._all_time_best_lap_time = 95.0
        de._track_length = 5781.0
        de._apply_active_profile()

        # 1. FullScoring arrives: car is at dist=935m.
        v = VehicleScoring(is_player=1, lap_dist=935.0, time_into_lap=15.0, count_lap_flag=1, total_laps=3, sector=1)
        session = FullScoringSession(lap_dist=5781.0, track_name="Monza", vehicles=[v])
        rlm.update_scoring(session)
        self.assertEqual(de.last_scoring_dist, 935.0)

        # 2. CompactScoring arrives with lap_dist=5781.0m (track length)
        compact = CompactScoring(lap_dist=5781.0, count_lap_flag=1, total_laps=3, sector=1, current_et=120.0)
        rlm.update_scoring(compact)

        # DeltaEngine last_scoring_dist MUST STILL BE 935.0m (NOT 5781.0m!)
        self.assertEqual(de.last_scoring_dist, 935.0)

        # 3. TelemInfo arrives: advances 10m at 50 m/s with dt=0.2s
        from isimotor_rawudp_client.models.common import TelemVect3
        telem = TelemInfo(local_vel=TelemVect3(x=0.0, y=0.0, z=50.0), delta_time=0.2, elapsed_time=120.2, lap_start_et=105.0)
        rlm.update_physics(
            veh_speed_ms=float(telem.speed_mps),
            dt=float(telem.delta_time),
            elapsed_time=float(telem.elapsed_time),
            lap_start_et=float(telem.lap_start_et),
        )

        # Distance smoothly advances by 50 * 0.2 = 10m -> 945.0m!
        self.assertAlmostEqual(de.last_scoring_dist, 945.0, delta=0.1)

    def test_event_driven_surface_on_off_track_logging(self):
        """Verify that leaving the road and returning to the track logs strictly on state transitions."""
        self.logger.reset_log_file(self.log_path)

        # 1. Car is on track (initial frame) -> No spam on clean initial state
        self.logger.log_surface_event(
            source="TelemInfo(120Hz)",
            is_on_track=True,
            wheels_on_track=4,
            surface_types=(0, 0, 0, 0),
            terrain_names=("ROAD", "ROAD", "ROAD", "ROAD"),
        )
        with open(self.log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        self.assertEqual(len([l for l in lines if "[OFF_TRACK" in l or "[TRACK_REJOIN" in l]), 0)

        # 2. Car runs wide into grass/gravel -> OFF_TRACK logged
        self.logger.log_surface_event(
            source="TelemInfo(120Hz)",
            is_on_track=False,
            wheels_on_track=0,
            surface_types=(2, 2, 4, 4),
            terrain_names=("GRAS", "GRAS", "GRAV", "GRAV"),
        )
        with open(self.log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        off_track_lines = [l for l in lines if "[OFF_TRACK" in l]
        self.assertEqual(len(off_track_lines), 1)
        self.assertIn("OFF-ROAD (Grass/Gravel)", off_track_lines[0])
        self.assertIn("ORANGE", off_track_lines[0])

        # 3. Repeated frames while staying in grass -> NO duplicate lines (strictly event driven)
        for _ in range(50):
            self.logger.log_surface_event(
                source="TelemInfo(120Hz)",
                is_on_track=False,
                wheels_on_track=0,
                surface_types=(2, 2, 4, 4),
            )
        with open(self.log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        self.assertEqual(len([l for l in lines if "[OFF_TRACK" in l]), 1)

        # 4. Car re-enters the track -> TRACK_REJOIN logged
        self.logger.log_surface_event(
            source="TelemInfo(120Hz)",
            is_on_track=True,
            wheels_on_track=4,
            surface_types=(0, 0, 0, 0),
            terrain_names=("ROAD", "ROAD", "ROAD", "ROAD"),
        )
        with open(self.log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        rejoin_lines = [l for l in lines if "[TRACK_REJOIN" in l]
        self.assertEqual(len(rejoin_lines), 1)
        self.assertIn("ON-TRACK", rejoin_lines[0])
        self.assertIn("4/4 on road", rejoin_lines[0])
        self.assertIn("GREEN", rejoin_lines[0])


if __name__ == "__main__":
    unittest.main()
