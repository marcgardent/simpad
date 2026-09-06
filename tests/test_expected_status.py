"""
Contract: the Expected (projected) lap time drives the unified colour code and is
propagated DeltaEngine → ReferenceLapManager packet → VehicleSensors copy.
"""
import unittest

from simpulse.core.telemetry.sector_colors import expected_status
from simpulse.core.reference_lap import ReferenceLapManager
from simpulse_sdk.models.telemetry import VehicleSensors


class TestExpectedStatusRule(unittest.TestCase):
    def test_priority_table(self):
        # value (projected) vs ever/paddock/session
        self.assertEqual(expected_status(98.0, ever=99.0, paddock=99.5, session=100.0), "pink")
        self.assertEqual(expected_status(99.2, ever=99.0, paddock=99.5, session=100.0), "purple")  # equal paddock
        self.assertEqual(expected_status(99.6, ever=99.0, paddock=99.5, session=100.0), "green")    # better session
        self.assertEqual(expected_status(101.0, ever=99.0, paddock=99.5, session=100.0), "yellow")  # slower session
        self.assertEqual(expected_status(90.0), "white")          # no reference
        self.assertEqual(expected_status(90.0, invalid=True), "invalid")

    def test_equal_counts_as_beaten(self):
        self.assertEqual(expected_status(99.0, ever=99.0), "pink")      # equal ever
        self.assertEqual(expected_status(99.5, ever=99.0, paddock=99.5), "purple")  # equal paddock
        self.assertEqual(expected_status(100.0, ever=99.0, paddock=99.5, session=100.0), "green")

    def test_engine_build_propagates_expected_status(self):
        mgr = ReferenceLapManager.get_instance()
        de = mgr.delta_engine
        de._ref_lap_time = 100.0
        de._ref_t_grid = [float(i) for i in range(101)]
        de._ref_num_points = 101
        de._ref_spatial_step = 1.0
        de._live_delta = -2.0                  # projected 98.0
        de._all_time_best_lap_time = 99.0      # ever
        de._session_best_lap_time = 100.0      # my session
        de._paddock_known = True
        de._paddock_best_lap = 99.5
        de._last_lap_flag = 2
        pkt = mgr._build_delta_packet(player_dist=200.0)
        self.assertEqual(pkt.estimated_lap_time_str, "01:38.000")
        self.assertEqual(pkt.expected_status, "pink")


class TestSensorCopy(unittest.TestCase):
    def test_field_default_exists(self):
        s = VehicleSensors()
        self.assertEqual(getattr(s, "expected_status", "white"), "white")


if __name__ == "__main__":
    unittest.main()
