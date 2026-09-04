"""
SimPad Central Telemetry State Store.
Maintains in-memory the latest known frame for each ISI / LMU UDP telemetry channel,
tracks packet timestamps & freshness, and exposes a unified, consistent vehicle and session state.
"""

from __future__ import annotations
import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union


class TelemetryWakeReason(Enum):
    """Specifies which UDP channel / event woke up the processing pipeline."""
    PHYSICS_TICK = "physics_tick"              # TelemInfo (120Hz)
    OPPONENTS_TICK = "opponents_tick"          # Opponent TelemInfo (10-20Hz)
    SCORING_UPDATE = "scoring_update"          # CompactScoring (10Hz)
    GRID_UPDATE = "grid_update"                # FullScoringSession (2-5Hz)
    WEATHER_UPDATE = "weather_update"          # WeatherControl (1-2Hz)
    SYSTEM_EVENT = "session_event"             # SystemEvents
    STATE_CHANGE = "state_change"              # ExtendedState / Graphics / FFB
    MANUAL_EVALUATION = "manual_evaluation"    # Triggered manually / in tests


@dataclass
class PacketSlot:
    """A slot holding the latest received raw data packet and its arrival timestamp."""
    data: Any = None
    timestamp: float = 0.0
    sequence_id: int = 0

    @property
    def age_sec(self) -> float:
        """Returns age of the cached packet in seconds."""
        if self.timestamp <= 0.0:
            return 999999.0
        return max(0.0, time.time() - self.timestamp)

    def is_fresh(self, max_age_sec: float = 1.0) -> bool:
        """Returns True if the cached packet was received within max_age_sec."""
        return self.data is not None and self.age_sec <= max_age_sec

    def update(self, data: Any, timestamp: Optional[float] = None) -> None:
        """Updates slot with new packet data."""
        self.data = data
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.sequence_id += 1


class TelemetryStateStore:
    """
    Thread-safe Central Telemetry State Store.
    Preserves the latest known frame for every telemetry channel and provides
    unified cross-channel vehicle state without stale defaults or race conditions.
    """
    _instance: Optional["TelemetryStateStore"] = None
    _lock = threading.RLock()

    def __init__(self):
        self._mutex = threading.RLock()
        self.telemetry = PacketSlot()          # Player TelemInfo (120Hz)
        self.opponent_telemetry = PacketSlot() # Opponent TelemInfo
        self.compact_scoring = PacketSlot()    # CompactScoring (10Hz)
        self.full_scoring = PacketSlot()       # FullScoringSession (2-5Hz)
        self.weather = PacketSlot()            # WeatherControl (1-2Hz)
        self.system = PacketSlot()             # SystemEvents
        self.extended_state = PacketSlot()     # ExtendedState

        # Persistent state memory across packet boundaries
        self._last_wheels_on_track: int = 4
        self._last_is_on_track: bool = True
        self._last_surface_types: Tuple[int, ...] = (0, 0, 0, 0)
        self._last_terrain_names: Tuple[str, ...] = ("", "", "", "")
        self._last_penalties: int = 0
        self._last_track_limits_steps: int = 0
        self._last_steps_per_point: int = 3
        self._last_steps_per_penalty: int = 12
        self._last_lap_flag: Optional[int] = None
        self._is_lap_valid: bool = True
        self._is_lap_invalid: bool = False
        self._lap_timing_status: str = "timing_in_progress"
        self._last_validity_event: str = "IDLE"
        self._last_validity_event_time: float = 0.0
        self._validity_transition: Optional[str] = None
        self._was_in_garage: bool = False
        self._last_current_sector: int = 1
        self._last_total_laps: int = 0
        self._last_speed_kmh: float = 0.0
        self._last_throttle_pct: float = 0.0
        self._last_brake_pct: float = 0.0
        self._last_in_realtime: bool = True
        self._last_in_garage: bool = False
        self._last_gear: int = 0
        self._last_engine_rpm: float = 0.0
        self._last_engine_max_rpm: float = 7500.0
        self._last_fuel: float = 0.0
        self._last_lap_dist: float = 0.0
        self._last_time_into_lap: float = 0.0
        self._last_grips: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)

    @classmethod
    def get_instance(cls) -> "TelemetryStateStore":
        """Singleton accessor for global telemetry state store."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def reset(self) -> None:
        """Resets all packet slots and persistent state memory."""
        with self._mutex:
            self.telemetry = PacketSlot()
            self.opponent_telemetry = PacketSlot()
            self.compact_scoring = PacketSlot()
            self.full_scoring = PacketSlot()
            self.weather = PacketSlot()
            self.system = PacketSlot()
            self.extended_state = PacketSlot()

            self._last_wheels_on_track = 4
            self._last_is_on_track = True
            self._last_surface_types = (0, 0, 0, 0)
            self._last_terrain_names = ("", "", "", "")
            self._last_penalties = 0
            self._last_track_limits_steps = 0
            self._last_steps_per_point = 3
            self._last_steps_per_penalty = 12
            self._last_lap_flag = None
            self._is_lap_valid = True
            self._is_lap_invalid = False
            self._lap_timing_status = "timing_in_progress"
            self._last_validity_event = "IDLE"
            self._last_validity_event_time = 0.0
            self._validity_transition = None
            self._was_in_garage = False
            self._last_current_sector = 1
            self._last_total_laps = 0
            self._last_speed_kmh = 0.0
            self._last_throttle_pct = 0.0
            self._last_brake_pct = 0.0
            self._last_in_realtime = True
            self._last_in_garage = False
            self._last_gear = 0
            self._last_engine_rpm = 0.0
            self._last_engine_max_rpm = 7500.0
            self._last_fuel = 0.0
            self._last_lap_dist = 0.0
            self._last_time_into_lap = 0.0
            self._last_grips = (1.0, 1.0, 1.0, 1.0)

    def _process_lap_validity(self, raw_flag: Any, timestamp: Optional[float] = None) -> None:
        """
        Authoritative 100% stateless lap validity & timing transition processor:
        - Maintains is_lap_valid (flag == 2) and is_lap_invalid (flag in (0, 1))
        - Maintains lap_timing_status ("timing_in_progress" vs "time_deleted")
        - Detects transitions:
            (0, 1) -> 2 => "timing_in_progress"
            2 -> (0, 1) => "time_deleted"
        - Handles garage / pause silence
        """
        if raw_flag is None:
            return

        try:
            current_flag = int(raw_flag)
        except (ValueError, TypeError):
            return

        is_in_garage_or_pause = (self._last_in_garage or not self._last_in_realtime)

        # In garage / pause: stay silent, update flag without triggering transitions
        if is_in_garage_or_pause:
            self._was_in_garage = True
            self._last_lap_flag = current_flag
            self._is_lap_valid = (current_flag == 2)
            self._is_lap_invalid = (current_flag in (0, 1))
            self._lap_timing_status = "timing_in_progress" if current_flag == 2 else "time_deleted"
            self._validity_transition = None
            return

        # Exiting garage onto track: silent initialization
        if self._was_in_garage:
            self._was_in_garage = False
            self._last_lap_flag = current_flag
            self._is_lap_valid = (current_flag == 2)
            self._is_lap_invalid = (current_flag in (0, 1))
            self._lap_timing_status = "timing_in_progress" if current_flag == 2 else "time_deleted"
            self._validity_transition = None
            return

        # First frame silent initialization
        if self._last_lap_flag is None:
            self._last_lap_flag = current_flag
            self._is_lap_valid = (current_flag == 2)
            self._is_lap_invalid = (current_flag in (0, 1))
            self._lap_timing_status = "timing_in_progress" if current_flag == 2 else "time_deleted"
            self._validity_transition = None
            return

        now = timestamp if timestamp is not None else time.time()

        # On-track transition detection
        if self._last_lap_flag != current_flag:
            if self._last_lap_flag in (0, 1) and current_flag == 2:
                self._last_validity_event = "TIMING_IN_PROGRESS"
                self._lap_timing_status = "timing_in_progress"
                self._last_validity_event_time = now
                self._validity_transition = "timing_in_progress"
                self._is_lap_valid = True
                self._is_lap_invalid = False
            elif self._last_lap_flag == 2 and current_flag in (0, 1):
                self._last_validity_event = "TIME_DELETED"
                self._lap_timing_status = "time_deleted"
                self._last_validity_event_time = now
                self._validity_transition = "time_deleted"
                self._is_lap_valid = False
                self._is_lap_invalid = True

            self._last_lap_flag = current_flag

    # ── Ingestion Handlers ───────────────────────────────────────────────────

    def update_telemetry(self, data: Any, timestamp: Optional[float] = None) -> None:
        """Ingests a 120Hz TelemInfo frame and updates physics state."""
        with self._mutex:
            self.telemetry.update(data, timestamp)
            if data is None:
                return

            if hasattr(data, "in_realtime") and data.in_realtime is not None:
                self._last_in_realtime = bool(data.in_realtime)
            if hasattr(data, "in_garage"):
                self._last_in_garage = bool(data.in_garage)
            elif hasattr(data, "in_garage_stall"):
                self._last_in_garage = bool(data.in_garage_stall)

            # Extract wheels and surface types
            wheels = getattr(data, "wheels", None)
            if wheels and len(wheels) >= 4:
                surface_types = tuple(int(getattr(w, "surface_type", 0)) for w in wheels[:4])
                terrain_names = tuple(str(getattr(w, "terrain_name", "")).strip() for w in wheels[:4])
                # In isiMotor: 0=dry_road, 1=wet_road, 5=kerb, 6=special -> on-track. 2=grass, 3=dirt, 4=gravel -> off-track.
                wheels_on_track = sum(1 for s in surface_types if s not in (2, 3, 4))
                self._last_surface_types = surface_types
                self._last_terrain_names = terrain_names
                self._last_wheels_on_track = wheels_on_track
                self._last_is_on_track = (wheels_on_track >= 3)
            elif hasattr(data, "wheels_on_track"):
                self._last_wheels_on_track = int(data.wheels_on_track)
                self._last_is_on_track = (self._last_wheels_on_track >= 3)
                if hasattr(data, "surface_types"):
                    self._last_surface_types = tuple(data.surface_types)
                if hasattr(data, "terrain_names"):
                    self._last_terrain_names = tuple(data.terrain_names)

            # Speed, pedals
            if hasattr(data, "speed_mps"):
                self._last_speed_kmh = float(data.speed_mps) * 3.6
            elif hasattr(data, "local_vel") and hasattr(data.local_vel, "z"):
                vz = float(data.local_vel.z)
                vx = float(getattr(data.local_vel, "x", 0.0))
                vy = float(getattr(data.local_vel, "y", 0.0))
                self._last_speed_kmh = ((vx**2 + vy**2 + vz**2) ** 0.5) * 3.6

            if hasattr(data, "unfiltered_throttle"):
                self._last_throttle_pct = float(data.unfiltered_throttle) * 100.0
            if hasattr(data, "unfiltered_brake"):
                self._last_brake_pct = float(data.unfiltered_brake) * 100.0

            if hasattr(data, "gear"):
                self._last_gear = int(data.gear)
            if hasattr(data, "engine_rpm"):
                self._last_engine_rpm = float(data.engine_rpm)
            if hasattr(data, "engine_max_rpm") and float(data.engine_max_rpm) > 1000.0:
                self._last_engine_max_rpm = float(data.engine_max_rpm)
            if hasattr(data, "fuel"):
                self._last_fuel = float(data.fuel)
            if hasattr(data, "lap_dist"):
                self._last_lap_dist = float(data.lap_dist)

            raw_flag = None
            if hasattr(data, "lap_flag"):
                raw_flag = getattr(data, "lap_flag")
            elif hasattr(data, "count_lap_flag"):
                raw_flag = getattr(data, "count_lap_flag")
            elif isinstance(data, dict):
                raw_flag = data.get("lap_flag", data.get("count_lap_flag", data.get("mCountLapFlag")))

            if raw_flag is not None:
                self._process_lap_validity(raw_flag, timestamp)

    def update_compact_scoring(self, data: Any, timestamp: Optional[float] = None) -> None:
        """Ingests a 10Hz CompactScoring frame and updates timing & lap flag state."""
        with self._mutex:
            self.compact_scoring.update(data, timestamp)
            if data is None:
                return

            if hasattr(data, "in_realtime"):
                self._last_in_realtime = bool(data.in_realtime)
            if hasattr(data, "in_garage_stall"):
                self._last_in_garage = bool(data.in_garage_stall)

            raw_flag = getattr(data, "count_lap_flag", None)
            if raw_flag is not None:
                self._process_lap_validity(raw_flag, timestamp)
            elif isinstance(data, dict):
                raw_flag = data.get("count_lap_flag", data.get("mCountLapFlag"))
                if raw_flag is not None:
                    self._process_lap_validity(raw_flag, timestamp)

            if hasattr(data, "total_laps"):
                self._last_total_laps = int(data.total_laps)
            elif isinstance(data, dict) and ("total_laps" in data or "mTotalLaps" in data):
                self._last_total_laps = int(data.get("total_laps", data.get("mTotalLaps", 0)))

            if hasattr(data, "sector"):
                raw_sec = int(data.sector)
                self._last_current_sector = 3 if raw_sec == 0 else (raw_sec if raw_sec in (1, 2, 3) else 1)
            elif isinstance(data, dict) and ("sector" in data or "mSector" in data):
                raw_sec = int(data.get("sector", data.get("mSector", 1)))
                self._last_current_sector = 3 if raw_sec == 0 else (raw_sec if raw_sec in (1, 2, 3) else 1)

    def update_full_scoring(self, data: Any, timestamp: Optional[float] = None) -> None:
        """Ingests a 2-5Hz FullScoringSession frame and updates grid, penalties & rule parameters."""
        with self._mutex:
            self.full_scoring.update(data, timestamp)
            if data is None:
                return

            # Rules parameters
            if hasattr(data, "lmu") and data.lmu:
                if getattr(data.lmu, "track_limits_steps_per_point", 0) > 0:
                    self._last_steps_per_point = int(data.lmu.track_limits_steps_per_point)
                if getattr(data.lmu, "track_limits_steps_per_penalty", 0) > 0:
                    self._last_steps_per_penalty = int(data.lmu.track_limits_steps_per_penalty)

            # Player vehicle data
            player_veh = getattr(data, "player_vehicle", None)
            if player_veh is None and isinstance(data, dict):
                vehs = data.get("mVehicles", data.get("vehicles", []))
                for v in vehs:
                    if isinstance(v, dict) and (v.get("mIsPlayer") or v.get("is_player")):
                        player_veh = v
                        break
                    elif hasattr(v, "is_player") and getattr(v, "is_player"):
                        player_veh = v
                        break
                    elif hasattr(v, "mIsPlayer") and getattr(v, "mIsPlayer"):
                        player_veh = v
                        break

            if player_veh is not None:
                if isinstance(player_veh, dict):
                    if "mInGarageStall" in player_veh or "in_garage_stall" in player_veh:
                        self._last_in_garage = bool(player_veh.get("mInGarageStall", player_veh.get("in_garage_stall")))
                    if "mNumPenalties" in player_veh or "num_penalties" in player_veh:
                        self._last_penalties = int(player_veh.get("mNumPenalties", player_veh.get("num_penalties", 0)))
                    if "mTotalLaps" in player_veh or "total_laps" in player_veh:
                        self._last_total_laps = int(player_veh.get("mTotalLaps", player_veh.get("total_laps", 0)))
                    if "mSector" in player_veh or "sector" in player_veh:
                        raw_sec = int(player_veh.get("mSector", player_veh.get("sector", 1)))
                        self._last_current_sector = 3 if raw_sec == 0 else (raw_sec if raw_sec in (1, 2, 3) else 1)
                    raw_flag = player_veh.get("mCountLapFlag", player_veh.get("count_lap_flag"))
                    if raw_flag is not None:
                        self._process_lap_validity(raw_flag, timestamp)
                else:
                    if hasattr(player_veh, "in_garage_stall"):
                        self._last_in_garage = bool(player_veh.in_garage_stall)
                    if hasattr(player_veh, "num_penalties"):
                        self._last_penalties = int(player_veh.num_penalties)
                    if hasattr(player_veh, "total_laps"):
                        self._last_total_laps = int(player_veh.total_laps)
                    if hasattr(player_veh, "sector"):
                        raw_sec = int(player_veh.sector)
                        self._last_current_sector = 3 if raw_sec == 0 else (raw_sec if raw_sec in (1, 2, 3) else 1)
                    if hasattr(player_veh, "lmu") and player_veh.lmu:
                        self._last_track_limits_steps = int(getattr(player_veh.lmu, "track_limits_steps", 0))

                    raw_flag = getattr(player_veh, "count_lap_flag", None)
                    if raw_flag is not None:
                        self._process_lap_validity(raw_flag, timestamp)

    def update_weather(self, data: Any, timestamp: Optional[float] = None) -> None:
        """Ingests weather packet."""
        with self._mutex:
            self.weather.update(data, timestamp)

    def update_system_event(self, data: Any, timestamp: Optional[float] = None) -> None:
        """Ingests system session / cockpit event."""
        with self._mutex:
            self.system.update(data, timestamp)
            if hasattr(data, "in_realtime") and data.in_realtime is not None:
                self._last_in_realtime = bool(data.in_realtime)

    def update_lap_validity(self, flag: int, timestamp: Optional[float] = None) -> None:
        """Explicit update of authoritative lap validity flag."""
        with self._mutex:
            self._process_lap_validity(flag, timestamp)

    def consume_validity_transition(self) -> Optional[str]:
        """Returns and clears the latest pending validity transition ('timing_in_progress' or 'time_deleted')."""
        with self._mutex:
            trans = self._validity_transition
            self._validity_transition = None
            return trans

    # ── Unified Cross-Packet High-Level Properties ───────────────────────────

    @property
    def wheels_on_track(self) -> int:
        """Returns authoritative number of wheels on track (0 to 4)."""
        with self._mutex:
            return self._last_wheels_on_track

    @property
    def is_on_track(self) -> bool:
        """Returns True if the vehicle has at least 3 wheels on track / legal road surface."""
        with self._mutex:
            return self._last_is_on_track

    @property
    def surface_types(self) -> Tuple[int, ...]:
        """Returns 4-tuple of wheel surface types (0=road, 2=grass, 4=gravel, 5=kerb)."""
        with self._mutex:
            return self._last_surface_types

    @property
    def terrain_names(self) -> Tuple[str, ...]:
        """Returns 4-tuple of wheel terrain names."""
        with self._mutex:
            return self._last_terrain_names

    @property
    def lap_flag(self) -> int:
        """
        Authoritative count_lap_flag:
        0 = Invalid / Deleted / Penalty
        1 = Under Investigation (Cut Track)
        2 = Clean / Valid / Cleared
        """
        with self._mutex:
            return 2 if self._last_lap_flag is None else self._last_lap_flag

    @property
    def is_lap_valid(self) -> bool:
        """True if current lap is official and valid for timing (count_lap_flag == 2)."""
        with self._mutex:
            return self.lap_flag == 2

    @property
    def is_lap_invalid(self) -> bool:
        """True if current lap is invalidated / cut / deleted (count_lap_flag in (0, 1))."""
        with self._mutex:
            return self.lap_flag in (0, 1)

    @property
    def lap_timing_status(self) -> str:
        """Authoritative lap timing status ('timing_in_progress' or 'time_deleted')."""
        with self._mutex:
            return "timing_in_progress" if self.lap_flag == 2 else "time_deleted"

    @property
    def lap_status_text(self) -> str:
        """User-facing lap status description ('Valid' or 'Invalid')."""
        with self._mutex:
            return "Valid" if self.lap_flag == 2 else "Invalid"

    @property
    def last_validity_event(self) -> str:
        """Name of last validity transition event ('TIMING_IN_PROGRESS', 'TIME_DELETED', 'IDLE')."""
        with self._mutex:
            return self._last_validity_event

    @property
    def last_validity_event_time(self) -> float:
        """Timestamp of last validity transition."""
        with self._mutex:
            return self._last_validity_event_time

    @property
    def validity_transition(self) -> Optional[str]:
        """Pending unconsumed validity transition string, if any."""
        with self._mutex:
            return self._validity_transition

    @property
    def num_penalties(self) -> int:
        """Active official penalties issued by Race Control."""
        with self._mutex:
            return self._last_penalties

    @property
    def track_limits_steps(self) -> int:
        """Active infraction steps accumulated in LMU Track Limits system."""
        with self._mutex:
            return self._last_track_limits_steps

    @property
    def steps_per_point(self) -> int:
        """Threshold steps per penalty point in LMU."""
        with self._mutex:
            return self._last_steps_per_point

    @property
    def steps_per_penalty(self) -> int:
        """Threshold steps per official drive-through penalty."""
        with self._mutex:
            return self._last_steps_per_penalty

    @property
    def current_sector(self) -> int:
        """Current lap sector (1, 2, or 3)."""
        with self._mutex:
            return self._last_current_sector

    @property
    def total_laps(self) -> int:
        """Total laps completed."""
        with self._mutex:
            return self._last_total_laps

    @property
    def speed_kmh(self) -> float:
        """Current vehicle speed in km/h."""
        with self._mutex:
            return self._last_speed_kmh

    @property
    def throttle_pct(self) -> float:
        """Current unfiltered throttle percentage (0-100%)."""
        with self._mutex:
            return self._last_throttle_pct

    @property
    def brake_pct(self) -> float:
        """Current unfiltered brake percentage (0-100%)."""
        with self._mutex:
            return self._last_brake_pct

    @property
    def in_realtime(self) -> bool:
        """True if game is running in realtime (not paused / in garage)."""
        with self._mutex:
            return self._last_in_realtime

    @property
    def in_garage(self) -> bool:
        """True if player is in garage."""
        with self._mutex:
            return self._last_in_garage

    @property
    def gear(self) -> int:
        """Currently engaged vehicle gear (-1=R, 0=N, 1..8)."""
        with self._mutex:
            return self._last_gear

    @property
    def rpm(self) -> float:
        """Current engine RPM."""
        with self._mutex:
            return self._last_engine_rpm

    @property
    def engine_rpm(self) -> float:
        """Current engine RPM (alias)."""
        with self._mutex:
            return self._last_engine_rpm

    @property
    def engine_max_rpm(self) -> float:
        """Maximum engine RPM / redline."""
        with self._mutex:
            return self._last_engine_max_rpm

    @property
    def fuel(self) -> float:
        """Current fuel remaining in liters or kilograms."""
        with self._mutex:
            return self._last_fuel

    @property
    def lap_dist(self) -> float:
        """Current lap distance along track spline in meters."""
        with self._mutex:
            return self._last_lap_dist
