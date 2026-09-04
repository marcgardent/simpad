"""
Unit tests for SimPad Central TelemetryStateStore and TelemetryWakeReason pipeline.
"""

import time
import unittest
from simpad_qt.core.telemetry.state_store import TelemetryStateStore, TelemetryWakeReason, PacketSlot
from simpad_qt.core.engineer.context import EngineerContext
from simpad_qt.core.engineer.manager import RaceEngineer
from isimotor_rawudp_client import (
    CompactScoring,
    FullScoringSession,
    VehicleScoring,
    TelemInfo,
    TelemWheel,
    TelemVect3,
    WeatherControl,
    ExtendedState,
    SystemEvent,
    ForceFeedback,
    Graphics,
)


class TestTelemetryStateStore(unittest.TestCase):
    def setUp(self):
        self.store = TelemetryStateStore()
        self.store.reset()

    def test_packet_slot_freshness_and_aging(self):
        """Verify PacketSlot tracks age and freshness correctly."""
        slot = PacketSlot()
        self.assertFalse(slot.is_fresh(max_age_sec=1.0))
        self.assertGreater(slot.age_sec, 1000.0)

        # Update slot
        now = time.time()
        slot.update("sample_data", timestamp=now)
        self.assertEqual(slot.data, "sample_data")
        self.assertTrue(slot.is_fresh(max_age_sec=1.0))
        self.assertLess(slot.age_sec, 0.5)

        # Artificially age slot
        slot.timestamp = now - 2.5
        self.assertFalse(slot.is_fresh(max_age_sec=1.0))
        self.assertGreaterEqual(slot.age_sec, 2.5)

    def test_unified_state_cross_channel_sync(self):
        """Verify 120Hz TelemInfo and 10Hz CompactScoring combine into unified state without data loss."""
        # 1. TelemInfo arrives: 4 wheels in grass (surface_type=2)
        wheels = [
            TelemWheel(surface_type=2, terrain_name="GRAS"),
            TelemWheel(surface_type=2, terrain_name="GRAS"),
            TelemWheel(surface_type=2, terrain_name="GRAS"),
            TelemWheel(surface_type=2, terrain_name="GRAS"),
        ]
        telem = TelemInfo(
            wheels=wheels,
            local_vel=TelemVect3(x=0.0, y=0.0, z=45.0),
            unfiltered_throttle=0.0,
            unfiltered_brake=0.5,
        )
        self.store.update_telemetry(telem)

        # Store properties should reflect grass excursion
        self.assertEqual(self.store.wheels_on_track, 0)
        self.assertFalse(self.store.is_on_track)
        self.assertEqual(self.store.surface_types, (2, 2, 2, 2))
        self.assertEqual(self.store.terrain_names, ("GRAS", "GRAS", "GRAS", "GRAS"))
        self.assertAlmostEqual(self.store.speed_kmh, 162.0, delta=0.1)

        # 2. CompactScoring arrives 20ms later (has no wheels!)
        compact = CompactScoring(count_lap_flag=1, total_laps=5, sector=2, in_realtime=1)
        self.store.update_compact_scoring(compact)

        # wheels_on_track MUST STILL BE 0 (NOT 4!), and lap_flag MUST BE 1
        self.assertEqual(self.store.wheels_on_track, 0)
        self.assertFalse(self.store.is_on_track)
        self.assertEqual(self.store.lap_flag, 1)
        self.assertEqual(self.store.total_laps, 5)
        self.assertEqual(self.store.current_sector, 2)

        # 3. TelemInfo arrives: car returns to road (surface_type=0)
        road_wheels = [
            TelemWheel(surface_type=0, terrain_name="ROAD"),
            TelemWheel(surface_type=0, terrain_name="ROAD"),
            TelemWheel(surface_type=0, terrain_name="ROAD"),
            TelemWheel(surface_type=0, terrain_name="ROAD"),
        ]
        telem2 = TelemInfo(wheels=road_wheels, local_vel=TelemVect3(x=0.0, y=0.0, z=40.0))
        self.store.update_telemetry(telem2)

        self.assertEqual(self.store.wheels_on_track, 4)
        self.assertTrue(self.store.is_on_track)
        self.assertEqual(self.store.lap_flag, 1)  # Still under investigation

    def test_engineer_context_wake_reason_dispatch(self):
        """Verify EngineerContext and RaceEngineer dispatch wake reasons correctly."""
        played = []
        engineer = RaceEngineer(audio_engine=lambda pk, interrupt=False: played.append(pk), auto_load_builtin_roles=False)

        # Process with wake_reason
        ctx_telem = engineer.update(
            telemetry=TelemInfo(local_vel=TelemVect3(x=0.0, y=0.0, z=30.0)),
            store=self.store,
            wake_reason=TelemetryWakeReason.PHYSICS_TICK,
        )
        self.assertEqual(self.store.telemetry.is_fresh(), True)

        ctx_scoring = engineer.update(
            scoring=CompactScoring(count_lap_flag=2),
            store=self.store,
            wake_reason=TelemetryWakeReason.SCORING_UPDATE,
        )
    def test_lap_validity_stateless_transitions(self):
        """Verify TelemetryStateStore processes lap validity transitions and exposes clean shared properties."""
        # 1. Initial valid frame on-track (silent first frame init)
        self.store.update_telemetry(TelemInfo(unfiltered_throttle=1.0), timestamp=100.0)
        self.store.update_compact_scoring(CompactScoring(count_lap_flag=2, in_realtime=1, in_garage_stall=0), timestamp=100.0)
        self.assertEqual(self.store.lap_flag, 2)
        self.assertTrue(self.store.is_lap_valid)
        self.assertFalse(self.store.is_lap_invalid)
        self.assertEqual(self.store.lap_timing_status, "timing_in_progress")
        self.assertEqual(self.store.lap_status_text, "Valid")
        self.assertIsNone(self.store.validity_transition)

        # 2. Driver cuts track -> count_lap_flag becomes 1 (Time deleted)
        self.store.update_compact_scoring(CompactScoring(count_lap_flag=1, in_realtime=1, in_garage_stall=0), timestamp=105.0)
        self.assertEqual(self.store.lap_flag, 1)
        self.assertFalse(self.store.is_lap_valid)
        self.assertTrue(self.store.is_lap_invalid)
        self.assertEqual(self.store.lap_timing_status, "time_deleted")
        self.assertEqual(self.store.lap_status_text, "Invalid")
        self.assertEqual(self.store.last_validity_event, "TIME_DELETED")
        self.assertEqual(self.store.consume_validity_transition(), "time_deleted")
        self.assertIsNone(self.store.validity_transition)  # Consumed

        # 3. Repeat flag 1: no transition emitted
        self.store.update_compact_scoring(CompactScoring(count_lap_flag=1, in_realtime=1, in_garage_stall=0), timestamp=106.0)
        self.assertIsNone(self.store.validity_transition)

        # 4. Lap revalidated / new lap -> count_lap_flag becomes 2 (Timing in progress)
        self.store.update_compact_scoring(CompactScoring(count_lap_flag=2, in_realtime=1, in_garage_stall=0), timestamp=110.0)
        self.assertEqual(self.store.lap_flag, 2)
        self.assertTrue(self.store.is_lap_valid)
        self.assertFalse(self.store.is_lap_invalid)
        self.assertEqual(self.store.lap_timing_status, "timing_in_progress")
        self.assertEqual(self.store.last_validity_event, "TIMING_IN_PROGRESS")
        self.assertEqual(self.store.consume_validity_transition(), "timing_in_progress")

    def test_lap_validity_garage_silence(self):
        """Verify TelemetryStateStore remains silent and emits no transitions while in garage or paused."""
        # 1. Spawn in garage with flag=1
        self.store.update_compact_scoring(CompactScoring(count_lap_flag=1, in_realtime=1, in_garage_stall=1), timestamp=10.0)
        self.assertTrue(self.store.in_garage)
        self.assertEqual(self.store.lap_flag, 1)
        self.assertIsNone(self.store.validity_transition)

        # 2. Flag changes to 2 while still in garage -> NO transition
        self.store.update_compact_scoring(CompactScoring(count_lap_flag=2, in_realtime=1, in_garage_stall=1), timestamp=11.0)
        self.assertIsNone(self.store.validity_transition)

        # 3. Exit garage onto track (first on-track frame is silent)
        self.store.update_compact_scoring(CompactScoring(count_lap_flag=2, in_realtime=1, in_garage_stall=0), timestamp=12.0)
        self.assertFalse(self.store.in_garage)
        self.assertIsNone(self.store.validity_transition)

        # 4. First cut on track -> triggers time_deleted
        self.store.update_compact_scoring(CompactScoring(count_lap_flag=1, in_realtime=1, in_garage_stall=0), timestamp=15.0)
        self.assertEqual(self.store.consume_validity_transition(), "time_deleted")

    def test_all_telemetry_channel_update_methods(self):
        """Verify TelemetryStateStore provides update methods for all TelemetryChannel values."""
        from simpad_qt.core.telemetry_channels import TelemetryChannel
        from simpad_qt.plugins.contracts import TelemetryRawPacket
        from simpad_qt.plugins.manager import PluginManager
        from simpad_qt.core.config import ConfigManager

        self.assertTrue(hasattr(self.store, "update_extended_state"))
        self.assertTrue(hasattr(self.store, "update_opponent_telemetry"))
        self.assertTrue(hasattr(self.store, "update_system_events"))
        self.assertTrue(hasattr(self.store, "update_force_feedback"))
        self.assertTrue(hasattr(self.store, "update_graphics"))
        self.assertTrue(hasattr(self.store, "update_track_rules"))
        self.assertTrue(hasattr(self.store, "update_pit_menu"))

        pm = PluginManager(config_manager=ConfigManager())
        channel_data_map = {
            TelemetryChannel.TELEMETRY: TelemInfo(),
            TelemetryChannel.OPPONENT_TELEMETRY: TelemInfo(),
            TelemetryChannel.COMPACT_SCORING: CompactScoring(),
            TelemetryChannel.FULL_SCORING: FullScoringSession(),
            TelemetryChannel.WEATHER: WeatherControl(),
            TelemetryChannel.EXTENDED_STATE: ExtendedState(),
            TelemetryChannel.SYSTEM_EVENTS: SystemEvent(),
            TelemetryChannel.FORCE_FEEDBACK: ForceFeedback(),
            TelemetryChannel.GRAPHICS: Graphics(),
            TelemetryChannel.TRACK_RULES: None,
            TelemetryChannel.PIT_MENU: None,
        }
        for ch in TelemetryChannel:
            pkt = TelemetryRawPacket(channel=ch, data=channel_data_map.get(ch), raw_bytes_len=64)
            pm.dispatch_packet(pkt)


if __name__ == "__main__":
    unittest.main()
