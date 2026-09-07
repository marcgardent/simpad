"""
SimPulse SDK — Scoring & Grid Telemetry Models.
Defines BaseTimingState (common continuous timing) and FullGridScoringState (extended multi-car session).
"""

from __future__ import annotations
from dataclasses import dataclass, field, fields
from typing import List, Tuple, Optional, Protocol
from isimotor_rawudp_client import VehicleScoring


class LapTimingSource(Protocol):
    """
    Structural type for the one merge point shared by CompactScoring (10Hz)
    and FullScoringSession.player_vehicle (a VehicleScoring, 2-5Hz) — both
    isiMotor packets happen to expose this exact same field subset for lap/
    sector timing. `BaseTimingState.merge()` is the single place allowed to
    read it; TelemetryStateStore.update_compact_scoring/update_full_scoring
    must never duplicate this field-by-field mapping themselves again.
    """
    total_laps: int
    in_garage_stall: bool
    count_lap_flag: int
    cur_sector1: float
    cur_sector2: float
    last_sector1: float
    last_sector2: float
    last_lap_time: float
    best_sector1: float
    best_sector2: float
    best_lap_time: float


@dataclass
class BaseTimingState:
    """
    Unified common session and player timing state.
    Guaranteed continuous at 10Hz, source of truth for HUD, timing, and DeltaEngine.
    """
    track_name: str = ""
    session: int = 0
    current_et: float = 0.0
    track_length: float = 0.0        # Disambiguated from vehicle lap_dist (meters)
    max_laps: int = 0
    in_realtime: bool = True

    # Player Lap & Sector Status
    total_laps: int = 0
    sector: int = 1                  # Normalized to 1, 2, or 3 (0 in raw isiMotor -> 3)
    in_garage: bool = False
    count_lap_flag: int = 2          # 0=invalid, 1=lap count only, 2=valid
    is_lap_valid: bool = True

    # Player Sector & Lap Times (Cumulative & Standalone)
    cur_sector1: float = 0.0
    cur_sector2: float = 0.0         # Cumulative S1 + S2
    last_sector1: float = 0.0
    last_sector2: float = 0.0        # Cumulative S1 + S2
    last_lap_time: float = 0.0
    best_sector1: float = 0.0
    best_sector2: float = 0.0        # Cumulative S1 + S2
    best_lap_time: float = 0.0

    @property
    def cur_sector2_individual(self) -> float:
        """Standalone duration of current Sector 2 (cur_s2 - cur_s1)."""
        return max(0.0, self.cur_sector2 - self.cur_sector1) if self.cur_sector2 > 0 and self.cur_sector1 > 0 else 0.0

    @property
    def last_sector2_individual(self) -> float:
        """Standalone duration of last lap Sector 2."""
        return max(0.0, self.last_sector2 - self.last_sector1) if self.last_sector2 > 0 and self.last_sector1 > 0 else 0.0

    @property
    def last_sector3_individual(self) -> float:
        """Standalone duration of last lap Sector 3 (last_lap_time - last_s2)."""
        return max(0.0, self.last_lap_time - self.last_sector2) if self.last_lap_time > 0 and self.last_sector2 > 0 else 0.0

    @property
    def best_sector2_individual(self) -> float:
        """Standalone duration of best lap Sector 2."""
        return max(0.0, self.best_sector2 - self.best_sector1) if self.best_sector2 > 0 and self.best_sector1 > 0 else 0.0

    @property
    def is_race(self) -> bool:
        """True if current session is race."""
        return 10 <= self.session <= 13

    @property
    def is_qualifying(self) -> bool:
        """True if current session is qualifying."""
        return 5 <= self.session <= 8

    @classmethod
    def merge(
        cls,
        *,
        track_name: str,
        session: int,
        current_et: float,
        track_length: float,
        max_laps: int,
        in_realtime: bool,
        sector: int,
        lap_source: LapTimingSource,
    ) -> "BaseTimingState":
        """
        THE single merge point for BaseTimingState, from either raw source.

        This exists because CompactScoring (10Hz) and FullScoringSession's
        player_vehicle (2-5Hz VehicleScoring) both carry the full lap/sector
        timing subset under the exact same field names — a coincidence of the
        isiMotor wire format, not something either call site should encode
        for itself. Before this method, update_compact_scoring() and
        update_full_scoring() each rebuilt BaseTimingState by hand: two
        15-field literals that had to be kept in lockstep by eye. That's the
        actual trap — a field added/renamed in one path and forgotten in the
        other silently desyncs `timing` depending on which packet happened to
        arrive last, with no test catching it (both paths produce a valid
        BaseTimingState, just with different data). Session-level fields
        (track_name/session/current_et/track_length/max_laps/in_realtime) and
        the already-normalized `sector` are NOT part of that shared subset —
        callers resolve those themselves (they differ: CompactScoring is
        session-scoped, FullScoringSession needs its player_vehicle resolved
        first) and pass them in explicitly.
        """
        return cls(
            track_name=track_name.strip(),
            session=session,
            current_et=current_et,
            track_length=track_length,
            max_laps=max_laps,
            in_realtime=in_realtime,
            total_laps=lap_source.total_laps,
            sector=sector,
            in_garage=lap_source.in_garage_stall,
            count_lap_flag=lap_source.count_lap_flag,
            is_lap_valid=(lap_source.count_lap_flag == 2),
            cur_sector1=lap_source.cur_sector1,
            cur_sector2=lap_source.cur_sector2,
            last_sector1=lap_source.last_sector1,
            last_sector2=lap_source.last_sector2,
            last_lap_time=lap_source.last_lap_time,
            best_sector1=lap_source.best_sector1,
            best_sector2=lap_source.best_sector2,
            best_lap_time=lap_source.best_lap_time,
        )


@dataclass
class FullGridScoringState(BaseTimingState):
    """
    Extended multi-car grid, environmental conditions, and official race control state.
    Updated at 2-5Hz.
    """
    # Extended Session & Flags
    end_et: float = 0.0
    game_phase: int = 5
    yellow_flag_state: int = 0
    sector_flags: Tuple[int, int, int] = (0, 0, 0)
    start_light: int = 0
    num_red_lights: int = 0
    is_fcy: bool = False

    # Weather & Track Surface
    ambient_temp: float = 0.0
    track_temp: float = 0.0
    dark_cloud: float = 0.0
    raining: float = 0.0
    avg_path_wetness: float = 0.0
    min_path_wetness: float = 0.0
    max_path_wetness: float = 0.0

    # LMU Rules
    track_limits_steps_per_point: int = 3
    track_limits_steps_per_penalty: int = 12

    # Player Vehicle Specifics (Full only)
    driver_name: str = ""
    vehicle_name: str = ""
    vehicle_class: str = ""
    place: int = 1
    qualification: int = 0
    finish_status: int = 0
    num_pitstops: int = 0
    num_penalties: int = 0
    track_limits_steps: int = 0
    in_pits: bool = False
    pit_state: int = 0
    time_behind_leader: float = 0.0
    time_behind_next: float = 0.0
    laps_behind_leader: int = 0
    laps_behind_next: int = 0
    lap_start_et: float = 0.0
    time_into_lap: float = 0.0
    estimated_lap_time: float = 0.0
    car_lap_dist: float = 0.0

    # Grid & Multi-vehicle
    num_vehicles: int = 0
    vehicles: List[VehicleScoring] = field(default_factory=list)
    leaderboard: List[VehicleScoring] = field(default_factory=list)
    player_vehicle: Optional[VehicleScoring] = None

    @classmethod
    def from_timing(cls, timing: BaseTimingState, **full_only_fields) -> "FullGridScoringState":
        """
        Builds a FullGridScoringState from an already-merged BaseTimingState
        (see `BaseTimingState.merge`) plus the fields only FullScoringSession
        carries. The shared timing subset is read back off `timing` field by
        field, not retyped as a second literal here — the previous version of
        update_full_scoring() built `self.timing` and `self.grid` as two
        independent ~15-field literals that had to be kept identical by eye.
        """
        common = {f.name: getattr(timing, f.name) for f in fields(BaseTimingState)}
        return cls(**common, **full_only_fields)

    def sync_lap_timing(self, timing: BaseTimingState) -> None:
        """
        In-place sync of this grid's inherited BaseTimingState fields from a
        freshly merged `timing`. Used when a CompactScoring tick (10Hz)
        arrives between two FullScoringSession ticks (2-5Hz): the grid keeps
        its Full-only fields (weather, penalties, leaderboard, …) untouched
        but its shared timing fields track the latest tick instead of going
        stale until the next FullScoringSession. Iterates BaseTimingState's
        own fields, so a field added there is picked up here automatically —
        no second hand-maintained field list to forget.
        """
        for f in fields(BaseTimingState):
            setattr(self, f.name, getattr(timing, f.name))
