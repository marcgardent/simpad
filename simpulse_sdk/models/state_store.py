"""
SimPulse Central Telemetry State Store.
Maintains in-memory the latest known frame for each ISI / LMU UDP telemetry channel,
tracks packet timestamps & freshness, and exposes a unified, consistent vehicle and session state.
"""

from __future__ import annotations
import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Generic, List, Optional, Tuple, TypeVar, Union, Self

from isimotor_rawudp_client import (
    TelemInfo,
    CompactScoring,
    FullScoringSession,
    WeatherControl,
    ExtendedState,
    ForceFeedback,
    Graphics,
    SystemEvent,
)
from .scoring import BaseTimingState, FullGridScoringState
from .delta import LapDeltaPacket
from .presence import PresenceTracker

T = TypeVar("T")


class TimingStatus(str, Enum):
    """Authoritative lap timing validity status according to game flag."""
    TIMING_IN_PROGRESS = "timing_in_progress"
    TIME_DELETED = "time_deleted"


class ValidityEvent(str, Enum):
    """High-level lap validity state event."""
    IDLE = "IDLE"
    TIMING_IN_PROGRESS = "TIMING_IN_PROGRESS"
    TIME_DELETED = "TIME_DELETED"


class LapStatus(str, Enum):
    """Clean vs dirty lap status."""
    CLEAN = "clean"
    DIRTY = "dirty"


@dataclass
class PacketSlot(Generic[T]):
    """A slot holding the latest received raw data packet and its arrival timestamp."""
    data: Optional[T] = None
    timestamp: float = 0.0
    sequence_id: int = 0
    raw_bytes_len: int = 0

    @property
    def age_sec(self) -> float:
        """Returns age of the cached packet in seconds."""
        if self.timestamp <= 0.0:
            return 999999.0
        return max(0.0, time.time() - self.timestamp)

    def is_fresh(self, max_age_sec: float = 1.0) -> bool:
        """Returns True if the cached packet was received within max_age_sec."""
        return self.data is not None and self.age_sec <= max_age_sec

    def update(self, data: T, timestamp: float, raw_bytes_len: int = 0) -> None:
        """Updates slot with new packet data."""
        self.data = data
        self.timestamp = timestamp
        self.raw_bytes_len = raw_bytes_len
        self.sequence_id += 1


class TelemetryStateStore:
    """
    Thread-safe Central Telemetry State Store.
    Preserves the latest known frame for every telemetry channel and provides
    unified cross-channel vehicle state without stale defaults or race conditions.
    """
    _instance: Optional[Self] = None
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
        self.force_feedback = PacketSlot()     # ForceFeedback
        self.graphics = PacketSlot()           # Graphics
        self.track_rules = PacketSlot()        # TrackRules
        self.pit_menu = PacketSlot()           # PitMenu
        self.delta = PacketSlot()              # LapDeltaPacket derived state (120Hz continuous)

        # Unified typed scoring models
        self.timing: BaseTimingState = BaseTimingState()
        self.grid: Optional[FullGridScoringState] = None

        # Dedicated fusion of TelemInfo/CompactScoring/FullScoringSession/
        # SystemEvent/ExtendedState into one hysteresis-guarded presence state (see
        # in_realtime/in_garage properties below, which delegate to it). Replaces
        # LMUParser's former 5 independent, mutually-divergent heuristics.
        self._presence: PresenceTracker = PresenceTracker()

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
        self._lap_timing_status: TimingStatus = TimingStatus.TIMING_IN_PROGRESS
        self._last_validity_event: ValidityEvent = ValidityEvent.IDLE
        self._last_validity_event_time: float = 0.0
        self._validity_transition: Optional[TimingStatus] = None
        self._was_in_garage: bool = False
        self._last_current_sector: int = 1
        self._last_total_laps: int = 0
        self._last_speed_kmh: float = 0.0
        self._last_throttle_pct: float = 0.0
        self._last_brake_pct: float = 0.0
        self._last_gear: int = 0
        self._last_engine_rpm: float = 0.0
        self._last_engine_max_rpm: float = 7500.0
        self._last_fuel: float = 0.0
        self._last_lap_dist: float = 0.0
        self._last_time_into_lap: float = 0.0
        self._last_grips: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)

        # Hit (collision/contact) tracking per lap & clean lap cache
        self._hit_count_current_lap: int = 0
        self._last_impact_et: float = 0.0       # last_impact_et from TelemInfo UDP
        self._hit_lap_reference: Optional[int] = None  # lap number used to detect lap changes
        self._cache_is_clean_lap: bool = True
        self._cache_clean_lap_status: LapStatus = LapStatus.CLEAN
        self._cache_hit_count: int = 0

    @classmethod
    def get_instance(cls) -> Self:
        """Singleton accessor for global telemetry state store."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _recalculate_cache(self) -> None:
        """Recalculates clean/dirty lap cache based on timing status and hits in current lap."""
        self._cache_hit_count = self._hit_count_current_lap
        # Clean Lap = timed lap (timing in progress <=> flag == 2) && 0 Hits
        self._cache_is_clean_lap = (self._is_lap_valid and self._hit_count_current_lap == 0)
        self._cache_clean_lap_status = LapStatus.CLEAN if self._cache_is_clean_lap else LapStatus.DIRTY

    def _on_lap_changed(self) -> None:
        """Called on lap transition: resets hit counter and cache for the new lap."""
        self._hit_count_current_lap = 0
        self._recalculate_cache()

    @staticmethod
    def _normalize_raw_sector(raw_sector: int) -> int:
        """Per-packet isiMotor sector code -> 1/2/3, with NO jitter guard.

        This is the raw signal DeltaEngine's own guard (_handle_sector_transition)
        needs to see un-massaged to detect and reject a stray echo — it must NOT
        be pre-resolved to the already-guarded display value (see
        _resolve_current_sector below), or the guard would only ever see its own
        past output and could never catch a genuine disagreement between
        CompactScoring and FullScoringSession again.
        """
        return 3 if raw_sector == 0 else (raw_sector if raw_sector in (1, 2, 3) else 1)

    def _resolve_current_sector(self, raw_sector: int) -> int:
        """Single source of truth for the *displayed* current sector.

        Prefers the authoritative, jitter-guarded value already computed by
        DeltaEngine (delivered here through ``update_delta`` as
        ``LapDeltaPacket.current_sector``) over a naive per-packet remap of the
        raw isiMotor sector code. CompactScoring and FullScoringSession can
        disagree on the raw code for a frame or two around a timing line;
        recomputing it naively here duplicated (and disagreed with) the guard
        DeltaEngine already applies, which is what actually reaches the HUD.

        Used ONLY for the ``current_sector`` property (plugin/HUD display).
        ``BaseTimingState.sector``/``FullGridScoringState.sector`` (consumed as
        DeltaEngine's own input) use ``_normalize_raw_sector`` instead — see its
        docstring for why the two must not be conflated.
        """
        if self.delta.data is not None and self.delta.is_fresh(2.0):
            return int(self.delta.data.current_sector)
        return self._normalize_raw_sector(raw_sector)

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
            self.force_feedback = PacketSlot()
            self.graphics = PacketSlot()
            self.track_rules = PacketSlot()
            self.pit_menu = PacketSlot()
            self.delta = PacketSlot()
            self.timing = BaseTimingState()
            self.grid = None
            self._presence = PresenceTracker()

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
            self._lap_timing_status = TimingStatus.TIMING_IN_PROGRESS
            self._last_validity_event = ValidityEvent.IDLE
            self._last_validity_event_time = 0.0
            self._validity_transition = None
            self._was_in_garage = False
            self._last_current_sector = 1
            self._last_total_laps = 0
            self._last_speed_kmh = 0.0
            self._last_throttle_pct = 0.0
            self._last_brake_pct = 0.0
            self._last_gear = 0
            self._last_engine_rpm = 0.0
            self._last_engine_max_rpm = 7500.0
            self._last_fuel = 0.0
            self._last_lap_dist = 0.0
            self._last_time_into_lap = 0.0
            self._last_grips = (1.0, 1.0, 1.0, 1.0)
            self._hit_count_current_lap = 0
            self._last_impact_et = 0.0
            self._hit_lap_reference = None
            self._cache_is_clean_lap = True
            self._cache_clean_lap_status = LapStatus.CLEAN
            self._cache_hit_count = 0
            self._recalculate_cache()

    def _process_lap_validity(self, current_flag: int, timestamp: Optional[float] = None) -> None:
        """
        Internal transition detector for lap validity flag.
        Dispatches edge triggers and updates internal timing status.
        """
        is_in_garage_or_pause = self._presence.in_garage or not self._presence.in_realtime

        # In garage / pause: stay silent, update flag without triggering transitions
        if is_in_garage_or_pause:
            self._was_in_garage = True
            self._last_lap_flag = current_flag
            self._is_lap_valid = (current_flag == 2)
            self._is_lap_invalid = (current_flag in (0, 1))
            self._lap_timing_status = TimingStatus.TIMING_IN_PROGRESS if current_flag == 2 else TimingStatus.TIME_DELETED
            self._validity_transition = None
            return

        # Exiting garage onto track: silent initialization
        if self._was_in_garage:
            self._was_in_garage = False
            self._last_lap_flag = current_flag
            self._is_lap_valid = (current_flag == 2)
            self._is_lap_invalid = (current_flag in (0, 1))
            self._lap_timing_status = TimingStatus.TIMING_IN_PROGRESS if current_flag == 2 else TimingStatus.TIME_DELETED
            self._validity_transition = None
            return

        # First frame silent initialization
        if self._last_lap_flag is None:
            self._last_lap_flag = current_flag
            self._is_lap_valid = (current_flag == 2)
            self._is_lap_invalid = (current_flag in (0, 1))
            self._lap_timing_status = TimingStatus.TIMING_IN_PROGRESS if current_flag == 2 else TimingStatus.TIME_DELETED
            self._validity_transition = None
            self._recalculate_cache()
            return

        now = timestamp if timestamp is not None else time.time()

        # On-track transition detection
        if self._last_lap_flag != current_flag:
            if self._last_lap_flag in (0, 1) and current_flag == 2:
                self._last_validity_event = ValidityEvent.TIMING_IN_PROGRESS
                self._lap_timing_status = TimingStatus.TIMING_IN_PROGRESS
                self._last_validity_event_time = now
                self._validity_transition = TimingStatus.TIMING_IN_PROGRESS
                self._is_lap_valid = True
                self._is_lap_invalid = False
            elif self._last_lap_flag == 2 and current_flag in (0, 1):
                self._last_validity_event = ValidityEvent.TIME_DELETED
                self._lap_timing_status = TimingStatus.TIME_DELETED
                self._last_validity_event_time = now
                self._validity_transition = TimingStatus.TIME_DELETED
                self._is_lap_valid = False
                self._is_lap_invalid = True

            self._last_lap_flag = current_flag
            self._recalculate_cache()

    # ── Ingestion Handlers ───────────────────────────────────────────────────

    def update_telemetry(self, data: TelemInfo, timestamp: float, raw_bytes_len: int = 0) -> None:
        """Ingests a 120Hz TelemInfo frame and updates physics state."""
        with self._mutex:
            self.telemetry.update(data, timestamp, raw_bytes_len)

            self._presence.on_telemetry(getattr(data, "speed_mps", 0.0))

            # Extract wheels and surface types
            wheels = getattr(data, "wheels", None)
            if wheels and len(wheels) >= 4:
                surface_types = tuple(w.surface_type for w in wheels[:4])
                terrain_names = tuple(w.terrain_name.strip() for w in wheels[:4])
                # In isiMotor: 0=dry_road, 1=wet_road, 5=kerb, 6=special -> on-track. 2=grass, 3=dirt, 4=gravel -> off-track.
                wheels_on_track = sum(1 for s in surface_types if s not in (2, 3, 4))
                self._last_surface_types = surface_types
                self._last_terrain_names = terrain_names
                self._last_wheels_on_track = wheels_on_track
                self._last_is_on_track = (wheels_on_track >= 3)

            # Speed, pedals
            self._last_speed_kmh = getattr(data, "speed_kmh", getattr(data, "vehicle_speed", 0.0))
            self._last_throttle_pct = getattr(data, "unfiltered_throttle", getattr(data, "throttle", 0.0)) * 100.0
            self._last_brake_pct = getattr(data, "unfiltered_brake", getattr(data, "brake", 0.0)) * 100.0
            self._last_gear = getattr(data, "gear", 0)
            self._last_engine_rpm = getattr(data, "engine_rpm", 0.0)
            max_rpm = getattr(data, "engine_max_rpm", 7500.0)
            if max_rpm > 1000.0:
                self._last_engine_max_rpm = max_rpm
            self._last_fuel = getattr(data, "fuel", 0.0)

            # ── Hit (collision/contact) detection from TelemInfo UDP ──────
            # Detect lap change: reset hit counter when lap_number changes
            current_lap_number = getattr(data, "lap_number", 0)
            if self._hit_lap_reference is not None and current_lap_number != self._hit_lap_reference:
                self._on_lap_changed()
            self._hit_lap_reference = current_lap_number

            # Detect new impact: last_impact_et changes = new collision event
            impact_et = getattr(data, "last_impact_et", 0.0)
            if impact_et > 0.0 and impact_et != self._last_impact_et:
                self._hit_count_current_lap += 1
                self._last_impact_et = impact_et

            self._recalculate_cache()

    def update_compact_scoring(self, data: CompactScoring, timestamp: float, raw_bytes_len: int = 0) -> None:
        """Ingests a 10Hz CompactScoring frame and updates timing & lap flag state."""
        with self._mutex:
            self.compact_scoring.update(data, timestamp, raw_bytes_len)

            self._presence.on_compact_scoring(data.in_garage_stall, data.in_realtime)

            self._process_lap_validity(data.count_lap_flag, timestamp)

            new_laps = data.total_laps
            if self._last_total_laps > 0 and new_laps != self._last_total_laps:
                self._on_lap_changed()
            self._last_total_laps = new_laps

            raw_sec = data.sector
            norm_sec = self._normalize_raw_sector(raw_sec)
            self._last_current_sector = self._resolve_current_sector(raw_sec)

            # Construct unified BaseTimingState (continuous 10Hz) — carries the raw
            # normalized sector (DeltaEngine's input), not the guarded display value.
            self.timing = BaseTimingState(
                track_name=data.track_name.strip(),
                session=data.session,
                current_et=data.current_et,
                track_length=data.lap_dist,
                max_laps=data.max_laps,
                in_realtime=data.in_realtime,
                total_laps=data.total_laps,
                sector=norm_sec,
                in_garage=data.in_garage_stall,
                count_lap_flag=data.count_lap_flag,
                is_lap_valid=(data.count_lap_flag == 2),
                cur_sector1=data.cur_sector1,
                cur_sector2=data.cur_sector2,
                last_sector1=data.last_sector1,
                last_sector2=data.last_sector2,
                last_lap_time=data.last_lap_time,
                best_sector1=data.best_sector1,
                best_sector2=data.best_sector2,
                best_lap_time=data.best_lap_time,
            )

            # Sync timing updates to grid state if present
            if self.grid is not None:
                self.grid.total_laps = data.total_laps
                self.grid.sector = norm_sec
                self.grid.in_garage = data.in_garage_stall
                self.grid.count_lap_flag = data.count_lap_flag
                self.grid.is_lap_valid = (data.count_lap_flag == 2)
                self.grid.cur_sector1 = data.cur_sector1
                self.grid.cur_sector2 = data.cur_sector2
                self.grid.last_sector1 = data.last_sector1
                self.grid.last_sector2 = data.last_sector2
                self.grid.last_lap_time = data.last_lap_time
                self.grid.best_sector1 = data.best_sector1
                self.grid.best_sector2 = data.best_sector2
                self.grid.best_lap_time = data.best_lap_time

            self._recalculate_cache()

    def update_full_scoring(self, data: FullScoringSession, timestamp: float, raw_bytes_len: int = 0) -> None:
        """Ingests a 2-5Hz FullScoringSession frame and updates grid, penalties & rule parameters."""
        with self._mutex:
            self.full_scoring.update(data, timestamp, raw_bytes_len)

            # Rules parameters LMU
            steps_per_point = 3
            steps_per_penalty = 12
            if data.lmu:
                if data.lmu.track_limits_steps_per_point > 0:
                    self._last_steps_per_point = data.lmu.track_limits_steps_per_point
                    steps_per_point = data.lmu.track_limits_steps_per_point
                if data.lmu.track_limits_steps_per_penalty > 0:
                    self._last_steps_per_penalty = data.lmu.track_limits_steps_per_penalty
                    steps_per_penalty = data.lmu.track_limits_steps_per_penalty

            # Player vehicle data
            player_veh = data.player_vehicle
            # Robust fallback: locate the player when the packet exposes it through the
            # vehicles/leaderboard lists instead of the dedicated player_vehicle slot.
            if player_veh is None:
                for cand in list(data.vehicles) + list(data.leaderboard or []):
                    if getattr(cand, "is_player", False) or int(getattr(cand, "control", -1)) == 0:
                        player_veh = cand
                        break
            norm_sec = 1
            # Must run unconditionally (even without a resolved player vehicle this
            # tick) — mirrors the former LMUParser heuristic's unconditional write.
            self._presence.on_full_scoring(
                data.game_phase,
                data.in_realtime,
                player_veh.in_garage_stall if player_veh is not None else False,
            )
            if player_veh is not None:
                self._last_penalties = player_veh.num_penalties
                self._last_total_laps = player_veh.total_laps
                self._last_lap_dist = player_veh.lap_dist
                raw_sec = player_veh.sector
                norm_sec = self._normalize_raw_sector(raw_sec)
                self._last_current_sector = self._resolve_current_sector(raw_sec)
                if player_veh.lmu:
                    self._last_track_limits_steps = player_veh.lmu.track_limits_steps

                self._process_lap_validity(player_veh.count_lap_flag, timestamp)

                # Keep BaseTimingState in sync
                self.timing = BaseTimingState(
                    track_name=data.track_name.strip(),
                    session=data.session,
                    current_et=data.current_et,
                    track_length=data.lap_dist,
                    max_laps=data.max_laps,
                    in_realtime=data.in_realtime,
                    total_laps=player_veh.total_laps,
                    sector=norm_sec,
                    in_garage=player_veh.in_garage_stall,
                    count_lap_flag=player_veh.count_lap_flag,
                    is_lap_valid=(player_veh.count_lap_flag == 2),
                    cur_sector1=player_veh.cur_sector1,
                    cur_sector2=player_veh.cur_sector2,
                    last_sector1=player_veh.last_sector1,
                    last_sector2=player_veh.last_sector2,
                    last_lap_time=player_veh.last_lap_time,
                    best_sector1=player_veh.best_sector1,
                    best_sector2=player_veh.best_sector2,
                    best_lap_time=player_veh.best_lap_time,
                )

                # Construct FullGridScoringState
                self.grid = FullGridScoringState(
                    track_name=data.track_name.strip(),
                    session=data.session,
                    current_et=data.current_et,
                    track_length=data.lap_dist,
                    max_laps=data.max_laps,
                    in_realtime=data.in_realtime,
                    total_laps=player_veh.total_laps,
                    sector=norm_sec,
                    in_garage=player_veh.in_garage_stall,
                    count_lap_flag=player_veh.count_lap_flag,
                    is_lap_valid=(player_veh.count_lap_flag == 2),
                    cur_sector1=player_veh.cur_sector1,
                    cur_sector2=player_veh.cur_sector2,
                    last_sector1=player_veh.last_sector1,
                    last_sector2=player_veh.last_sector2,
                    last_lap_time=player_veh.last_lap_time,
                    best_sector1=player_veh.best_sector1,
                    best_sector2=player_veh.best_sector2,
                    best_lap_time=player_veh.best_lap_time,
                    end_et=data.end_et,
                    game_phase=data.game_phase,
                    yellow_flag_state=data.yellow_flag_state,
                    sector_flags=data.sector_flags,
                    start_light=data.start_light,
                    num_red_lights=data.num_red_lights,
                    is_fcy=data.is_fcy,
                    ambient_temp=data.ambient_temp,
                    track_temp=data.track_temp,
                    dark_cloud=data.dark_cloud,
                    raining=data.raining,
                    avg_path_wetness=data.avg_path_wetness,
                    min_path_wetness=data.min_path_wetness,
                    max_path_wetness=data.max_path_wetness,
                    track_limits_steps_per_point=steps_per_point,
                    track_limits_steps_per_penalty=steps_per_penalty,
                    driver_name=player_veh.driver_name.strip(),
                    vehicle_name=player_veh.vehicle_name.strip(),
                    vehicle_class=player_veh.vehicle_class.strip(),
                    place=player_veh.place,
                    qualification=player_veh.qualification,
                    finish_status=player_veh.finish_status,
                    num_pitstops=player_veh.num_pitstops,
                    num_penalties=player_veh.num_penalties,
                    track_limits_steps=self._last_track_limits_steps,
                    in_pits=player_veh.in_pits,
                    pit_state=player_veh.pit_state,
                    time_behind_leader=player_veh.time_behind_leader,
                    time_behind_next=player_veh.time_behind_next,
                    laps_behind_leader=player_veh.laps_behind_leader,
                    laps_behind_next=player_veh.laps_behind_next,
                    lap_start_et=player_veh.lap_start_et,
                    time_into_lap=player_veh.time_into_lap,
                    estimated_lap_time=player_veh.estimated_lap_time,
                    car_lap_dist=player_veh.lap_dist,
                    num_vehicles=len(data.vehicles),
                    vehicles=data.vehicles,
                    leaderboard=data.leaderboard,
                    player_vehicle=player_veh,
                )

            self._recalculate_cache()

    def update_weather(self, data: WeatherControl, timestamp: float, raw_bytes_len: int = 0) -> None:
        """Ingests weather packet."""
        with self._mutex:
            self.weather.update(data, timestamp, raw_bytes_len)

    def update_system_event(self, data: SystemEvent, timestamp: float, raw_bytes_len: int = 0) -> None:
        """Ingests system session / cockpit event."""
        with self._mutex:
            self.system.update(data, timestamp, raw_bytes_len)
            self._presence.on_system_event(data.event_id)

    def update_system_events(self, data: SystemEvent, timestamp: float, raw_bytes_len: int = 0) -> None:
        """Ingests system session / cockpit event (plural alias)."""
        self.update_system_event(data, timestamp, raw_bytes_len)

    def update_opponent_telemetry(self, data: TelemInfo, timestamp: float, raw_bytes_len: int = 0) -> None:
        """Ingests opponent vehicle dynamics."""
        with self._mutex:
            self.opponent_telemetry.update(data, timestamp, raw_bytes_len)

    def update_extended_state(self, data: ExtendedState, timestamp: float, raw_bytes_len: int = 0) -> None:
        """Ingests extended vehicle state (lights, wipers, ignition, flags)."""
        with self._mutex:
            self.extended_state.update(data, timestamp, raw_bytes_len)
            in_realtime_fc = getattr(data, "in_realtime_fc", None)
            if in_realtime_fc is not None:
                self._presence.on_extended_state(bool(in_realtime_fc))

    def update_force_feedback(self, data: ForceFeedback, timestamp: float, raw_bytes_len: int = 0) -> None:
        """Ingests force feedback packet."""
        with self._mutex:
            self.force_feedback.update(data, timestamp, raw_bytes_len)

    def update_graphics(self, data: Graphics, timestamp: float, raw_bytes_len: int = 0) -> None:
        """Ingests camera / graphics telemetry frame."""
        with self._mutex:
            self.graphics.update(data, timestamp, raw_bytes_len)

    def update_track_rules(
        self,
        data: Union[bytes, Dict[str, Union[str, int, float, bool, None]]],
        timestamp: float,
        raw_bytes_len: int = 0,
    ) -> None:
        """Ingests track rules / flag conditions."""
        with self._mutex:
            self.track_rules.update(data, timestamp, raw_bytes_len)

    def update_pit_menu(
        self,
        data: Union[bytes, Dict[str, Union[str, int, float, bool, None]]],
        timestamp: float,
        raw_bytes_len: int = 0,
    ) -> None:
        """Ingests pit strategy menu state."""
        with self._mutex:
            self.pit_menu.update(data, timestamp, raw_bytes_len)

    def update_delta(
        self,
        data: LapDeltaPacket,
        timestamp: Optional[float] = None,
        raw_bytes_len: int = 0,
    ) -> None:
        """Ingests authoritative continuous LapDeltaPacket and updates continuous distance."""
        with self._mutex:
            ts = timestamp if timestamp is not None else time.time()
            self.delta.update(data, ts, raw_bytes_len)
            if data.player_dist > 0.0 or self._last_lap_dist == 0.0:
                self._last_lap_dist = data.player_dist

    def update_lap_validity(self, flag: int, timestamp: float) -> None:
        """Explicit update of authoritative lap validity flag."""
        with self._mutex:
            self._process_lap_validity(flag, timestamp)

    def consume_validity_transition(self) -> Optional[TimingStatus]:
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
    def lap_timing_status(self) -> TimingStatus:
        """Authoritative lap timing status ('timing_in_progress' or 'time_deleted')."""
        with self._mutex:
            return TimingStatus.TIMING_IN_PROGRESS if self.lap_flag == 2 else TimingStatus.TIME_DELETED

    @property
    def lap_status_text(self) -> str:
        """User-facing lap status description ('Valid' or 'Invalid')."""
        with self._mutex:
            return "Valid" if self.lap_flag == 2 else "Invalid"

    @property
    def track_cut_state(self) -> str:
        """User-facing track-limits state derived from lap_flag: 'yellow' (under
        investigation, count_lap_flag == 1), 'invalid' (deleted/penalty, == 0), or
        'green' (clean, == 2). Pure function of lap_flag — the single canonical
        version of a rule LMUParser used to duplicate 3x (once per packet type)."""
        with self._mutex:
            flag = self.lap_flag
            if flag == 1:
                return "yellow"
            if flag == 0:
                return "invalid"
            return "green"

    @property
    def last_validity_event(self) -> ValidityEvent:
        """Name of last validity transition event ('TIMING_IN_PROGRESS', 'TIME_DELETED', 'IDLE')."""
        with self._mutex:
            return self._last_validity_event

    @property
    def last_validity_event_time(self) -> float:
        """Timestamp of last validity transition."""
        with self._mutex:
            return self._last_validity_event_time

    @property
    def validity_transition(self) -> Optional[TimingStatus]:
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
    def speed_mps(self) -> float:
        """Current vehicle speed in m/s."""
        with self._mutex:
            return self._last_speed_kmh / 3.6

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
        """True if game is running in realtime (not paused / in garage). Delegates
        to the PresenceTracker fusion of TelemInfo/CompactScoring/FullScoringSession/
        SystemEvent/ExtendedState — never recomputed here."""
        with self._mutex:
            return self._presence.in_realtime

    @property
    def in_garage(self) -> bool:
        """True if player is in garage. Delegates to PresenceTracker — see in_realtime."""
        with self._mutex:
            return self._presence.in_garage

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
            if self.delta.data is not None and self.delta.data.player_dist > 0.0:
                return float(self.delta.data.player_dist)
            return self._last_lap_dist

    @property
    def player_lap_dist(self) -> float:
        """Authoritative high-frequency player lap distance in meters from Delta dead-reckoning."""
        return self.lap_dist

    @property
    def live_delta(self) -> float:
        """Live delta to reference in seconds."""
        with self._mutex:
            if self.delta.data is not None:
                return float(self.delta.data.live_delta)
            return 0.0

    @property
    def display_delta(self) -> float:
        """Display delta to reference in seconds (frozen at sectors/finish)."""
        with self._mutex:
            if self.delta.data is not None:
                return float(self.delta.data.display_delta)
            return 0.0

    @property
    def delta_str(self) -> str:
        """Formatted delta string (e.g. '+0.123', '-0.456', '--:--.---')."""
        with self._mutex:
            if self.delta.data is not None:
                return str(self.delta.data.delta_str)
            return "--:--.---"

    @property
    def has_delta_reference(self) -> bool:
        """True if an active reference profile is loaded."""
        with self._mutex:
            if self.delta.data is not None:
                return bool(self.delta.data.has_reference)
            return False

    @property
    def hit_count_current_lap(self) -> int:
        """Number of collision/contact hits detected during the current lap.
        Sourced from TelemInfo.last_impact_et transitions in the UDP stream.
        Reset to 0 on each lap change (lap_number transition)."""
        with self._mutex:
            self._recalculate_cache()
            return self._cache_hit_count

    @property
    def is_clean_lap(self) -> bool:
        """True if current lap is clean: timing in progress (valid) and 0 hits."""
        with self._mutex:
            self._recalculate_cache()
            return self._cache_is_clean_lap

    @property
    def clean_lap_status(self) -> LapStatus:
        """Clean lap status: LapStatus.CLEAN or LapStatus.DIRTY."""
        with self._mutex:
            self._recalculate_cache()
            return self._cache_clean_lap_status

    @property
    def is_dirty_lap(self) -> bool:
        """True if current lap is dirty (invalid timing or >= 1 hits)."""
        with self._mutex:
            self._recalculate_cache()
            return not self._cache_is_clean_lap

    @property
    def last_impact_et(self) -> float:
        """Elapsed time of the last detected collision/contact impact."""
        with self._mutex:
            return self._last_impact_et

    @property
    def session_timing(self) -> BaseTimingState:
        """Authoritative unified session and player timing state."""
        with self._mutex:
            return self.timing

    @property
    def session_grid(self) -> Optional[FullGridScoringState]:
        """Full grid, multi-car leaderboard and environmental scoring state."""
        with self._mutex:
            return self.grid


class TelemetryPluginView:
    """
    Read-only façade handed to telemetry plugins on each on_* event.

    Deliberately hides every raw-UDP ingestion slot so that accessing the decoded
    payload is structurally impossible from a plugin:
      - ``state.telemetry``, ``state.compact_scoring``, ``state.full_scoring``,
        ``.weather``, ``.system``, ``.extended_state``, ``.force_feedback``,
        ``.graphics``, ``.track_rules``, ``.pit_menu``, ``.opponent_telemetry``
        raise AttributeError;
      - every other consolidated/public access (``timing``, ``grid``, ``delta``,
        cross-channel properties, consume_* helpers) delegates to the backing store.

    Only the ingest layer (parsers, callbacks that physically receive the UDP frame)
    may dereference the real :class:`TelemetryStateStore`; those consumers declare the
    explicit ``_REQUIRE_RAW_INGEST`` capability instead of going through this view.
    """

    _RAW_INGEST_SLOTS = frozenset({
        "telemetry", "opponent_telemetry", "compact_scoring", "full_scoring",
        "weather", "system", "extended_state", "force_feedback", "graphics",
        "track_rules", "pit_menu",
    })

    def __init__(self, _backing: TelemetryStateStore) -> None:
        object.__setattr__(self, "_backing", _backing)

    def __getattr__(self, name: str):
        if name in TelemetryPluginView._RAW_INGEST_SLOTS:
            raise AttributeError(
                f"{type(self).__name__}.{name} is raw UDP ingress state and is not "
                "exposed to plugins; consume the consolidated timing/grid/delta state."
            )
        if name.startswith("_"):
            raise AttributeError(
                f"{type(self).__name__}: internal attributes are not exposed to plugins."
            )
        backing = object.__getattribute__(self, "_backing")
        return getattr(backing, name)

