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
        # DeltaEngine.expected_lap_status is SESSION-scoped only (no pink): the
        # all-time-best ("ever") comparison is reported separately as the
        # expected_lap_is_pr flag instead of a colour — see the "no pink, PR
        # tag" convention in simpulse.builtin_plugins.expected_timing.
        mgr = ReferenceLapManager.get_instance()
        de = mgr.delta_engine
        de._ref_lap_time = 100.0
        de._ref_t_grid = [float(i) for i in range(101)]
        de._ref_num_points = 101
        de._ref_spatial_step = 1.0
        de._live_delta = -2.0                  # projected 98.0
        de._all_time_best_lap_time = 99.0      # ever (beaten -> PR flag)
        de._session_best_lap_time = 100.0      # my session
        de._paddock_known = True
        de._paddock_best_lap = 99.5            # beaten -> purple
        de._last_lap_flag = 2
        pkt = mgr._build_delta_packet(player_dist=200.0)
        self.assertEqual(pkt.estimated_lap_time_str, "01:38.000")
        self.assertEqual(pkt.expected_status, "purple")
        self.assertTrue(pkt.expected_lap_is_pr)


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


class TestExpectedSectorTimes(unittest.TestCase):
    """S1/S2/S3 EXPECTED = reference split + live splitN delta, session-scoped
    colour only (no pink); beating the all-time-best split -> *_is_pr=True."""

    def _profile(self, s1_time, s2_time, lap_time):
        from simpulse.core.telemetry.reference_profile import ReferenceLapProfile
        return ReferenceLapProfile(
            lap_time=lap_time, sector_1_time=s1_time, sector_2_time=s2_time,
            t_grid=[float(i) for i in range(101)], num_points=101,
        )

    def test_sector1_expected_and_pr_flag(self):
        from simpulse.core.telemetry.delta_engine import DeltaEngine
        eng = DeltaEngine()
        eng._current_profile = self._profile(30.0, 60.0, 100.0)   # active reference S1=30
        eng._all_time_best_profile = self._profile(29.0, 60.0, 99.0)  # ever S1=29 (beaten below)
        eng._session_best_profile = self._profile(31.0, 60.0, 101.0)  # my session S1=31
        eng._paddock_known = True
        eng._paddock_cum_s1 = 29.5   # paddock S1=29.5 (also beaten -> purple)
        eng._paddock_cum_s2 = 60.0
        eng._paddock_best_lap = 100.0
        eng._ref_t_grid = [float(i) for i in range(101)]
        eng._ref_num_points = 101
        eng._sector1_delta = -1.5   # projected S1 = 30.0 - 1.5 = 28.5

        self.assertEqual(eng.expected_sector1_time, "00:28.500")
        self.assertEqual(eng.expected_sector1_status, "purple")   # beats paddock 29.5, session-scoped
        self.assertTrue(eng.expected_sector1_is_pr)               # 28.5 <= ever 29.0

    def test_sector_untouched_defaults_to_reference_split(self):
        from simpulse.core.telemetry.delta_engine import DeltaEngine
        eng = DeltaEngine()
        eng._current_profile = self._profile(30.0, 60.0, 100.0)
        eng._ref_t_grid = [float(i) for i in range(101)]
        eng._ref_num_points = 101
        eng._sector2_delta = 0.0  # S2 not reached yet -> target = reference split (60-30=30)
        self.assertEqual(eng.expected_sector2_time, "00:30.000")
        self.assertFalse(eng.expected_sector2_is_pr)

    def test_no_reference_is_white_dash(self):
        from simpulse.core.telemetry.delta_engine import DeltaEngine
        eng = DeltaEngine()
        self.assertEqual(eng.expected_sector1_time, "--")
        self.assertEqual(eng.expected_sector1_status, "white")
        self.assertFalse(eng.expected_sector1_is_pr)


if __name__ == "__main__":
    unittest.main()
