"""
Fuel / Virtual-Energy consumption engine.

Neither the TelemInfo physics packet nor the scoring packets carry a "fuel
used last lap" or a "laps remaining on this tank/battery" field — mFuel (and,
for WEC Hypercars, the LMU virtual_energy expansion resolved onto
VehicleSensors.fuel_level by VehicleSensors.from_telem_info()) is only ever
the *instantaneous* level. Likewise there's no "how long does a lap take"
field beyond the raw last_lap_time of the one just completed. This engine
derives both from lap-to-lap deltas/samples, fed one physics tick at a time
by TelemetryBus. Its output is stamped onto VehicleSensors.energy_per_lap /
.energy_projected_laps / .energy_lap_time_median, which OfficialCockpitHud's
QtEnergyLapsWidget displays, and feeds session_energy_gauge.py's "will this
last to the end of the session" projection.

The per-lap samples are also persisted (see save_history/load_history) into
this combo's ref_<track>_<car>.energy.json — TelemetryBus reloads it the moment
a track/vehicle combo is resolved (DeltaEngine.get_energy_history_filepath()),
so the projection is already meaningful from lap 1 of a session/warmup: e.g.
noticing a suspiciously low projected-laps figure means "I forgot to put fuel
in" before a single lap of THIS session has been driven.
"""

from __future__ import annotations

import json
import logging
import statistics
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Optional

logger = logging.getLogger(__name__)


@dataclass
class LapSample:
    """One completed lap's data point. Either field can be missing (None) —
    e.g. last_lap_time reporting 0.0 the very tick total_laps increments —
    without discarding the other; the median helpers below simply skip a
    sample for a given metric where it's None, so a spotty lap_time signal
    never costs FuelEnergyEngine its fuel/energy history or vice versa."""

    fuel: Optional[float] = None
    lap_time: Optional[float] = None


def _median_of(values: list) -> float:
    non_null = [v for v in values if v is not None]
    return statistics.median(non_null) if non_null else 0.0


class FuelEnergyEngine:
    """Tracks fuel/virtual-energy consumption AND lap time, lap over lap, and
    projects how many more laps the current level can sustain.

    Stateful and single-vehicle: one instance tracks the player car across a
    session/stint. Resets itself when the completed-lap counter goes
    backwards (session restart or re-join) since history from a previous
    stint no longer applies.

    HISTORY_SIZE (64 laps) and the median (rather than a mean or the session
    best) are the "smart filters" this engine relies on to stay resilient to
    the odd cold/scruffy out-lap or an unusually conservative/aggressive
    single lap: a median is unmoved by a handful of outliers the way a
    rolling mean would be, and doesn't share a personal-best lap's
    unsustainable pace the way DeltaEngine's best_lap_time would if reused
    here for a "how many laps are left in the session" estimate. 64 laps
    comfortably spans several stints/sessions once persisted.
    """

    HISTORY_SIZE = 64  # rolling window, in laps — persisted across sessions

    def __init__(self) -> None:
        self.reset()

    # Fraction below max_level_seen still counted as "topped up" — the game
    # never reports absolute tank capacity, so a small tolerance absorbs the
    # display-rounding/regen noise around an actual full refill.
    FULL_TANK_TOLERANCE = 0.01

    def reset(self) -> None:
        self._history: Deque[LapSample] = deque(maxlen=self.HISTORY_SIZE)
        self._lap_start_level: Optional[float] = None
        self._last_total_laps: Optional[int] = None
        self._pit_seen_this_lap: bool = False
        self.last_lap_consumption: float = 0.0
        self.estimated_consumption_per_lap: float = 0.0
        self.estimated_laps_remaining: float = 0.0
        self.estimated_lap_time: float = 0.0  # median, not a best/PB time — see class docstring
        # Highest level ever seen this session/stint — the best available
        # stand-in for "full tank" since no packet ever reports absolute
        # capacity. Monotonic: a race-start full tank sets it once, a mid-
        # session refuel can only raise it further. See is_tank_full().
        self.max_level_seen: float = 0.0

    def update(
        self,
        level: float,
        total_laps: int,
        lap_time: float = 0.0,
        is_pit_lap: bool = False,
    ) -> bool:
        """`level` is the current VehicleSensors.fuel_level (already resolved to
        liters, or a Hypercar's virtual-energy percentage). `total_laps` is the
        unified completed-lap counter (TelemetryView.total_laps). `lap_time` is
        the just-completed lap's duration (TelemetryView.timing.last_lap_time —
        already valid the same tick total_laps increments). `is_pit_lap` marks
        a lap that included a pit visit — its consumption delta AND lap time
        are both skipped, since a refuel/recharge makes the fuel delta
        meaningless and a pit-lane visit makes the lap time unrepresentative
        of normal pace.

        Returns True the tick a new lap sample was recorded into history — the
        caller's cue to persist it via save_history().
        """
        level = float(level)
        total_laps = int(total_laps)
        recorded = False

        if self._last_total_laps is not None and total_laps < self._last_total_laps:
            self.reset()

        self.max_level_seen = max(self.max_level_seen, level)

        if self._lap_start_level is None:
            self._lap_start_level = level
            self._last_total_laps = total_laps
        elif total_laps != self._last_total_laps:
            consumed = self._lap_start_level - level
            # Always-on diagnostic (no config gate — see DeltaEngine's
            # "Lap completed" line, same reasoning): every prior "why isn't
            # fuel being captured" guess so far turned out wrong once actual
            # numbers were looked at (see delta_engine.py's own SAMPLE_
            # REJECTED/scoring_ticks additions) — this is that same lap-
            # boundary log for FuelEnergyEngine, printed once per lap
            # regardless of whether a sample ends up recorded, showing
            # exactly why (level frozen at the same value across the whole
            # lap means the resolved fuel/energy reading itself is stuck,
            # not this engine's own logic).
            logger.info(
                "[FuelEnergyEngine] Lap boundary: total_laps %s->%s, "
                "lap_start_level=%.3f, level=%.3f, consumed=%.3f, "
                "is_pit_lap=%s, pit_seen_this_lap=%s",
                self._last_total_laps, total_laps, self._lap_start_level, level,
                consumed, is_pit_lap, self._pit_seen_this_lap,
            )
            print(
                f"[FuelEnergyEngine] Lap boundary: total_laps {self._last_total_laps}->{total_laps}, "
                f"lap_start_level={self._lap_start_level:.3f}, level={level:.3f}, consumed={consumed:.3f}, "
                f"is_pit_lap={is_pit_lap}, pit_seen_this_lap={self._pit_seen_this_lap}",
                flush=True,
            )
            # A rising level across the lap boundary means a refuel/recharge
            # happened during it (pit stop) — skip recording that lap but
            # still resync the baseline for the one that's starting.
            if not self._pit_seen_this_lap:
                sample = LapSample(
                    fuel=round(consumed, 3) if consumed > 0.0 else None,
                    lap_time=round(float(lap_time), 3) if lap_time > 0.0 else None,
                )
                if sample.fuel is not None or sample.lap_time is not None:
                    if sample.fuel is not None:
                        self.last_lap_consumption = sample.fuel
                    self._history.append(sample)
                    recorded = True
            self._lap_start_level = level
            self._last_total_laps = total_laps
            self._pit_seen_this_lap = False

        if is_pit_lap:
            self._pit_seen_this_lap = True

        self._recompute()
        self.estimated_laps_remaining = (
            level / self.estimated_consumption_per_lap
            if self.estimated_consumption_per_lap > 0.0
            else 0.0
        )
        return recorded

    def _recompute(self) -> None:
        """Refreshes the two medians from history. Deliberately does NOT touch
        estimated_laps_remaining — that needs the caller's current `level`,
        only available inside update() (see its tail) or absent entirely right
        after load_history() (no level known yet — stays at reset()'s 0.0
        until the next update() call)."""
        fuel_values = [s.fuel for s in self._history if s.fuel is not None]
        lap_time_values = [s.lap_time for s in self._history if s.lap_time is not None]

        self.estimated_consumption_per_lap = _median_of(fuel_values)
        self.estimated_lap_time = _median_of(lap_time_values)

    def is_tank_full(self, level: float) -> bool:
        """True when `level` is at/near the highest level ever recorded this
        session (see max_level_seen) — the best available "full tank" signal
        since no packet ever reports absolute capacity. True before anything
        has been observed yet (nothing to compare against — don't flag a
        false anomaly on tick one)."""
        if self.max_level_seen <= 0.0:
            return True
        return level >= self.max_level_seen * (1.0 - self.FULL_TANK_TOLERANCE)

    def has_insufficient_fuel_anomaly(self, level: float, session_energy_ratio: Optional[float]) -> bool:
        """Fuel anomaly: not enough energy to finish the session AND the tank
        isn't topped up — i.e. a splash-and-dash would still fix it, so this
        is worth a driver's attention right now (unlike a car that
        structurally can't do a full stint on one tank, which stays true
        even with a full one — that's not an anomaly, that's the car).
        `session_energy_ratio` is session_energy_gauge's — None (session
        length not known yet) never flags an anomaly."""
        if session_energy_ratio is None or session_energy_ratio >= 1.0:
            return False
        return not self.is_tank_full(level)

    # ── Persistence (ref_<track>_<car>.energy.json) ──────────────────────────
    def to_dict(self) -> dict:
        return {
            "laps": [
                {k: v for k, v in (("fuel", s.fuel), ("lap_time", s.lap_time)) if v is not None}
                for s in self._history
            ]
        }

    def load_history(self, filepath: Path) -> None:
        """Loads a persisted per-lap history (see save_history()). Call once,
        right after a track/vehicle combo is (re)resolved, BEFORE the first
        lap of that combo completes this session — that's what lets
        estimated_consumption_per_lap/estimated_lap_time already be non-zero
        on lap 1 of a warmup, instead of sitting at 0.0 until a full lap of
        THIS session has been driven.
        """
        try:
            filepath = Path(filepath)
            if not filepath.exists():
                return
            data = json.loads(filepath.read_text(encoding="utf-8"))
            raw_laps = data.get("laps")
            if raw_laps is None:
                # Back-compat with the older {"history": [floats]} fuel-only
                # schema this file used before lap_time was added.
                raw_laps = [{"fuel": v} for v in data.get("history", [])]
            samples = []
            for entry in raw_laps:
                fuel = entry.get("fuel")
                lap_time = entry.get("lap_time")
                fuel = float(fuel) if fuel is not None and float(fuel) > 0.0 else None
                lap_time = float(lap_time) if lap_time is not None and float(lap_time) > 0.0 else None
                if fuel is not None or lap_time is not None:
                    samples.append(LapSample(fuel=fuel, lap_time=lap_time))
            self._history = deque(samples[-self.HISTORY_SIZE:], maxlen=self.HISTORY_SIZE)
            self._recompute()
        except Exception:
            logger.exception("[FuelEnergyEngine] Failed to load fuel history from %s", filepath)

    def save_history(self, filepath: Path) -> None:
        """Persists the current history — called by TelemetryBus right after
        update() reports a new sample was recorded (`recorded=True`), never on
        every tick."""
        try:
            filepath = Path(filepath)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        except Exception:
            logger.exception("[FuelEnergyEngine] Failed to save fuel history to %s", filepath)
