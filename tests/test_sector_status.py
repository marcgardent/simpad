"""
Unit tests for sector status calculations, non-realtime sensor telemetry retention, and sector delta formatting.
"""

import unittest
from simpulse.core.telemetry.sensors import VehicleSensors
from simpulse.core.telemetry.lmu_parser import LMUParser


class TestSectorStatusCalculations(unittest.TestCase):

    def test_sensors_retains_session_telemetry_when_not_in_realtime(self):
        """Verify VehicleSensors retains session telemetry when in_realtime is False."""
        sensors = VehicleSensors.from_wheel_velocities(
            long_patch_vels=(0.0, 0.0, 0.0, 0.0),
            long_ground_vels=(0.0, 0.0, 0.0, 0.0),
            lat_patch_vels=(0.0, 0.0, 0.0, 0.0),
            in_realtime=False,
            gear=1,
            fuel_level=45.5,
            remaining_laps=12,
            delta_time=-0.250,
            sector1_time="31.250",
            sector1_status="purple",
            sector2_time="42.100",
            sector2_status="green",
            sector3_time="28.900",
            sector3_status="default",
            current_sector=2,
        )

        self.assertFalse(sensors.in_realtime)
        self.assertEqual(sensors.fuel_level, 45.5)
        self.assertEqual(sensors.remaining_laps, 12)
        self.assertEqual(sensors.delta_time, -0.250)
        self.assertEqual(sensors.sector1_time, "31.250")
        self.assertEqual(sensors.sector1_status, "purple")
        self.assertEqual(sensors.sector2_time, "42.100")
        self.assertEqual(sensors.sector2_status, "green")
        self.assertEqual(sensors.sector3_time, "28.900")
        self.assertEqual(sensors.sector3_status, "default")
        self.assertEqual(sensors.current_sector, 2)

    def test_lmu_parser_last_sector_status_calculation(self):
        """Verify LMUParser calculates sector status (purple, green, default) for last_s1 and last_s2."""
        from isimotor_rawudp_client import VehicleScoring

        session_bests = (30.0, 40.0, 25.0)  # S1 best = 30.0, S2 indiv best = 40.0, S3 indiv best = 25.0

        player_veh = VehicleScoring(
            cur_sector1=-1.0,
            last_sector1=30.0,  # Personal & Session best!
            best_sector1=30.0,
            cur_sector2=-1.0,
            last_sector2=70.0,  # indiv S2 = 70 - 30 = 40.0 (Personal & Session best!)
            best_sector2=70.0,
            last_lap_time=95.0,  # indiv S3 = 95 - 70 = 25.0 (Personal & Session best!)
            best_lap_time=95.0,
        )

        LMUParser._update_player_sector_times_from_model(player_veh, session_bests)

        self.assertEqual(LMUParser._last_sector1_time, "00:30.000")
        self.assertEqual(LMUParser._last_sector1_status, "pink")   # session == personal (no rival gap)

        self.assertEqual(LMUParser._last_sector2_time, "00:40.000")
        self.assertEqual(LMUParser._last_sector2_status, "pink")

        self.assertEqual(LMUParser._last_sector3_time, "00:25.000")
        self.assertEqual(LMUParser._last_sector3_status, "pink")

    def test_sector_delta_str_zero_delta(self):
        """Verify sector_delta_str formats zero delta (+0.000) when active session reference exists."""
        sensors = VehicleSensors(
            sector1_delta=0.0,
            delta_time=-0.120,
            sector1_time="30.500",
        )
        self.assertEqual(sensors.sector_delta_str(1), "+0.000")

    def test_telemetry_does_not_corrupt_scoring_sector(self):
        """Verify TelemInfo with uninitialized current_sector (0) does not overwrite active scoring sector."""
        from isimotor_rawudp_client import CompactScoring, TelemInfo

        LMUParser._last_full_scoring = None

        # 1. Scoring définit le secteur 2 — drive the engine first (LMUParser only
        # *reads* its already-latched sector), mirroring telemetry_bus.py's call order.
        scoring = CompactScoring(sector=2)
        LMUParser._delta_engine.update_scoring(scoring)
        snap_sc = LMUParser.process_compact_scoring(scoring)
        self.assertEqual(snap_sc.current_sector, 2)
        self.assertEqual(LMUParser._last_current_sector, 2)

        # 2. Arrivée d'un paquet physique TelemInfo avec current_sector=0
        telem = TelemInfo(current_sector=0)
        LMUParser._delta_engine.update_physics(telem)
        snap_telem = LMUParser.process_telemetry(telem)
        self.assertIsNotNone(snap_telem)
        self.assertEqual(snap_telem.current_sector, 2)  # Le secteur 2 doit être préservé !
        self.assertEqual(LMUParser._last_current_sector, 2)


if __name__ == "__main__":
    unittest.main()

