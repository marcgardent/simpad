"""
SimPulse SDK — Unified Timing Domain Model (TimeStatus).

Single model of "where am I versus the references I know about" — see
TIME_STATUS_SPEC.md at the repo root for the full rationale. Replaces the flat
expected_sectorN_*/sector1_status/sector1_delta/etc. fields historically spread
across ``LapDeltaPacket``/``VehicleSensors`` and the three overlapping colour
enums (``SplitStatus``, ``LapColorStatus``, ``ExpectedStatus``) with:

- ``TimeLap``: a frozen chrono (per-sector + total), no delta/colour — the raw
  fact of one reference lap (mine, paddock, or all-time).
- ``WallOfFameTimes``: the three references known at a given instant.
- ``TimeTarget``: which SESSION-scoped reference is currently beaten (the
  single source of truth for colour — see its docstring for why "all-time" is
  deliberately NOT a member).
- ``TimeStatus``: the per-tick projection (lap + 3 sectors) plugins consume.
- ``resolve_target`` / ``resolve_is_personal_record_target``: the two
  independent resolution rules (never merged — see their docstrings).

Everything here is ``@dataclass(frozen=True)``, plugin-facing, and free of I/O:
only getters/formatters, same style as ``ReferenceLapProfileView``. The actual
computation (WallOfFameEngine, DeltaEngine) lives in Core.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Tuple

from simpulse_sdk.models.math import format_lap_time, format_sector_time

SectorKey = Literal["total", "sector1", "sector2", "sector3"]


@dataclass(frozen=True)
class TimeLap:
    """A frozen chrono: per-sector times + total. Nothing else — no delta, no
    colour. This is the raw data of one reference lap (mine, the paddock's, or
    all-time), before any comparison is made against it."""
    sector1: float = 0.0
    sector2: float = 0.0
    sector3: float = 0.0
    total: float = 0.0

    @property
    def is_valid(self) -> bool:
        return 0.0 < self.total < 999900.0

    @property
    def total_str(self) -> str:
        return format_lap_time(self.total)

    @property
    def sector1_str(self) -> str:
        return format_sector_time(self.sector1)

    @property
    def sector2_str(self) -> str:
        return format_sector_time(self.sector2)

    @property
    def sector3_str(self) -> str:
        return format_sector_time(self.sector3)


class TimeTarget(str, Enum):
    """Which SESSION-scoped reference is currently beaten — the SOLE source of
    truth for colour, replacing ``SplitStatus``/``LapColorStatus``/
    ``ExpectedStatus``. Ascending order = display priority (the strongest
    wins). Deliberately separate from the colour itself (see the "Résolution
    couleur" table in TIME_STATUS_SPEC.md): the domain states WHAT is true,
    the view decides how to paint it.

    NO ``ALLTIME`` member here (a mistake in the spec's first draft): my
    all-time-best and the paddock-best are NOT two levels of one total order —
    nothing guarantees paddock <= all-time (the paddock can well be slower
    than my own record). Coding them into the same enum created a collision:
    it could not represent "I beat the paddock AND my own record" (two
    independent facts) with a single value that can only carry one at a time.
    "Beats my all-time-best" is orthogonal to the session colour — see
    ``is_personal_record_target`` below, resolved separately, never mixed
    into ``target``.
    ``INVALID`` is deliberately absent too: a cut lap/sector already has its
    own sound/visual indicator elsewhere; that is out of scope here and
    ``target`` must not be used to hide delta/expected.
    """
    NONE = "none"          # nothing to compare (no reference loaded) -> white
    BEHIND = "behind"      # reference(s) known, but none beaten -> yellow
    SESSION = "session"    # beats MY SESSION BEST -> green
    PADDOCK = "paddock"    # beats PADDOCK BEST -> purple


@dataclass(frozen=True)
class TimeSectorViewModel:
    target: TimeTarget = TimeTarget.NONE
    expected_time: float = 0.0   # projection = active reference + live delta
    delta_time: float = 0.0      # current delta vs active reference
    is_current: bool = False     # this sector is the one in progress (vs already frozen)
    # Independent fact from `target` (see TimeTarget docstring) — never
    # derived from it, always resolved separately via
    # resolve_is_personal_record_target().
    is_personal_record_target: bool = False

    @property
    def expected_time_str(self) -> str:
        return format_sector_time(self.expected_time)

    @property
    def delta_str(self) -> str:
        if self.delta_time < -0.0001:
            return f"-{abs(self.delta_time):.3f}"
        elif self.delta_time > 0.0001:
            return f"+{self.delta_time:.3f}"
        return "--"


@dataclass(frozen=True)
class TimeLapViewModel:
    target: TimeTarget = TimeTarget.NONE
    expected_time: float = 0.0
    delta_time: float = 0.0
    is_personal_record_target: bool = False   # idem, independent of target

    @property
    def expected_time_str(self) -> str:
        return format_lap_time(self.expected_time)

    @property
    def delta_str(self) -> str:
        if self.delta_time < -0.0001:
            return f"-{abs(self.delta_time):.3f}"
        elif self.delta_time > 0.0001:
            return f"+{self.delta_time:.3f}"
        return "--"


@dataclass(frozen=True)
class WallOfFameTimes:
    """The three references known at instant T. One TimeLap per reference —
    no status/colour in here, these are FACTS, not a view."""
    my_best_all_time: TimeLap = field(default_factory=TimeLap)
    my_best_session: TimeLap = field(default_factory=TimeLap)
    paddock_session_best: TimeLap = field(default_factory=TimeLap)


@dataclass(frozen=True)
class TimeStatus:
    """THE model DeltaEngine produces every tick and plugins consume. Replaces
    every expected_sectorN_*/expected_lap_is_pr/sector1_status/etc. flat field
    of LapDeltaPacket/VehicleSensors.

    ``lap``/``sectors`` are the live PROJECTION (target/expected/delta at the
    current instant) — ``wall_of_fame`` is the raw, un-projected reference
    data behind them (e.g. "MY SESSION BEST: 1:32.450", independent of
    whether the current lap beats it). Both live on the same model because a
    display that shows a reference clock verbatim (not just its target
    colour) needs the actual TimeLap, not just the resolved TimeTarget —
    see ``WallOfFameTimes``/``TimeLap.total_str``.
    """
    lap: TimeLapViewModel = field(default_factory=TimeLapViewModel)
    sectors: Tuple[TimeSectorViewModel, TimeSectorViewModel, TimeSectorViewModel] = field(
        default_factory=lambda: (TimeSectorViewModel(), TimeSectorViewModel(), TimeSectorViewModel())
    )
    wall_of_fame: WallOfFameTimes = field(default_factory=WallOfFameTimes)

    @property
    def sector1(self) -> TimeSectorViewModel:
        return self.sectors[0]

    @property
    def sector2(self) -> TimeSectorViewModel:
        return self.sectors[1]

    @property
    def sector3(self) -> TimeSectorViewModel:
        return self.sectors[2]


def _valid(value: float) -> bool:
    return 0.0 < value < 999900.0


def resolve_target(
    current: float,
    wof: WallOfFameTimes,
    key: SectorKey,
    eps: float,
) -> TimeTarget:
    """Priority: PADDOCK > SESSION > BEHIND > NONE. NEVER looks at
    ``wof.my_best_all_time`` — see ``resolve_is_personal_record_target``.

    ``eps`` is a mandatory parameter, not a domain constant (see
    TIME_STATUS_SPEC.md "eps"): the equality tolerance that makes sense for a
    driver ("do I consider this tied = beaten") is a display decision, always
    supplied by the caller (the cockpit HUD plugin, via its config).
    """
    if not _valid(current):
        return TimeTarget.NONE

    paddock = getattr(wof.paddock_session_best, key)
    session = getattr(wof.my_best_session, key)

    paddock_known = _valid(paddock)
    session_known = _valid(session)

    if paddock_known and current <= paddock + eps:
        return TimeTarget.PADDOCK
    if session_known and current <= session + eps:
        return TimeTarget.SESSION
    if paddock_known or session_known:
        return TimeTarget.BEHIND
    return TimeTarget.NONE


def resolve_is_personal_record_target(
    current: float,
    wof: WallOfFameTimes,
    key: SectorKey,
    eps: float,
) -> bool:
    """Independent of ``resolve_target``. Looks ONLY at ``wof.my_best_all_time``.

    Strict ``<`` (not ``<=``): at the exact instant ``current == ever`` (e.g.
    all-time-best mode, delta == 0 at the very start of a lap), the record is
    NOT yet beaten — an inclusive comparison would flag "PR" by default before
    the driver has proven anything.
    """
    if not _valid(current):
        return False
    ever = getattr(wof.my_best_all_time, key)
    if not _valid(ever):
        return False
    return current < ever - eps


__all__ = [
    "TimeLap",
    "TimeTarget",
    "TimeSectorViewModel",
    "TimeLapViewModel",
    "TimeStatus",
    "WallOfFameTimes",
    "resolve_target",
    "resolve_is_personal_record_target",
]
