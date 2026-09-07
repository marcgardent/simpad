"""
Unit tests for PresenceTracker (simpulse_sdk.models.presence) — the dedicated class
fusing TelemInfo/CompactScoring/FullScoringSession/SystemEvent/ExtendedState into
one hysteresis-guarded in_realtime/in_garage state, replacing LMUParser's former 5
independent heuristics. See ~/.claude/plans/cached-hopping-cupcake.md.

Phase 1 of that plan: this class is tested here in complete isolation (no Qt, no
TelemetryStateStore, no LMUParser) — nothing is wired yet.
"""

import unittest

from simpulse_sdk.models.presence import PresenceTracker


class TestPresenceTracker(unittest.TestCase):
    def setUp(self):
        self.p = PresenceTracker()

    def test_default_state_is_realtime(self):
        self.assertTrue(self.p.in_realtime)
        self.assertFalse(self.p.in_garage)

    # ---- explicit garage-stall beats speed ----------------------------------

    def test_compact_scoring_garage_stall_beats_realtime_flag(self):
        """in_garage_stall=True must win even if the packet also claims in_realtime=True."""
        self.p.on_compact_scoring(in_garage_stall=True, in_realtime=True)
        self.assertFalse(self.p.in_realtime)
        self.assertTrue(self.p.in_garage)

    def test_full_scoring_player_garage_stall_beats_everything(self):
        self.p.on_full_scoring(game_phase=5, session_in_realtime=True, player_in_garage_stall=True)
        self.assertFalse(self.p.in_realtime)

    def test_telemetry_garage_stall_fused_from_cached_compact_scoring(self):
        """on_telemetry() must re-derive garage state from the LATEST cached
        CompactScoring garage flag, not just from speed — mirrors
        lmu_parser.py's former L302-307 cross-packet fusion."""
        self.p.on_compact_scoring(in_garage_stall=True, in_realtime=True)
        # Even a high speed sample must not override an explicit garage-stall flag.
        self.p.on_telemetry(speed_mps=40.0)
        self.assertFalse(self.p.in_realtime)

    # ---- on_full_scoring must run unconditionally ----------------------------

    def test_full_scoring_without_resolved_player_vehicle_still_applies_top_level_check(self):
        """The game_phase/session_in_realtime check must fire even when no player
        vehicle was resolved that tick (player_in_garage_stall=False) — mirrors the
        original's unconditional write at L539-540, outside the `if player_veh:`
        block."""
        self.p.on_telemetry(speed_mps=0.0)
        self.p.on_full_scoring(game_phase=0, session_in_realtime=True, player_in_garage_stall=False)
        self.assertFalse(self.p.in_realtime)

    # ---- speed-based recovery + hysteresis latch -----------------------------

    def test_system_event_pause_then_speed_recovers_realtime(self):
        """SystemEvent(2) forces paused; a subsequent active-driving speed sample
        (>= 3.0 m/s) must recover in_realtime, mirroring
        test_lmu_parser_auto_realtime_recovery."""
        self.p.on_system_event(event_id=2)
        self.assertFalse(self.p.in_realtime)
        self.p.on_telemetry(speed_mps=40.0)
        self.assertTrue(self.p.in_realtime)

    def test_garage_stall_latch_persists_through_zero_speed(self):
        """Locks the load-bearing latch-persistence behavior from
        test_garage_stall_preserves_inactive_realtime: once CompactScoring reports
        in_garage_stall, a subsequent 0 m/s TelemInfo sample must NOT recover
        in_realtime (only a speed >= 3.0 m/s does)."""
        self.p.on_compact_scoring(in_garage_stall=True, in_realtime=False)
        self.assertFalse(self.p.in_realtime)
        self.p.on_telemetry(speed_mps=0.0)
        self.assertFalse(self.p.in_realtime)

    def test_active_driving_speed_threshold_is_3_mps(self):
        self.p.on_system_event(event_id=2)  # force paused
        self.p.on_telemetry(speed_mps=2.9)
        self.assertFalse(self.p.in_realtime, "2.9 m/s must stay below the 3.0 m/s active-driving threshold")
        self.p.on_telemetry(speed_mps=3.0)
        self.assertTrue(self.p.in_realtime)

    # ---- SystemEvent -----------------------------------------------------------

    def test_system_event_unrecognized_id_is_a_no_op(self):
        self.p.on_system_event(event_id=2)  # paused
        self.assertFalse(self.p.in_realtime)
        self.p.on_system_event(event_id=99)  # unrecognized: must not change state
        self.assertFalse(self.p.in_realtime)

    def test_system_event_ids_1_and_3_mean_realtime_2_and_4_mean_paused(self):
        for event_id in (1, 3):
            self.p = PresenceTracker()
            self.p.on_system_event(event_id=2)  # start paused
            self.p.on_system_event(event_id=event_id)
            self.assertTrue(self.p.in_realtime, f"event_id={event_id} must mean realtime")
        for event_id in (2, 4):
            self.p = PresenceTracker()
            self.p.on_system_event(event_id=event_id)
            self.assertFalse(self.p.in_realtime, f"event_id={event_id} must mean paused")

    # ---- ExtendedState, including its documented gap --------------------------

    def test_extended_state_garage_stall_speed_threshold_is_1_mps(self):
        self.p.on_telemetry(speed_mps=0.5)
        self.p.on_extended_state(in_realtime_fc=False)
        self.assertFalse(self.p.in_realtime)

    def test_extended_state_recovers_realtime_above_1_mps(self):
        self.p.on_system_event(event_id=2)  # force paused
        self.p.on_telemetry(speed_mps=1.0)
        self.p.on_extended_state(in_realtime_fc=False)
        self.assertTrue(self.p.in_realtime, "speed >= 1.0 m/s must recover realtime regardless of in_realtime_fc")

    def test_extended_state_known_gap_leaves_state_unchanged(self):
        """Documented, deliberately-preserved gap: in_realtime_fc=True combined with
        a stale low-speed sample (< 1.0 m/s) hits neither branch of the original
        if/elif, so state is left exactly as it was — not a design choice, a faithful
        reproduction of lmu_parser.py's former L596-604. If this test starts failing
        after a deliberate fix, that's expected — update it then."""
        self.p.on_system_event(event_id=2)  # force paused
        self.p.on_telemetry(speed_mps=0.5)
        self.p.on_extended_state(in_realtime_fc=True)
        self.assertFalse(self.p.in_realtime, "the gap: neither branch fires, state stays unchanged (paused)")


if __name__ == "__main__":
    unittest.main()
