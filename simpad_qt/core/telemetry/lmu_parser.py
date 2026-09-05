"""
SimPad Telemetry — Standard ISI/LMU Binary Telemetry Parser.
Exclusively implements the official binary SIMP standard protocol via isimotor_rawudp_client.
"""

from dataclasses import dataclass
import time
from typing import Tuple, Optional, Union
import logging

from isimotor_rawudp_client import (
    TelemInfo,
    TelemWheel,
    CompactScoring,
    FullScoringSession,
    VehicleScoring,
    SystemEvent,
    ExtendedState,
    ForceFeedback,
    Graphics,
    WeatherControl,
    decode_packet,
)

from .sensors import VehicleSensors
from .delta_engine import DeltaEngine, format_lap_time
from .state_store import TelemetryStateStore

logger = logging.getLogger(__name__)


def format_time_sec(seconds: float) -> str:
    """Formats seconds into clean representation [MM:]ss.mmm."""
    if seconds <= 0.0:
        return "--"
    minutes = int(seconds // 60)
    rem_sec = seconds % 60.0
    if minutes > 0:
        return f"{minutes}:{rem_sec:06.3f}"
    else:
        return f"{rem_sec:.3f}"


@dataclass
class TelemetryData:
    """Structured representation of decoded telemetry."""
    longitudinal_patch_vel: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    longitudinal_ground_vel: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    lateral_patch_vel: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    lateral_ground_vel: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    engine_rpm: float = 0.0
    engine_max_rpm: float = 7500.0
    suspension_travels: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    suspension_velocities: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    unfiltered_throttle: float = 0.0
    unfiltered_brake: float = 0.0
    filtered_throttle: Optional[float] = None
    filtered_brake: Optional[float] = None
    unfiltered_steering: float = 0.0
    in_realtime: bool = True
    gear: int = 0
    fuel: float = 0.0
    total_laps: int = 0
    laps_completed: int = 0
    delta_time: float = 0.0
    estimated_lap_time: float = 0.0
    estimated_lap_time_str: str = "--:--.---"
    sector1_time: str = "--"
    sector1_status: str = "default"
    sector2_time: str = "--"
    sector2_status: str = "default"
    sector3_time: str = "--"
    sector3_status: str = "default"
    aero_downforce: float = 0.0
    current_sector: int = 1
    sector1_delta: float = 0.0
    sector2_delta: float = 0.0
    sector3_delta: float = 0.0
    lap_flag: int = 2
    track_cut_state: Optional[Union[str, int]] = None
    track_limits_steps: int = 0
    num_penalties: int = 0
    track_limits_steps_per_point: int = 0
    track_limits_steps_per_penalty: int = 0
    has_delta_reference: bool = False
    is_pit_lap: bool = False
    last_lap_time: float = 0.0
    last_lap_time_str: str = "--:--.---"
    last_lap_status: str = "default"
    is_lap_freeze_active: bool = False
    grip_fractions: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    is_on_track: bool = True
    wheels_on_track: int = 4
    surface_types: Tuple[int, int, int, int] = (0, 0, 0, 0)
    terrain_names: Tuple[str, str, str, str] = ("", "", "", "")
    raw_scoring: Optional[Union[FullScoringSession, CompactScoring]] = None
    raw_telemetry: Optional[TelemInfo] = None

    def to_sensors(self) -> VehicleSensors:
        if self.raw_telemetry is not None:
            return VehicleSensors.from_telem_info(
                telem=self.raw_telemetry,
                scoring=self.raw_scoring,
                delta_time=self.delta_time,
                estimated_lap_time=self.estimated_lap_time,
                estimated_lap_time_str=self.estimated_lap_time_str,
                sector1_time=self.sector1_time,
                sector1_status=self.sector1_status,
                sector2_time=self.sector2_time,
                sector2_status=self.sector2_status,
                sector3_time=self.sector3_time,
                sector3_status=self.sector3_status,
                explicit_aero_load=self.aero_downforce,
                current_sector=self.current_sector,
                sector1_delta=self.sector1_delta,
                sector2_delta=self.sector2_delta,
                sector3_delta=self.sector3_delta,
                lap_flag=self.lap_flag,
                track_cut_state=self.track_cut_state,
                has_delta_reference=self.has_delta_reference,
                is_pit_lap=self.is_pit_lap,
                last_lap_time=self.last_lap_time,
                last_lap_time_str=self.last_lap_time_str,
                last_lap_status=self.last_lap_status,
                is_lap_freeze_active=self.is_lap_freeze_active,
                in_realtime=self.in_realtime,
            )

        remaining = max(0, self.total_laps - self.laps_completed) if (self.total_laps > 0 and self.total_laps < 1000) else 0
        return VehicleSensors.from_wheel_velocities(
            self.longitudinal_patch_vel,
            self.longitudinal_ground_vel,
            self.lateral_patch_vel,
            self.lateral_ground_vel,
            engine_rpm=self.engine_rpm,
            engine_max_rpm=self.engine_max_rpm,
            suspension_travels=self.suspension_travels,
            suspension_velocities=self.suspension_velocities,
            in_realtime=self.in_realtime,
            gear=self.gear,
            unfiltered_throttle=self.unfiltered_throttle,
            unfiltered_brake=self.unfiltered_brake,
            filtered_throttle=self.filtered_throttle,
            filtered_brake=self.filtered_brake,
            fuel_level=self.fuel,
            remaining_laps=remaining,
            delta_time=self.delta_time,
            estimated_lap_time=self.estimated_lap_time,
            estimated_lap_time_str=self.estimated_lap_time_str,
            sector1_time=self.sector1_time,
            sector1_status=self.sector1_status,
            sector2_time=self.sector2_time,
            sector2_status=self.sector2_status,
            sector3_time=self.sector3_time,
            sector3_status=self.sector3_status,
            explicit_aero_load=self.aero_downforce,
            current_sector=self.current_sector,
            sector1_delta=self.sector1_delta,
            sector2_delta=self.sector2_delta,
            sector3_delta=self.sector3_delta,
            lap_flag=self.lap_flag,
            track_cut_state=self.track_cut_state,
            has_delta_reference=self.has_delta_reference,
            is_pit_lap=self.is_pit_lap,
            last_lap_time=self.last_lap_time,
            last_lap_time_str=self.last_lap_time_str,
            last_lap_status=self.last_lap_status,
            is_lap_freeze_active=self.is_lap_freeze_active,
            grip_fractions=self.grip_fractions,
        )


class LMUParser:
    """
    Standard binary SIMP UDP packet decoder (isiMotor-RawUDP / Le Mans Ultimate).
    """

    _last_in_realtime: bool = True
    _in_garage_trap: bool = False

    # Unique DeltaEngine instance
    _delta_engine: DeltaEngine = DeltaEngine()

    # Persistent scoring & telemetry state
    _last_fuel: float = 0.0
    _last_total_laps: int = 0
    _last_laps_completed: int = 0
    _last_delta_time: float = 0.0
    _last_sector1_time: str = "--"
    _last_sector1_status: str = "default"
    _last_sector2_time: str = "--"
    _last_sector2_status: str = "default"
    _last_sector3_time: str = "--"
    _last_sector3_status: str = "default"
    _last_aero_downforce: float = 0.0

    _last_gear: int = 1
    _last_engine_rpm: float = 0.0
    _last_engine_max_rpm: float = 7500.0
    _last_unfiltered_throttle: float = 0.0
    _last_unfiltered_brake: float = 0.0
    _last_filtered_throttle: Optional[float] = None
    _last_filtered_brake: Optional[float] = None
    _last_unfiltered_steering: float = 0.0
    _last_lpv: tuple = (0.0, 0.0, 0.0, 0.0)
    _last_lgv: tuple = (0.0, 0.0, 0.0, 0.0)
    _last_lat_pv: tuple = (0.0, 0.0, 0.0, 0.0)
    _last_lat_gv: tuple = (0.0, 0.0, 0.0, 0.0)
    _last_travels: tuple = (0.0, 0.0, 0.0, 0.0)
    _last_grips: tuple = (1.0, 1.0, 1.0, 1.0)
    _last_susp_vels: tuple = (0.0, 0.0, 0.0, 0.0)
    _last_is_on_track: bool = True
    _last_wheels_on_track: int = 4
    _last_surface_types: tuple = (0, 0, 0, 0)
    _last_terrain_names: tuple = ("", "", "", "")

    _last_current_sector: int = 1
    _last_sector1_delta: float = 0.0
    _last_sector2_delta: float = 0.0
    _last_sector3_delta: float = 0.0
    _last_lap_flag: int = 2
    _last_track_cut_state: Optional[Union[str, int]] = "green"
    _last_track_limits_steps: int = 0
    _last_num_penalties: int = 0
    _last_steps_per_point: int = 0
    _last_steps_per_penalty: int = 0
    _player_slot_id: Optional[int] = None

    # Cached domain models from isimotor_rawudp_client
    _last_telem_info: Optional[TelemInfo] = None
    _last_compact_scoring: Optional[CompactScoring] = None
    _last_full_scoring: Optional[FullScoringSession] = None
    _last_extended_state: Optional[ExtendedState] = None
    _last_weather: Optional[WeatherControl] = None
    _last_ffb: Optional[ForceFeedback] = None
    _last_graphics: Optional[Graphics] = None

    @classmethod
    def get_latest_scoring(cls) -> Optional[Union[FullScoringSession, CompactScoring]]:
        """Returns latest scoring packet received."""
        return cls._last_full_scoring or cls._last_compact_scoring

    @classmethod
    def get_latest_full_scoring(cls) -> Optional[FullScoringSession]:
        """Returns latest multi-car FullScoringSession received."""
        return cls._last_full_scoring

    @classmethod
    def get_latest_compact_scoring(cls) -> Optional[CompactScoring]:
        """Returns latest CompactScoring packet received."""
        return cls._last_compact_scoring

    @classmethod
    def get_latest_telemetry_info(cls) -> Optional[TelemInfo]:
        """Returns latest TelemInfo packet received."""
        return cls._last_telem_info

    @classmethod
    def to_vehicle_sensors(cls, data: Union[VehicleSensors, TelemetryData, TelemInfo]) -> VehicleSensors:
        """Convert a TelemInfo or TelemetryData instance into VehicleSensors."""
        if isinstance(data, VehicleSensors):
            return data
        if isinstance(data, TelemetryData):
            return data.to_sensors()
        if isinstance(data, TelemInfo) or hasattr(data, "wheels"):
            snap = cls.process_telemetry(data)
            if snap:
                return snap.to_sensors()
        return VehicleSensors()

    @classmethod
    def _calculate_sector_status(cls, val: float, best_val: float, session_best: float) -> str:
        """Determines sector time status color (purple, green, or default)."""
        if session_best < 999900.0 and val <= (session_best + 0.001):
            return "purple"
        elif best_val > 0.0 and val <= (best_val + 0.001):
            return "green"
        return "default"

    @classmethod
    def _calculate_session_bests(cls, vehicles: list) -> Tuple[float, float, float]:
        """Computes session best sector 1, individual sector 2, and individual sector 3 times."""
        s1, s2_indiv, s3_indiv = 999999.0, 999999.0, 999999.0
        for v in vehicles:
            bs1 = float(v.best_sector1)
            bs2 = float(v.best_sector2)
            blap = float(v.best_lap_time)

            if 0.0 < bs1 < s1:
                s1 = bs1
            if 0.0 < bs1 and 0.0 < bs2 and (bs2 - bs1) > 0.0:
                if (bs2 - bs1) < s2_indiv:
                    s2_indiv = bs2 - bs1
            if 0.0 < bs2 and 0.0 < blap and (blap - bs2) > 0.0:
                if (blap - bs2) < s3_indiv:
                    s3_indiv = blap - bs2
        return s1, s2_indiv, s3_indiv

    @classmethod
    def _update_player_sector_times_from_model(
        cls, player_veh: VehicleScoring, session_bests: Tuple[float, float, float]
    ) -> None:
        """Helper to extract individual sector times and color coding from VehicleScoring."""
        session_best_s1, session_best_s2_indiv, session_best_s3_indiv = session_bests

        # Sector 1
        cur_s1 = float(player_veh.cur_sector1)
        last_s1 = float(player_veh.last_sector1)
        best_s1 = float(player_veh.best_sector1)
        if cur_s1 > 0.0:
            cls._last_sector1_time = format_time_sec(cur_s1)
            cls._last_sector1_status = cls._calculate_sector_status(cur_s1, best_s1, session_best_s1)
        elif last_s1 > 0.0:
            cls._last_sector1_time = format_time_sec(last_s1)
            cls._last_sector1_status = cls._calculate_sector_status(last_s1, best_s1, session_best_s1)

        # Sector 2
        cur_s2 = float(player_veh.cur_sector2)
        last_s2 = float(player_veh.last_sector2)
        best_s2 = float(player_veh.best_sector2)
        best_indiv_s2 = (best_s2 - best_s1) if (best_s2 > 0.0 and best_s1 > 0.0) else -1.0
        if cur_s2 > 0.0 and cur_s1 > 0.0:
            indiv_s2 = cur_s2 - cur_s1
            if indiv_s2 > 0.0:
                cls._last_sector2_time = format_time_sec(indiv_s2)
                cls._last_sector2_status = cls._calculate_sector_status(indiv_s2, best_indiv_s2, session_best_s2_indiv)
        elif last_s2 > 0.0 and last_s1 > 0.0:
            indiv_s2 = last_s2 - last_s1
            if indiv_s2 > 0.0:
                cls._last_sector2_time = format_time_sec(indiv_s2)
                cls._last_sector2_status = cls._calculate_sector_status(indiv_s2, best_indiv_s2, session_best_s2_indiv)

        # Sector 3 (Lap completion)
        last_lap = float(player_veh.last_lap_time)
        best_lap = float(player_veh.best_lap_time)
        if last_lap > 0.0 and cur_s2 > 0.0:
            indiv_s3 = last_lap - cur_s2
            best_indiv_s3 = (best_lap - best_s2) if (best_lap > 0.0 and best_s2 > 0.0) else -1.0
            if indiv_s3 > 0.0:
                cls._last_sector3_time = format_time_sec(indiv_s3)
                cls._last_sector3_status = cls._calculate_sector_status(indiv_s3, best_indiv_s3, session_best_s3_indiv)
        elif last_lap > 0.0 and last_s2 > 0.0:
            indiv_s3 = last_lap - last_s2
            best_indiv_s3 = (best_lap - best_s2) if (best_lap > 0.0 and best_s2 > 0.0) else -1.0
            if indiv_s3 > 0.0:
                cls._last_sector3_time = format_time_sec(indiv_s3)
                cls._last_sector3_status = cls._calculate_sector_status(indiv_s3, best_indiv_s3, session_best_s3_indiv)

    @classmethod
    def process_telemetry(cls, telem: TelemInfo) -> Optional[TelemetryData]:
        """Processes a binary TelemInfo packet from isimotor_rawudp_client."""
        if cls._last_full_scoring and len(cls._last_full_scoring.vehicles) > 1:
            pv = cls._last_full_scoring.player_vehicle
            if pv is not None:
                slot_id = telem.slot_id
                if int(slot_id) != int(pv.id):
                    # Strict multi-car filtering: this packet originates from an opponent / AI
                    return None

        cls._last_telem_info = telem
        cls._last_fuel = telem.fuel

        f_df = abs(float(telem.front_downforce))
        r_df = abs(float(telem.rear_downforce))
        cls._last_aero_downforce = min(100.0, (f_df + r_df) / 50.0)

        wheels = telem.wheels
        if wheels and len(wheels) >= 4:
            cls._last_lpv = tuple(float(w.longitudinal_patch_vel) for w in wheels[:4])
            cls._last_lgv = tuple(float(w.longitudinal_ground_vel) for w in wheels[:4])
            cls._last_lat_pv = tuple(float(w.lateral_patch_vel) for w in wheels[:4])
            cls._last_lat_gv = tuple(float(w.lateral_ground_vel) for w in wheels[:4])
            raw_deflections = tuple(float(w.suspension_deflection) for w in wheels[:4])
            cls._last_travels = tuple(min(1.0, max(0.0, d / 0.10)) for d in raw_deflections)
            cls._last_grips = tuple(float(w.grip_fraction) for w in wheels[:4])
            cls._last_susp_vels = (0.0, 0.0, 0.0, 0.0)
            cls._last_surface_types = tuple(int(w.surface_type) for w in wheels[:4])
            cls._last_terrain_names = tuple(str(w.terrain_name).strip() for w in wheels[:4])
            cls._last_wheels_on_track = sum(1 for s in cls._last_surface_types if s not in (2, 3, 4))
            cls._last_is_on_track = (cls._last_wheels_on_track > 0)

        cls._last_unfiltered_throttle = float(telem.unfiltered_throttle)
        cls._last_unfiltered_brake = float(telem.unfiltered_brake)
        cls._last_filtered_throttle = float(telem.filtered_throttle)
        cls._last_filtered_brake = float(telem.filtered_brake)
        cls._last_unfiltered_steering = float(telem.unfiltered_steering)
        cls._last_gear = int(telem.gear)
        cls._last_engine_rpm = float(telem.engine_rpm)
        cls._last_engine_max_rpm = float(telem.engine_max_rpm) if telem.engine_max_rpm > 1000.0 else 7500.0

        cls._delta_engine.update_physics(
            veh_speed_ms=telem.speed_mps,
            throttle=telem.unfiltered_throttle,
            brake=telem.unfiltered_brake,
            steering=telem.unfiltered_steering,
            gear=telem.gear,
            dt=telem.delta_time,
            elapsed_time=telem.elapsed_time,
            lap_start_et=telem.lap_start_et,
        )
        cls._last_delta_time = cls._delta_engine.display_delta
        cls._last_sector1_delta = cls._delta_engine.sector1_delta
        cls._last_sector2_delta = cls._delta_engine.sector2_delta
        cls._last_sector3_delta = cls._delta_engine.sector3_delta

        # LMU track limits / investigation state extraction
        tl_steps = 0
        if telem.lmu:
            tl_steps = int(telem.lmu.track_limits_steps)
            cls._last_track_limits_steps = tl_steps

        if cls._last_lap_flag == 1:
            cls._last_track_cut_state = "yellow"
        elif cls._last_lap_flag == 0:
            cls._last_track_cut_state = "invalid"
        else:
            cls._last_track_cut_state = "green"

        speed = float(telem.speed_mps)
        is_strictly_in_garage_stall = False
        if cls._last_compact_scoring and cls._last_compact_scoring.in_garage_stall:
            is_strictly_in_garage_stall = True
        elif cls._last_full_scoring and cls._last_full_scoring.player_vehicle and cls._last_full_scoring.player_vehicle.in_garage_stall:
            is_strictly_in_garage_stall = True
        elif cls._last_full_scoring and cls._last_full_scoring.game_phase == 0 and speed < 1.0:
            is_strictly_in_garage_stall = True

        if is_strictly_in_garage_stall:
            cls._in_garage_trap = True
            cls._last_in_realtime = False
        elif speed >= 3.0:
            # Active on-track detection from 10.8 km/h
            cls._in_garage_trap = False
            cls._last_in_realtime = True
        elif cls._in_garage_trap:
            # Maintain pause/garage state if completely stopped after explicit exit
            cls._last_in_realtime = False
        else:
            cls._last_in_realtime = True

        snap = cls._build_telemetry_snapshot()
        try:
            from .telemetry_logger import TelemetryDiagnosticLogger
            TelemetryDiagnosticLogger.get_instance().log_sample(
                sensors=snap.to_sensors(),
                raw_lpv=cls._last_lpv,
                raw_lgv=cls._last_lgv,
            )
            from .overlay_anomaly_logger import OverlayAnomalyLogger
            OverlayAnomalyLogger.get_instance().check_telemetry_anomaly(
                speed_kmh=speed * 3.6,
                throttle_pct=cls._last_unfiltered_throttle * 100.0,
                brake_pct=cls._last_unfiltered_brake * 100.0,
                gear=cls._last_gear,
                in_realtime=cls._last_in_realtime,
                source="LMUParser.TelemInfo",
            )
            from .track_limits_logger import TrackLimitsLogger
            TrackLimitsLogger.get_instance().log_telemetry_event(
                source="TelemInfo(120Hz)",
                lap_num=int(telem.lap_number),
                sector=cls._last_current_sector,
                lap_flag=cls._last_lap_flag,
                track_limits_steps=cls._last_track_limits_steps,
                steps_per_point=cls._last_steps_per_point,
                steps_per_penalty=cls._last_steps_per_penalty,
                num_penalties=cls._last_num_penalties,
                is_lap_invalid=(cls._last_lap_flag in (0, 1)),
                speed_kmh=speed * 3.6,
                throttle_pct=cls._last_unfiltered_throttle * 100.0,
                brake_pct=cls._last_unfiltered_brake * 100.0,
                raw_data_summary=f"lap_num={telem.lap_number} gear={telem.gear} flap_legal={telem.rear_flap_legal_status} in_rt={cls._last_in_realtime}",
            )
            TrackLimitsLogger.get_instance().log_surface_event(
                source="TelemInfo(120Hz)",
                is_on_track=cls._last_is_on_track,
                wheels_on_track=cls._last_wheels_on_track,
                surface_types=cls._last_surface_types,
                terrain_names=cls._last_terrain_names,
                speed_kmh=speed * 3.6,
                throttle_pct=cls._last_unfiltered_throttle * 100.0,
                brake_pct=cls._last_unfiltered_brake * 100.0,
                lap_num=int(telem.lap_number),
                sector=cls._last_current_sector,
                lap_flag=cls._last_lap_flag,
            )
            TelemetryStateStore.get_instance().update_telemetry(telem, timestamp=time.time())
        except Exception:
            pass
        return snap

    @classmethod
    def process_compact_scoring(cls, scoring: CompactScoring) -> TelemetryData:
        """Processes a binary CompactScoring packet (SIMP Type 2)."""
        cls._last_compact_scoring = scoring
        current_speed = float(cls._last_telem_info.speed_mps) if cls._last_telem_info else 0.0
        is_in_garage = bool(scoring.in_garage_stall) or (not bool(scoring.in_realtime) and current_speed < 3.0)
        cls._in_garage_trap = is_in_garage
        cls._last_in_realtime = not is_in_garage

        if 0 < scoring.max_laps < 1000:
            cls._last_total_laps = int(scoring.max_laps)

        cls._last_laps_completed = int(scoring.total_laps)
        cls._last_lap_flag = int(scoring.count_lap_flag)
        if cls._last_lap_flag == 1:
            cls._last_track_cut_state = "yellow"
        else:
            if cls._last_lap_flag == 0:
                cls._last_track_cut_state = "invalid"
            else:
                cls._last_track_cut_state = "green"

        # Sector 1
        if scoring.cur_sector1 > 0.0:
            cls._last_sector1_time = format_time_sec(scoring.cur_sector1)
            cls._last_sector1_status = cls._calculate_sector_status(scoring.cur_sector1, scoring.best_sector1, scoring.best_sector1)
        elif scoring.last_sector1 > 0.0:
            cls._last_sector1_time = format_time_sec(scoring.last_sector1)
            cls._last_sector1_status = cls._calculate_sector_status(scoring.last_sector1, scoring.best_sector1, scoring.best_sector1)

        # Sector 2
        if scoring.cur_sector2_individual > 0.0:
            cls._last_sector2_time = format_time_sec(scoring.cur_sector2_individual)
            b2 = (scoring.best_sector2 - scoring.best_sector1) if (scoring.best_sector2 > 0 and scoring.best_sector1 > 0) else -1.0
            cls._last_sector2_status = cls._calculate_sector_status(scoring.cur_sector2_individual, b2, -1.0)
        elif scoring.last_sector2_individual > 0.0:
            cls._last_sector2_time = format_time_sec(scoring.last_sector2_individual)
            b2 = (scoring.best_sector2 - scoring.best_sector1) if (scoring.best_sector2 > 0 and scoring.best_sector1 > 0) else -1.0
            cls._last_sector2_status = cls._calculate_sector_status(scoring.last_sector2_individual, b2, -1.0)

        # Sector 3
        if scoring.last_sector3_individual > 0.0:
            cls._last_sector3_time = format_time_sec(scoring.last_sector3_individual)
            b3 = (scoring.best_lap_time - scoring.best_sector2) if (scoring.best_lap_time > 0 and scoring.best_sector2 > 0) else -1.0
            cls._last_sector3_status = cls._calculate_sector_status(scoring.last_sector3_individual, b3, -1.0)

        cls._delta_engine.update_scoring(scoring)
        cls._last_delta_time = cls._delta_engine.display_delta
        cls._last_sector1_delta = cls._delta_engine.sector1_delta
        cls._last_sector2_delta = cls._delta_engine.sector2_delta
        cls._last_sector3_delta = cls._delta_engine.sector3_delta

        raw_sec = int(scoring.sector)
        cls._last_current_sector = 3 if raw_sec == 0 else (raw_sec if raw_sec in (1, 2, 3) else 1)
        try:
            from .overlay_anomaly_logger import OverlayAnomalyLogger
            OverlayAnomalyLogger.get_instance().check_sector_update(
                current_sector=cls._last_current_sector,
                raw_sector=raw_sec,
                source="CompactScoring",
                s1_time=cls._last_sector1_time,
                s2_time=cls._last_sector2_time,
                s3_time=cls._last_sector3_time,
                s1_delta=cls._last_sector1_delta,
                s2_delta=cls._last_sector2_delta,
                s3_delta=cls._last_sector3_delta,
                lap_dist=cls._delta_engine.last_scoring_dist,
                speed_kmh=float(cls._last_telem_info.speed_mps * 3.6) if cls._last_telem_info else 0.0,
            )
            from .track_limits_logger import TrackLimitsLogger
            TrackLimitsLogger.get_instance().log_telemetry_event(
                source="CompactScoring(10Hz)",
                lap_num=int(scoring.total_laps),
                sector=cls._last_current_sector,
                lap_flag=cls._last_lap_flag,
                track_limits_steps=cls._last_track_limits_steps,
                steps_per_point=cls._last_steps_per_point,
                steps_per_penalty=cls._last_steps_per_penalty,
                num_penalties=cls._last_num_penalties,
                is_lap_invalid=(cls._last_lap_flag in (0, 1)),
                speed_kmh=float(cls._last_telem_info.speed_mps * 3.6) if cls._last_telem_info else 0.0,
                raw_data_summary=f"count_lap_flag={scoring.count_lap_flag} in_rt={scoring.in_realtime} in_garage={scoring.in_garage_stall} sector={scoring.sector} total_laps={scoring.total_laps}",
            )
            TelemetryStateStore.get_instance().update_compact_scoring(scoring)
        except Exception:
            pass

        return cls._build_telemetry_snapshot()

    @classmethod
    def process_full_scoring(cls, session: FullScoringSession) -> TelemetryData:
        """Processes a multi-car session FullScoringSession (SIMP Type 4)."""
        cls._last_full_scoring = session
        player_veh = session.player_vehicle
        session_bests = cls._calculate_session_bests(session.vehicles)

        current_speed = float(cls._last_telem_info.speed_mps) if cls._last_telem_info else 0.0
        is_in_garage = False
        if session.game_phase == 0 and current_speed < 3.0:
            is_in_garage = True
        elif not session.in_realtime and current_speed < 3.0:
            is_in_garage = True

        if session.lmu:
            cls._last_steps_per_point = int(session.lmu.track_limits_steps_per_point)
            cls._last_steps_per_penalty = int(session.lmu.track_limits_steps_per_penalty)

        if player_veh and (player_veh.is_player or player_veh.control == 0):
            cls._player_slot_id = int(player_veh.id)
            if player_veh.in_garage_stall:
                is_in_garage = True

            cls._last_laps_completed = int(player_veh.total_laps)
            cls._last_lap_flag = int(player_veh.count_lap_flag)

            # LMU track limits / investigation state extraction from VehicleScoring
            tl_steps = 0
            if player_veh.lmu:
                tl_steps = int(player_veh.lmu.track_limits_steps)
                cls._last_track_limits_steps = tl_steps

            cls._last_num_penalties = int(player_veh.num_penalties)

            if cls._last_lap_flag == 1:
                cls._last_track_cut_state = "yellow"
            else:
                if cls._last_lap_flag == 0:
                    cls._last_track_cut_state = "invalid"
                else:
                    cls._last_track_cut_state = "green"

            try:
                from .track_limits_logger import TrackLimitsLogger
                TrackLimitsLogger.get_instance().log_telemetry_event(
                    source="FullScoring(5Hz)",
                    lap_num=int(player_veh.total_laps),
                    sector=cls._last_current_sector,
                    lap_flag=cls._last_lap_flag,
                    track_limits_steps=cls._last_track_limits_steps,
                    steps_per_point=cls._last_steps_per_point,
                    steps_per_penalty=cls._last_steps_per_penalty,
                    num_penalties=cls._last_num_penalties,
                    is_lap_invalid=(cls._last_lap_flag in (0, 1)),
                    speed_kmh=current_speed * 3.6,
                    raw_data_summary=f"count_lap_flag={player_veh.count_lap_flag} flag={player_veh.flag} under_yellow={player_veh.under_yellow} pens={num_pens} tl_steps={tl_steps} in_pits={player_veh.in_pits}",
                )
            except Exception:
                pass

            cls._update_player_sector_times_from_model(player_veh, session_bests)
            cls._delta_engine.update_scoring(session)

            cls._last_delta_time = cls._delta_engine.display_delta
            cls._last_sector1_delta = cls._delta_engine.sector1_delta
            cls._last_sector2_delta = cls._delta_engine.sector2_delta
            cls._last_sector3_delta = cls._delta_engine.sector3_delta

            raw_sec = int(player_veh.sector)
            cls._last_current_sector = 3 if raw_sec == 0 else (raw_sec if raw_sec in (1, 2, 3) else 1)
            try:
                from .overlay_anomaly_logger import OverlayAnomalyLogger
                OverlayAnomalyLogger.get_instance().check_sector_update(
                    current_sector=cls._last_current_sector,
                    raw_sector=raw_sec,
                    source="FullScoringSession",
                    s1_time=cls._last_sector1_time,
                    s2_time=cls._last_sector2_time,
                    s3_time=cls._last_sector3_time,
                    s1_delta=cls._last_sector1_delta,
                    s2_delta=cls._last_sector2_delta,
                    s3_delta=cls._last_sector3_delta,
                    lap_dist=float(player_veh.lap_dist),
                    speed_kmh=current_speed * 3.6,
                )
            except Exception:
                pass

        cls._in_garage_trap = is_in_garage
        cls._last_in_realtime = not is_in_garage

        if 0 < session.max_laps < 1000:
            cls._last_total_laps = int(session.max_laps)

        try:
            TelemetryStateStore.get_instance().update_full_scoring(session)
        except Exception:
            pass

        return cls._build_telemetry_snapshot()

    @classmethod
    def process_system_event(cls, event: SystemEvent) -> TelemetryData:
        """Processes a session / cockpit SystemEvent (SIMP Type 3)."""
        prev_rt = cls._last_in_realtime
        if event.event_id in (1, 3):
            cls._in_garage_trap = False
            cls._last_in_realtime = True
        elif event.event_id in (2, 4):
            cls._in_garage_trap = True
            cls._last_in_realtime = False

        if prev_rt != cls._last_in_realtime:
            try:
                from .overlay_anomaly_logger import OverlayAnomalyLogger
                OverlayAnomalyLogger.get_instance().log_event(
                    "SYSTEM_EVENT_REALTIME_TOGGLE",
                    f"SystemEvent(event_id={event.event_id}) toggled in_realtime from {prev_rt} to {cls._last_in_realtime}"
                )
            except Exception:
                pass

        return cls._build_telemetry_snapshot()

    @classmethod
    def process_packet(
        cls,
        pkt: Union[TelemInfo, CompactScoring, FullScoringSession, SystemEvent, ExtendedState, ForceFeedback, Graphics, WeatherControl, None],
    ) -> Optional[TelemetryData]:
        """Routes any isimotor_rawudp_client domain packet to corresponding specialized method."""
        if isinstance(pkt, TelemInfo):
            return cls.process_telemetry(pkt)
        elif isinstance(pkt, CompactScoring):
            return cls.process_compact_scoring(pkt)
        elif isinstance(pkt, FullScoringSession):
            return cls.process_full_scoring(pkt)
        elif isinstance(pkt, SystemEvent):
            return cls.process_system_event(pkt)
        elif isinstance(pkt, ExtendedState):
            cls._last_extended_state = pkt
            if hasattr(pkt, "in_realtime_fc"):
                is_in_realtime = bool(pkt.in_realtime_fc)
                current_speed = float(cls._last_telem_info.speed_mps) if cls._last_telem_info else 0.0
                if not is_in_realtime and current_speed < 1.0:
                    cls._in_garage_trap = True
                    cls._last_in_realtime = False
                elif current_speed >= 1.0:
                    cls._in_garage_trap = False
                    cls._last_in_realtime = True
            return cls._build_telemetry_snapshot()
        elif isinstance(pkt, WeatherControl):
            cls._last_weather = pkt
            return cls._build_telemetry_snapshot()
        elif isinstance(pkt, ForceFeedback):
            cls._last_ffb = pkt
            return cls._build_telemetry_snapshot()
        elif isinstance(pkt, Graphics):
            cls._last_graphics = pkt
            return cls._build_telemetry_snapshot()
        return None

    @classmethod
    def _build_telemetry_snapshot(cls) -> TelemetryData:
        """Instantiates TelemetryData with current state."""
        return TelemetryData(
            longitudinal_patch_vel=cls._last_lpv,
            longitudinal_ground_vel=cls._last_lgv,
            lateral_patch_vel=cls._last_lat_pv,
            lateral_ground_vel=cls._last_lat_gv,
            engine_rpm=cls._last_engine_rpm,
            engine_max_rpm=cls._last_engine_max_rpm,
            suspension_travels=cls._last_travels,
            suspension_velocities=cls._last_susp_vels,
            unfiltered_throttle=cls._last_unfiltered_throttle,
            unfiltered_brake=cls._last_unfiltered_brake,
            filtered_throttle=cls._last_filtered_throttle,
            filtered_brake=cls._last_filtered_brake,
            unfiltered_steering=cls._last_unfiltered_steering,
            in_realtime=cls._last_in_realtime,
            gear=cls._last_gear,
            fuel=cls._last_fuel,
            total_laps=cls._last_total_laps,
            laps_completed=cls._last_laps_completed,
            delta_time=cls._last_delta_time,
            estimated_lap_time=cls._delta_engine.estimated_lap_time,
            estimated_lap_time_str=cls._delta_engine.estimated_lap_time_str,
            sector1_time=cls._last_sector1_time,
            sector1_status=cls._last_sector1_status,
            sector2_time=cls._last_sector2_time,
            sector2_status=cls._last_sector2_status,
            sector3_time=cls._last_sector3_time,
            sector3_status=cls._last_sector3_status,
            aero_downforce=cls._last_aero_downforce,
            current_sector=cls._last_current_sector,
            sector1_delta=cls._last_sector1_delta,
            sector2_delta=cls._last_sector2_delta,
            sector3_delta=cls._last_sector3_delta,
            lap_flag=cls._last_lap_flag,
            track_cut_state=cls._last_track_cut_state,
            track_limits_steps=cls._last_track_limits_steps,
            num_penalties=cls._last_num_penalties,
            track_limits_steps_per_point=cls._last_steps_per_point,
            track_limits_steps_per_penalty=cls._last_steps_per_penalty,
            has_delta_reference=cls._delta_engine.has_reference,
            is_pit_lap=cls._delta_engine.is_pit_lap,
            last_lap_time=cls._delta_engine.last_completed_lap_time,
            last_lap_time_str=cls._delta_engine.last_completed_lap_time_str,
            last_lap_status=cls._delta_engine.last_completed_lap_status,
            is_lap_freeze_active=cls._delta_engine.is_lap_freeze_active,
            grip_fractions=cls._last_grips,
            is_on_track=cls._last_is_on_track,
            wheels_on_track=cls._last_wheels_on_track,
            surface_types=cls._last_surface_types,
            terrain_names=cls._last_terrain_names,
            raw_scoring=cls.get_latest_scoring(),
            raw_telemetry=cls._last_telem_info,
        )

    @classmethod
    def parse(cls, data: bytes) -> Optional[TelemetryData]:
        """
        Main decoder compliant with binary SIMP standard via isimotor_rawudp_client.
        """
        if not data or len(data) < 24:
            return None

        try:
            pkt = decode_packet(data)
            if pkt is not None:
                return cls.process_packet(pkt)
        except Exception as e:
            logger.debug(f"[LMUParser] SIMP binary decode error: {e}")

        return None


