"""
SimPulse Telemetry — Wall Of Fame Engine.

Sole job: keep ``WallOfFameTimes`` (the three references TimeStatus compares
against — my all-time best, my session best, the paddock's session best) up
to date. Factored out of ``DeltaEngine`` (same pattern as ``SectorEngine``,
extracted from it two sessions ago) so it is testable in isolation: pure
state + arithmetic, no scoring-packet parsing, no disk I/O — ``DeltaEngine``
feeds it already-extracted scalars/TimeLaps and owns the actual
save/load-from-disk calls.

Regroups, behind one component:
  * ``DeltaEngine._all_time_best_lap_time``/``_all_time_best_profile``
  * ``DeltaEngine._game_session_best_lap_time`` (the game's own authoritative
    report) and ``DeltaEngine._session_best_lap_time`` (our own capture,
    fallback when the game hasn't reported yet — same "tighter of the two"
    rule as the historical ``_session_lap_bound``)
  * ``DeltaEngine._paddock_best_lap``/``_paddock_cum_s1``/``_paddock_cum_s2``
    (paddock lap — excludes the player, same ``_is_player`` filter)

Deliberately does NOT reuse ``SectorEngine.session_split_best_s1/s2/s3`` for
the paddock splits: those are computed over paddock+self (no ``_is_player``
filter — see ``SectorEngine.update_session_bests``), so comparing a live
sector against them would make ``target=PADDOCK`` trivially true against your
own best split. This engine computes its own paddock-only aggregation for
sector splits, mirroring the player-exclusion already used for
``_paddock_best_lap``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Self, Union

from isimotor_rawudp_client import VehicleScoring
from simpulse_sdk.models.timing import TimeLap, WallOfFameTimes
from .reference_profile import ReferenceLapProfile

_UNKNOWN = 999900.0

# The two — and only two — raw shapes a scoring packet's vehicle grid ever
# arrives as: a typed isimotor_rawudp_client object (FullScoringSession.vehicles)
# or a legacy raw-JSON dict (mVehicles). See VehicleBests.build below, the one
# sanctioned place allowed to branch on which.
RawScoringVehicle = Union[VehicleScoring, dict]


@dataclass(frozen=True)
class VehicleBests:
    """Normalized best-splits/lap facts for one scoring vehicle — built once,
    at the boundary, by ``build()`` below. Past that boundary, WallOfFameEngine
    works only with these plain typed attributes; no isinstance()/getattr()
    scattered through the paddock-scan business logic."""
    is_player: bool = False
    best_sector1: float = 0.0
    best_sector2: float = 0.0
    best_lap_time: float = 0.0

    @classmethod
    def build(cls, vehicle: RawScoringVehicle) -> Self:
        """Factory — the ONLY place allowed to branch on the raw vehicle
        shape (see scripts/lint_oop_evil.py: isinstance() is sanctioned
        inside a Factory, nowhere else)."""
        if isinstance(vehicle, dict):
            return cls._build_from_dict(vehicle)
        return cls._build_from_scoring(vehicle)

    @classmethod
    def _build_from_dict(cls, vehicle: dict) -> Self:
        is_player = vehicle.get("mIsPlayer", vehicle.get("isPlayer", vehicle.get("is_player")))
        if is_player is None:
            control = vehicle.get("mControl", vehicle.get("control", 1))
            is_player = int(control) == 0
        return cls(
            is_player=bool(is_player),
            best_sector1=float(vehicle.get("mBestSector1", vehicle.get("bestSector1", 0.0)) or 0.0),
            best_sector2=float(vehicle.get("mBestSector2", vehicle.get("bestSector2", 0.0)) or 0.0),
            best_lap_time=float(vehicle.get("mBestLapTime", vehicle.get("bestLapTime", 0.0)) or 0.0),
        )

    @classmethod
    def _build_from_scoring(cls, vehicle: VehicleScoring) -> Self:
        return cls(
            is_player=bool(vehicle.is_player) or vehicle.control == 0,
            best_sector1=float(vehicle.best_sector1 or 0.0),
            best_sector2=float(vehicle.best_sector2 or 0.0),
            best_lap_time=float(vehicle.best_lap_time or 0.0),
        )


def _decompose(sector_1_time: float, sector_2_time: float, total: float) -> TimeLap:
    """Splits cumulative loop clocks (sector_1_time, sector_2_time, total) into
    standalone S1/S2/S3 — same rule as DeltaEngine._individual_sector_splits.
    Any split that can't be derived (missing / not strictly increasing) is 0.0."""
    s1c = float(sector_1_time or 0.0)
    s2c = float(sector_2_time or 0.0)
    lap = float(total or 0.0)
    s1 = s1c if s1c > 0.0 else 0.0
    s2 = (s2c - s1c) if (s2c > 0.0 and s1c > 0.0 and s2c > s1c) else 0.0
    s3 = (lap - s2c) if (lap > 0.0 and s2c > 0.0 and lap > s2c) else 0.0
    return TimeLap(sector1=s1, sector2=s2, sector3=s3, total=lap)


class WallOfFameEngine:
    """Tracks the three references of ``WallOfFameTimes`` for one active
    session/track/car. Pure state — see module docstring."""

    def __init__(self) -> None:
        self.reset_session()

    def reset_session(self) -> None:
        """Track/car change: clears session + all-time state. All-time is
        reloaded right after via ``load_all_time_from_disk`` (mirrors
        DeltaEngine's track-change handling: reset then reload)."""
        self._all_time: TimeLap = TimeLap()
        self._my_session: TimeLap = TimeLap()
        self._game_session_best_total: float = 0.0
        self._paddock_best_lap: float = _UNKNOWN
        self._paddock_cum_s1: float = _UNKNOWN
        self._paddock_cum_s2: float = _UNKNOWN
        self._paddock_known: bool = False

    def load_all_time_from_disk(self, profile: Optional[ReferenceLapProfile]) -> None:
        """Sets the all-time-best reference from a loaded/cleared
        ``ReferenceLapProfile`` (``None`` clears it — no reference on disk for
        this track/car yet)."""
        if profile is None:
            self._all_time = TimeLap()
            return
        self._all_time = _decompose(profile.sector_1_time, profile.sector_2_time, profile.lap_time)

    def update_from_lap_completed(self, lap: TimeLap, is_valid: bool) -> None:
        """Feeds one just-finalized lap. Updates my-session-best and
        all-time-best independently (each "if strictly better"), same as
        DeltaEngine._finalize_completed_lap's two parallel blocks. Not gated
        on disk persistence — that stays DeltaEngine's job."""
        if not is_valid or not lap.is_valid:
            return
        if not self._my_session.is_valid or lap.total < self._my_session.total:
            self._my_session = lap
        if not self._all_time.is_valid or lap.total < self._all_time.total:
            self._all_time = lap

    def update_from_scoring(self, game_best_lap_time: float, vehicles_src: list[RawScoringVehicle]) -> None:
        """Feeds one scoring packet: the game's own authoritative best-lap
        report for the player (always current, unlike our own capture — see
        module docstring) and the full vehicle grid (paddock scan, empty for
        CompactScoring which only ever lists the player)."""
        if 0.0 < game_best_lap_time < _UNKNOWN:
            self._game_session_best_total = game_best_lap_time

        if not vehicles_src:
            return

        min_other_lap = _UNKNOWN
        min_other_s1 = _UNKNOWN
        min_other_s2 = _UNKNOWN
        for raw_vehicle in vehicles_src:
            bests = VehicleBests.build(raw_vehicle)
            if bests.is_player:
                continue
            if 0.0 < bests.best_lap_time < min_other_lap:
                min_other_lap = bests.best_lap_time
            # Cumulative loop clocks from a *coherent* timed lap of that rival.
            if bests.best_sector1 > 0.0 and bests.best_sector2 > bests.best_sector1:
                if bests.best_sector1 < min_other_s1:
                    min_other_s1 = bests.best_sector1
                if bests.best_sector2 < min_other_s2:
                    min_other_s2 = bests.best_sector2
        if min_other_lap < _UNKNOWN:
            self._paddock_best_lap = min_other_lap
            self._paddock_known = True
            self._paddock_cum_s1 = min_other_s1
            self._paddock_cum_s2 = min_other_s2

    def _session_total(self) -> float:
        """Tighter of the game's own report and our own capture — see
        DeltaEngine._session_lap_bound (the historical equivalent)."""
        game = self._game_session_best_total if _UNKNOWN > self._game_session_best_total > 0.0 else None
        ours = self._my_session.total if self._my_session.is_valid else None
        if game is not None and ours is not None:
            return min(game, ours)
        if game is not None:
            return game
        if ours is not None:
            return ours
        return 0.0

    def snapshot(self) -> WallOfFameTimes:
        """Point-in-time read of the three references."""
        session_total = self._session_total()
        my_best_session = self._my_session
        if session_total > 0.0 and session_total != self._my_session.total:
            # Game reports a tighter (or the only known) total than our own
            # capture — surface it even without a matching sector breakdown
            # (same historical mismatch as _session_lap_bound vs
            # _session_best_profile: two different sources for the same fact).
            my_best_session = TimeLap(
                sector1=self._my_session.sector1,
                sector2=self._my_session.sector2,
                sector3=self._my_session.sector3,
                total=session_total,
            )

        paddock = TimeLap()
        if self._paddock_known and self._paddock_best_lap < _UNKNOWN:
            paddock = _decompose(self._paddock_cum_s1, self._paddock_cum_s2, self._paddock_best_lap)

        return WallOfFameTimes(
            my_best_all_time=self._all_time,
            my_best_session=my_best_session,
            paddock_session_best=paddock,
        )


__all__ = ["WallOfFameEngine"]
