"""
Unit tests for sector status calculations, non-realtime sensor telemetry retention, and sector delta formatting.
"""

import time
import unittest
from simpulse.core.telemetry.sensors import VehicleSensors
from simpulse.core.telemetry.state_store import TelemetryStateStore
from simpulse.core.reference_lap import ReferenceLapManager


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

    def test_store_current_sector_reads_delta_engine_live(self):
        """TelemetryStateStore.current_sector must reflect the shared DeltaEngine's
        current sector display exactly (via update_delta, fed by
        ReferenceLapManager.update_scoring_from_view) — never a naive per-packet
        remap of the raw isiMotor sector code. See
        TelemetryStateStore._resolve_current_sector's docstring."""
        from isimotor_rawudp_client import FullScoringSession, VehicleScoring

        store = TelemetryStateStore.get_instance()
        rlm = ReferenceLapManager.get_instance()
        player_veh = VehicleScoring(
            id=1, is_player=True, control=0, sector=2,
            cur_sector1=-1.0,
            last_sector1=30.0,
            best_sector1=30.0,
            cur_sector2=-1.0,
            last_sector2=70.0,
            best_sector2=70.0,
            last_lap_time=95.0,
            best_lap_time=95.0,
        )
        session = FullScoringSession(track_name="T1", lap_dist=1000.0, vehicles=[player_veh])

        # Merge into the Store first, then feed the Engine from the Store's View —
        # mirrors telemetry_bus.py's real call order.
        store.update_full_scoring(session, timestamp=time.time())
        rlm.update_scoring_from_view(store.timing, store.grid)

        de = rlm.delta_engine
        self.assertEqual(de.current_sector, 2)
        self.assertEqual(de.sector1_time_str, "00:30.000")
        self.assertEqual(de.sector1_status, "pink")
        self.assertEqual(store.current_sector, 2)

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

        store = TelemetryStateStore.get_instance()
        rlm = ReferenceLapManager.get_instance()

        # 1. Scoring définit le secteur 2 — merge into Store, then drive the Engine
        # from the Store's View, mirroring telemetry_bus.py's call order.
        scoring = CompactScoring(sector=2)
        store.update_compact_scoring(scoring, timestamp=time.time())
        rlm.update_scoring_from_view(store.timing, store.grid)
        self.assertEqual(store.current_sector, 2)

        # 2. Arrivée d'un paquet physique TelemInfo avec current_sector=0
        telem = TelemInfo(current_sector=0)
        store.update_telemetry(telem, timestamp=time.time())
        rlm.update_physics_from_view(store.snapshot())
        self.assertEqual(store.current_sector, 2)  # Le secteur 2 doit être préservé !


if __name__ == "__main__":
    unittest.main()
