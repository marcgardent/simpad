"""
SimPulse SDK — Scoring Packet Freshness Guard.

A single, dedicated, stateful class whose only job is "is this packet newer
than the last one accepted" — no field mapping (BaseTimingState.merge()'s
job), no session/lap logic (DeltaEngine's job). Same "one narrow concern,
composed by TelemetryStateStore" pattern as PresenceTracker (see presence.py).
"""

from __future__ import annotations

from typing import Optional


class ScoringFreshnessGuard:
    """
    Rejects an out-of-order CompactScoring/FullScoringSession packet before it
    can overwrite TelemetryStateStore.timing/.grid.

    UDP delivery is not FIFO: CompactScoring (10Hz) and FullScoringSession
    (2-5Hz) are two independent packet streams, and either can arrive at the
    socket after a NEWER packet (of either kind) has already been merged into
    self.timing/.grid. Before this guard, update_compact_scoring()/
    update_full_scoring() applied BaseTimingState.merge() unconditionally —
    a stale packet's OLDER total_laps briefly overwrote the fresher value,
    and DeltaEngine's "Case 1: Session reset" (laps_comp < its own
    last-seen counter — see delta_engine.py's _handle_lap_transition) read
    that regression as a genuine restart mid-lap, wiping
    _current_lap_samples and rejecting an otherwise-clean lap for
    "Insufficient samples" — despite nothing actually being wrong with the
    lap or the driving.

    Ordering is judged on `current_et` — the game's own elapsed-session
    clock, carried by both packet types — never on wall-clock receipt time:
    two packets can be RECEIVED out of order relative to when the game
    actually produced them, but current_et is the game-side sequence number
    that actually matters here.

    ONE shared instance guards both packet types (not one per channel),
    since CompactScoring and FullScoringSession both write the same
    self.timing/.grid — a fresh FullScoringSession must be able to reject a
    stale CompactScoring and vice versa; two independent per-channel
    baselines would let each stream keep clobbering the other's more recent
    data.

    A backwards jump bigger than `session_reset_tolerance_s` is treated as a
    genuine new session (garage re-entry, session restart, current_et itself
    resetting near 0) rather than a stale/out-of-order packet, and is
    accepted — rebasing this guard onto it rather than rejecting it forever.
    """

    def __init__(self, session_reset_tolerance_s: float = 5.0) -> None:
        self._session_reset_tolerance_s = session_reset_tolerance_s
        self._last_accepted_et: Optional[float] = None

    def should_accept(self, current_et: float) -> bool:
        """True if `current_et` is fresh enough to merge into timing/grid.

        Call exactly once per candidate packet, in delivery order — a True
        result also rebases the guard onto `current_et`, so this is not
        idempotent/side-effect-free (mirrors PacketSlot.update()'s own
        "call once per received packet" contract)."""
        if self._last_accepted_et is None or current_et >= self._last_accepted_et:
            self._last_accepted_et = current_et
            return True
        if self._last_accepted_et - current_et > self._session_reset_tolerance_s:
            self._last_accepted_et = current_et
            return True
        return False

    def reset(self) -> None:
        """Clears the baseline — next should_accept() call always accepts,
        same as a fresh guard. Called by TelemetryStateStore.reset()."""
        self._last_accepted_et = None
