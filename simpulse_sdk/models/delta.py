"""
SimPulse SDK — Lap Delta & Timing Models.
Defines strongly-typed LapDeltaPacket, SectorInfo, and DeltaReferenceMode.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List


class DeltaReferenceMode(str, Enum):
    """Reference modes for delta calculation."""
    ALL_TIME_BEST = "all_time_best"
    SESSION_BEST = "session_best"
    STINT_BEST = "stint_best"
    LAST_LAP = "last_lap"


@dataclass(frozen=True)
class SectorInfo:
    """Strongly-typed sector checkpoint information."""
    time: str = "--"
    status: str = "default"
    delta: float = 0.0
    delta_str: str = "--"
    is_current: bool = False


@dataclass(frozen=True)
class LapDeltaPacket:
    """
    Strongly-typed data packet representing authoritative lap timing, delta, and sector states.
    Dispatched to all IDeltaSubscriber plugins and UI components.
    """
    live_delta: float = 0.0
    display_delta: float = 0.0
    delta_str: str = "--:--.---"
    has_reference: bool = False
    reference_mode: DeltaReferenceMode = DeltaReferenceMode.ALL_TIME_BEST
    ref_lap_time: float = 0.0
    ref_lap_time_str: str = "--:--.---"
    estimated_lap_time: float = 0.0
    estimated_lap_time_str: str = "--:--.---"
    expected_status: str = "white"   # unified colour of the projected/expected lap
    current_sector: int = 1
    sector1_delta: float = 0.0
    sector2_delta: float = 0.0
    sector3_delta: float = 0.0
    sector1_time: str = "--"
    sector1_status: str = "default"
    sector2_time: str = "--"
    sector2_status: str = "default"
    sector3_time: str = "--"
    sector3_status: str = "default"
    sectors_list: List[SectorInfo] = field(default_factory=list)
    last_lap_time: float = 0.0
    last_lap_time_str: str = "--:--.---"
    last_lap_status: str = "default"
    is_lap_freeze_active: bool = False
    lap_flag: int = 2
    is_pit_lap: bool = False
    track_name: str = ""
    track_length: float = 0.0
    player_dist: float = 0.0
    vehicle_name: str = ""
    vehicle_class: str = ""
    timestamp: float = field(default_factory=time.time)
