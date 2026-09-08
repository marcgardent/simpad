"""
SimPulse Telemetry — Delta Smoothing.

Engine-facing moving-average primitive, ported out of the Cockpit HUD plugin
(``official_cockpit_hud/widgets/display_cache.py::HudTimeWindowAverage``) so
``DeltaEngine`` can smooth the live delta once, upstream, and expose a fully
consistent smoothed ``TimeStatus`` (value + colour + PR) alongside the raw
one — see ``DeltaEngine.time_status_smoothed``.

Unlike the plugin-side original, this is pure Python (no Qt) and numeric-only:
there is no ``raw_text``/passthrough sentinel to sniff at this layer (that was
a display-formatting concern). The caller (``DeltaEngine``) is responsible for
calling ``reset()`` at its own "no data"/discontinuity points (no reference,
pit/garage, lap/session reset, finish-line freeze ending, ...).
"""

from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class TimeWindowAverage:
    """Simple moving average over every sample received within the last
    ``window_s`` seconds of GAME time (not wall-clock). ``window_s == 0.0``
    degenerates to "report the latest raw sample as-is" (no averaging).
    """

    window_s: float = 0.15
    _samples: List[Tuple[float, float]] = field(default_factory=list, init=False, repr=False)

    def sample(self, value: float, game_time_s: float) -> float:
        """Records one (game_time_s, value) sample and returns the mean of
        every sample still inside the trailing window. Detects game time
        moving backwards (lap/session reset, replay scrub) and resets the
        window automatically in that case."""
        if self._samples and game_time_s < self._samples[-1][0]:
            self.reset()
        self._samples.append((game_time_s, value))
        cutoff = game_time_s - max(0.0, self.window_s)
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.pop(0)
        return sum(v for _, v in self._samples) / len(self._samples)

    def reset(self) -> None:
        """Clears the window explicitly on a known discontinuity."""
        self._samples = []
