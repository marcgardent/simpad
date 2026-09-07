"""
SimPulse SDK — Vehicle Presence Fusion.

A single, dedicated, stateful class that fuses every signal the game exposes about
whether the player is actively driving vs. in the garage / paused / in a menu, with
hysteresis. Replaces LMUParser's 5 independent, mutually-divergent heuristics (see
`# TODO SRP` markers in simpulse/core/telemetry/lmu_parser.py) — this is the one
"garage/pause" concern that genuinely needs cross-packet memory, unlike the purely
stateless computed fields (aero_downforce, wheels_on_track, track_cut_state) that
belong on TelemetryStateStore as plain properties instead.

Deliberately preserves the exact current behaviour (including two known
imperfections, documented in-line) rather than silently "fixing" it — see
~/.claude/plans/cached-hopping-cupcake.md for the migration plan and rationale.
"""

from __future__ import annotations


class PresenceTracker:
    """
    Fuses TelemInfo speed, CompactScoring, FullScoringSession, SystemEvent and
    ExtendedState into ONE authoritative, hysteresis-guarded presence state.

    No Qt, no singleton, no file I/O — a plain state machine, fully unit-testable
    in isolation. Owned/composed by TelemetryStateStore (one instance), fed from
    its existing update_telemetry/update_compact_scoring/update_full_scoring/
    update_system_event(s)/update_extended_state methods, which already receive
    every relevant packet, in order, before LMUParser ever runs.

    `in_realtime` and `in_garage` are two views of a single internal latch, never
    independent booleans: every one of the 5 original heuristics wrote them as
    exact negations of each other, and every existing consumer
    (TelemetryStateStore._process_lap_validity, race_engineer/context.py) reads
    them via `in_garage or not in_realtime`, which is invariant under this
    collapse.
    """

    # Two distinct thresholds are preserved on purpose (not unified) — sites 1
    # (main check)/2/3 originally used 3.0 m/s ("active driving"), site 1's nested
    # game_phase check and site 5 originally used 1.0 m/s ("garage stall"). Faithful
    # reproduction, not a design choice.
    _ACTIVE_DRIVING_SPEED_MPS = 3.0
    _GARAGE_STALL_SPEED_MPS = 1.0

    def __init__(self) -> None:
        self._in_realtime: bool = True
        # Cached cross-packet signals, mirroring what LMUParser used to keep as
        # cls._last_telem_info / cls._last_compact_scoring / cls._last_full_scoring
        # for the same purpose: on_telemetry() needs the latest known scoring-side
        # garage flags, and on_compact_scoring()/on_full_scoring()/on_extended_state()
        # need the latest known speed, without cross-referencing each other's packets.
        self._last_speed_mps: float = 0.0
        self._last_compact_in_garage_stall: bool = False
        self._last_full_player_in_garage_stall: bool = False
        self._last_full_game_phase: int = 5

    @property
    def in_realtime(self) -> bool:
        return self._in_realtime

    @property
    def in_garage(self) -> bool:
        return not self._in_realtime

    def on_telemetry(self, speed_mps: float) -> None:
        """Fuses TelemInfo speed with the latest cached scoring-side garage flags.
        Priority: explicit garage-stall (any source) > active-driving speed >
        hysteresis latch > default realtime. Mirrors LMUParser.process_telemetry's
        former L298-320 (site 1 of 5)."""
        is_strictly_in_garage_stall = (
            self._last_compact_in_garage_stall
            or self._last_full_player_in_garage_stall
            or (self._last_full_game_phase == 0 and speed_mps < self._GARAGE_STALL_SPEED_MPS)
        )

        if is_strictly_in_garage_stall:
            self._in_realtime = False
        elif speed_mps >= self._ACTIVE_DRIVING_SPEED_MPS:
            # Active on-track detection from 10.8 km/h
            self._in_realtime = True
        elif not self._in_realtime:
            # Maintain pause/garage state if completely stopped after explicit exit
            self._in_realtime = False
        else:
            self._in_realtime = True

        self._last_speed_mps = speed_mps

    def on_compact_scoring(self, in_garage_stall: bool, in_realtime: bool) -> None:
        """Mirrors LMUParser.process_compact_scoring's former L377-382 (site 2 of 5).
        Stateless overwrite (does not consult the hysteresis latch)."""
        is_in_garage = bool(in_garage_stall) or (
            not bool(in_realtime) and self._last_speed_mps < self._ACTIVE_DRIVING_SPEED_MPS
        )
        self._in_realtime = not is_in_garage
        self._last_compact_in_garage_stall = bool(in_garage_stall)

    def on_full_scoring(
        self,
        game_phase: int,
        session_in_realtime: bool,
        player_in_garage_stall: bool,
    ) -> None:
        """Mirrors LMUParser.process_full_scoring's former L455-471 + L539-540
        (site 3 of 5). Must be called unconditionally (even when no player vehicle
        resolved that tick — pass player_in_garage_stall=False), matching the
        original's write at L539-540 sitting outside the `if player_veh:` block."""
        is_in_garage = False
        if game_phase == 0 and self._last_speed_mps < self._ACTIVE_DRIVING_SPEED_MPS:
            is_in_garage = True
        elif not session_in_realtime and self._last_speed_mps < self._ACTIVE_DRIVING_SPEED_MPS:
            is_in_garage = True
        if player_in_garage_stall:
            is_in_garage = True

        self._in_realtime = not is_in_garage
        self._last_full_player_in_garage_stall = bool(player_in_garage_stall)
        self._last_full_game_phase = int(game_phase)

    def on_system_event(self, event_id: int) -> None:
        """Mirrors LMUParser.process_system_event's former L559-564 (site 4 of 5).
        No speed involved. An unrecognized event_id is a no-op (state unchanged),
        exactly as before."""
        if event_id in (1, 3):
            self._in_realtime = True
        elif event_id in (2, 4):
            self._in_realtime = False

    def on_extended_state(self, in_realtime_fc: bool) -> None:
        """Mirrors the ExtendedState branch of LMUParser.process_packet's former
        L596-604 (site 5 of 5).

        Preserves a known gap exactly, not fixed here (see migration plan): when
        `in_realtime_fc` is True and the last known speed is below
        _GARAGE_STALL_SPEED_MPS, NEITHER branch fires and state is left unchanged —
        this was true of the original if/elif and is reproduced faithfully.
        """
        if not in_realtime_fc and self._last_speed_mps < self._GARAGE_STALL_SPEED_MPS:
            self._in_realtime = False
        elif self._last_speed_mps >= self._GARAGE_STALL_SPEED_MPS:
            self._in_realtime = True
        # else: no-op — the documented gap above.
