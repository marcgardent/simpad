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


class TestSectorVioletVsPaddock(unittest.TestCase):
    """Violet sector: when your crossing of S1/S2 is better-or-equal the best
    cumulative split of the other cars (paddock), the sector turns purple."""

    def _update(self, eng, player, rival):
        pkt = {"mTrackName": "T1", "mLapDist": 3000.0,
               "mVehicles": [player, rival]}
        eng.update_scoring(pkt)

    def test_s1_violet_when_beat_paddock(self):
        from simpulse.core.telemetry.delta_engine import DeltaEngine
        eng = DeltaEngine()
        rivals_sp = {
            "mIsPlayer": False, "mVehicleName": "Riv", "mVehicleClass": "GT3",
            "mTotalLaps": 3, "mTimeIntoLap": 1.0, "mLapDist": 100.0,
            "mSector": 2, "mCountLapFlag": 2, "mLastLapTime": 40.0,
            "mCurSector1": 0.0, "mCurSector2": 0.0,
            "mLastSector1": 10.0, "mLastSector2": 30.0,
            "mBestSector1": 10.0, "mBestSector2": 30.0, "mBestLapTime": 40.0,
        }
        player = {
            "mIsPlayer": True, "mVehicleName": "Me", "mVehicleClass": "GT3",
            "mTotalLaps": 1, "mTimeIntoLap": 1.0, "mLapDist": 100.0,
            "mSector": 2, "mCountLapFlag": 2, "mLastLapTime": 40.0,
            "mCurSector1": 9.5, "mCurSector2": 0.0,        # 9.5 < paddock 10 → violet
            "mLastSector1": 20.0, "mLastSector2": 50.0,
            "mBestSector1": 19.0, "mBestSector2": 49.0, "mBestLapTime": 60.0,
        }
        self._update(eng, player, rivals_sp)
        self.assertEqual(eng._paddock_cum_s1, 10.0)
        self.assertEqual(eng._last_sector1_time, "00:09.500")
        self.assertEqual(eng._last_sector1_status, "purple")

    def test_s1_not_violet_when_slower_than_paddock(self):
        from simpulse.core.telemetry.delta_engine import DeltaEngine
        eng = DeltaEngine()
        rival = {
            "mIsPlayer": False, "mVehicleName": "R", "mVehicleClass": "GT3",
            "mTotalLaps": 2, "mTimeIntoLap": 1.0, "mLapDist": 100.0,
            "mSector": 2, "mCountLapFlag": 2, "mLastLapTime": 40.0,
            "mCurSector1": 0.0, "mCurSector2": 0.0, "mLastSector1": 8.0,
            "mLastSector2": 25.0, "mBestSector1": 8.0, "mBestSector2": 25.0,
            "mBestLapTime": 33.0,
        }
        player = {
            "mIsPlayer": True, "mVehicleName": "Me", "mVehicleClass": "GT3",
            "mTotalLaps": 1, "mTimeIntoLap": 1.0, "mLapDist": 100.0,
            "mSector": 2, "mCountLapFlag": 2, "mLastLapTime": 40.0,
            "mCurSector1": 11.0, "mCurSector2": 0.0,
            "mLastSector1": 22.0, "mLastSector2": 55.0,
            "mBestSector1": 21.0, "mBestSector2": 54.0, "mBestLapTime": 70.0,
        }
        self._update(eng, player, rival)
        self.assertNotEqual(eng._last_sector1_status, "purple")


if __name__ == "__main__":
    unittest.main()
