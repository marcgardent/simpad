"""
SimPulse SDK — Scoring & Grid Telemetry Models.
Defines BaseTimingState (common continuous timing) and FullGridScoringState (extended multi-car session).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from isimotor_rawudp_client import VehicleScoring


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
