"""
Cockpit HUD — time-windowed moving average for expected/delta readouts.

Scope, deliberately narrow: this only ever smooths PROJECTIONS (live delta,
expected finish time) — an estimation that is, by construction, never exact
to begin with, so averaging recent samples to read more steadily on screen
introduces no meaningful new error. This is UNRELATED to `lerp` (see
base_widget.py), which eases raw telemetry (tire slip, RPM, pedals, ...) for
gauge animation — a physical channel describing what the car is *actually*
doing right now must never be smoothed the same way. Two different concerns,
two different mechanisms; don't conflate them.

``HudTimeWindowAverage`` averages every sample received within the last
``window_s`` seconds — of GAME time, not wall-clock/PC time: the overlay's
own paint rate (target_fps, vsync, a dropped frame) has nothing to do with
how much *in-race* time a smoothing window should cover, and PC time keeps
advancing even when the game doesn't (paused, loading, a scrubbed replay).
The caller supplies the current game time each sample (e.g.
``BaseTimingState.current_et``) — see ``CockpitWidgetContext.game_time_s``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# Readouts meaning "no data yet" reset the window and pass through
# immediately — a real reading must never get averaged in with samples from
# before a gap (e.g. losing the reference mid-lap).
_PASSTHROUGH_TEXTS = ("", "--", "--:--.---")


@dataclass
class HudTimeWindowAverage:
    """Simple moving average over every sample received within the last
    ``window_s`` seconds of GAME time.

    ``window_s`` (0.0 to 2.0): 0.0 disables smoothing (reports the latest
    raw sample as-is — a sample at the exact current game time is always
    kept). No ceiling is enforced here — the UI slider caps it at 2s.
    """
    window_s: float = 0.15

    _samples: List[Tuple[float, float]] = field(default_factory=list, init=False, repr=False)  # (game_time_s, value)

    def sample(self, raw_value: float, raw_text: str, game_time_s: float) -> Optional[float]:
        """Feeds one fresh raw reading at the given GAME time. Returns the
        averaged value to display, or ``None`` when ``raw_text`` signals "no
        data" (the caller should show that raw text as-is instead)."""
        if raw_text in _PASSTHROUGH_TEXTS:
            self.reset()
            return None

        if self._samples and game_time_s < self._samples[-1][0]:
            # Game time went backwards (session/lap reset, a scrubbed replay)
            # — old samples would corrupt the window against a time base that
            # no longer applies; start fresh.
            self.reset()

        self._samples.append((game_time_s, raw_value))
        cutoff = game_time_s - max(0.0, self.window_s)
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.pop(0)

        values = [v for _, v in self._samples]
        return sum(values) / len(values)

    def reset(self) -> None:
        """Clears the window — call on a discontinuity (e.g. a freeze window
        ending) so old samples don't get averaged into the new lap."""
        self._samples = []


__all__ = ["HudTimeWindowAverage"]
