"""
SimPulse SDK — Lap Delta & Timing Models.
Defines strongly-typed LapDeltaPacket, SectorInfo, and DeltaReferenceMode.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Dict


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

    # TODO MGT pas faire des user Exit avec des Dictionnaires, les consomateurs doivent connaitre les types
    def to_dict(self) -> Dict[str, object]:
        return {
            "live_delta": self.live_delta,
            "display_delta": self.display_delta,
            "delta_str": self.delta_str,
            "has_reference": self.has_reference,
            "reference_mode": self.reference_mode.value,
            "ref_lap_time": self.ref_lap_time,
            "ref_lap_time_str": self.ref_lap_time_str,
            "estimated_lap_time": self.estimated_lap_time,
            "estimated_lap_time_str": self.estimated_lap_time_str,
            "current_sector": self.current_sector,
            "sector1_delta": self.sector1_delta,
            "sector2_delta": self.sector2_delta,
            "sector3_delta": self.sector3_delta,
            "sector1_time": self.sector1_time,
            "sector1_status": self.sector1_status,
            "sector2_time": self.sector2_time,
            "sector2_status": self.sector2_status,
            "sector3_time": self.sector3_time,
            "sector3_status": self.sector3_status,
            "sectors_list": [asdict(s) for s in self.sectors_list],
            "last_lap_time": self.last_lap_time,
            "last_lap_time_str": self.last_lap_time_str,
            "last_lap_status": self.last_lap_status,
            "is_lap_freeze_active": self.is_lap_freeze_active,
            "lap_flag": self.lap_flag,
            "is_pit_lap": self.is_pit_lap,
            "track_name": self.track_name,
            "track_length": self.track_length,
            "player_dist": self.player_dist,
            "vehicle_name": self.vehicle_name,
            "vehicle_class": self.vehicle_class,
            "timestamp": self.timestamp,
        }
