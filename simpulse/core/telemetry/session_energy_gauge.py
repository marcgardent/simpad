"""
Session Energy Gauge.

Combines session progress (elapsed time and/or laps completed) with
FuelEnergyEngine's median consumption/lap-time to answer: "will the fuel/
energy in the tank right now get me to the end of THIS session?" — as
opposed to FuelEnergyEngine.estimated_laps_remaining, which only answers
"how many more laps can the tank do", with no notion of when the session
itself ends.

Single Responsibility: pure computation, no state of its own — everything it
needs is passed in on each call. Session timing data already flows through
TelemetryView (physics_view in TelemetryBus._apply_fuel_fields) with zero SDK
changes needed:
  - view.timing.current_et  — elapsed session time
  - view.grid.end_et        — session end time (None until a
                               FullScoringSession packet has resolved
                               view.grid — see _apply_fuel_fields)
  - view.timing.max_laps    — session lap limit (0 or >=1000 == unlimited,
                               same "unlimited" sentinel already used by
                               VehicleSensors.from_telem_info's remaining_laps)
  - view.total_laps         — laps completed
FuelEnergyEngine supplies estimated_consumption_per_lap and
estimated_lap_time (both medians over the last 64 laps — never a best/PB
time, which would be an unrealistically optimistic pace to project a whole
session on).
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Optional


def _is_lap_limited(max_laps: int) -> bool:
    return 0 < max_laps < 1000


@dataclass(frozen=True)
class SessionEnergyGaugeResult:
    """One tick's answer to "will I make it to the end of the session?".
    Every field is None when the session has no known length yet (practice/
    warmup with neither a lap limit nor a resolved end time) — the raw
    per-lap projection (FuelEnergyEngine.estimated_laps_remaining) stays the
    only figure available then, exactly as before this gauge existed.
    """

    time_ratio: Optional[float] = None    # elapsed / session length (time-limited only)
    lap_ratio: Optional[float] = None     # laps done / laps total (lap-limited only)
    laps_left_in_session: Optional[float] = None
    energy_needed_to_finish: Optional[float] = None
    energy_ratio: Optional[float] = None  # current level / energy_needed_to_finish (>=1.0 -> enough)

    # Raw figures backing time_ratio/lap_ratio, for display ("12:34 / 45:00",
    # "8 / 20") rather than just the percentage — None where the ratio itself
    # is None (time_total/laps_total), always present otherwise.
    time_elapsed: float = 0.0
    time_total: Optional[float] = None
    laps_done: int = 0
    laps_total: Optional[int] = None


def compute_session_energy_gauge(
    current_et: float,
    end_et: float,
    max_laps: int,
    total_laps: int,
    energy_level: float,
    median_consumption_per_lap: float,
    median_lap_time: float,
) -> SessionEnergyGaugeResult:
    """See SessionEnergyGaugeResult's docstring.

    A session can be lap-limited, time-limited, or both at once (e.g. "45
    minutes or 10 laps, whichever comes first") — when both limits are known,
    laps_left_in_session takes the smaller (more constraining) of the two
    independent estimates, since that's the one that will actually end the
    session first.
    """
    is_lap_limited = _is_lap_limited(max_laps)
    is_time_limited = end_et > 0.0

    time_ratio = current_et / end_et if is_time_limited else None
    lap_ratio = total_laps / max_laps if is_lap_limited else None

    laps_left_by_laps: Optional[float] = max(0.0, float(max_laps - total_laps)) if is_lap_limited else None
    laps_left_by_time: Optional[float] = None
    if is_time_limited and median_lap_time > 0.0:
        time_left = max(0.0, end_et - current_et)
        laps_left_by_time = float(ceil(time_left / median_lap_time))

    if laps_left_by_laps is not None and laps_left_by_time is not None:
        laps_left_in_session = min(laps_left_by_laps, laps_left_by_time)
    else:
        laps_left_in_session = laps_left_by_laps if laps_left_by_laps is not None else laps_left_by_time

    energy_needed_to_finish: Optional[float] = None
    energy_ratio: Optional[float] = None
    if laps_left_in_session is not None and median_consumption_per_lap > 0.0:
        energy_needed_to_finish = laps_left_in_session * median_consumption_per_lap
        if energy_needed_to_finish > 0.0:
            energy_ratio = energy_level / energy_needed_to_finish

    return SessionEnergyGaugeResult(
        time_ratio=time_ratio,
        lap_ratio=lap_ratio,
        laps_left_in_session=laps_left_in_session,
        energy_needed_to_finish=energy_needed_to_finish,
        energy_ratio=energy_ratio,
        time_elapsed=max(0.0, current_et),
        time_total=end_et if is_time_limited else None,
        laps_done=max(0, total_laps),
        laps_total=max_laps if is_lap_limited else None,
    )
