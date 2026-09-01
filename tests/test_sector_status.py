"""
Unit tests for sector status calculations, non-realtime sensor telemetry retention, and sector delta formatting.
"""

import unittest
from src.telemetry.sensors import VehicleSensors
from src.telemetry.lmu_parser import LMUParser


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

        self.assertEqual(LMUParser._last_sector1_time, "30.000")
        self.assertEqual(LMUParser._last_sector1_status, "purple")

        self.assertEqual(LMUParser._last_sector2_time, "40.000")
        self.assertEqual(LMUParser._last_sector2_status, "purple")

        self.assertEqual(LMUParser._last_sector3_time, "25.000")
        self.assertEqual(LMUParser._last_sector3_status, "purple")

    def test_sector_delta_str_zero_delta(self):
        """Verify sector_delta_str formats zero delta (+0.000) when active session reference exists."""
        sensors = VehicleSensors(
            sector1_delta=0.0,
            delta_time=-0.120,
            sector1_time="30.500",
        )
        self.assertEqual(sensors.sector_delta_str(1), "+0.000")


if __name__ == "__main__":
    unittest.main()
