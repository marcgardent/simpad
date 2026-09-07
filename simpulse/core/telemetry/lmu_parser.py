"""
SimPulse Telemetry — Standard ISI/LMU Binary Telemetry Parser.
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
    """Canonical MM:ss.mmm sector/lap display ('--' when unknown).

    Delegates to the single project formatter (simpulse_sdk) so the Full-scoring
    path emits exactly the same clock style as DeltaEngine — never the legacy
    bare 'ss.mmm' or unpadded 'M:ss.mmm' forms.
    """
    from simpulse_sdk import format_sector_time as _fmt
    return _fmt(seconds, missing="--")


@dataclass
class TelemetryData:
    """Structured representation of decoded telemetry.

    Deliberately holds ONLY what LMUParser itself decodes or derives from the raw
    packet in hand (physics, wheels, garage/pits, raw lap/track-limits flags) — never
    delta/timing/sector-status fields. Those are DeltaEngine's business data (live
    delta, estimated lap time, sector time/colour, current sector, last-lap status,
    lap-freeze) and reach VehicleSensors exactly once, at
    TelemetryBus._apply_delta_fields(), sourced from the authoritative LapDeltaPacket.
    A parser decodes; it does not carry, mirror, or invent another engine's output.
    """
    longitudinal_patch_vel: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    longitudinal_ground_vel: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    lateral_patch_vel: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    lateral_ground_vel: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    engine_rpm: float = 0.0
    engine_max_rpm: float = 7500.0
    suspension_travels: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # TODO SRP: normalized (deflection/0.10, clamped) in process_telemetry — a calibration formula, not a decode
    suspension_velocities: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # TODO SRP: hardcoded (0,0,0,0) placeholder in process_telemetry, never actually computed from wheel data — dead/stub field
    unfiltered_throttle: float = 0.0
    unfiltered_brake: float = 0.0
    filtered_throttle: Optional[float] = None
    filtered_brake: Optional[float] = None
    unfiltered_steering: float = 0.0
    in_realtime: bool = True  # TODO SRP: garage/pause state machine, re-derived independently (different heuristic each time) in process_telemetry, process_compact_scoring, process_full_scoring, process_system_event and the ExtendedState branch of process_packet — see _last_in_realtime/_in_garage_trap
    gear: int = 0
    fuel: float = 0.0
    total_laps: int = 0
    laps_completed: int = 0
    aero_downforce: float = 0.0  # TODO SRP: computed (min(100, (front+rear)/50)) in process_telemetry, not decoded
    lap_flag: int = 2
    track_cut_state: Optional[Union[str, int]] = None  # TODO MGT FUCK Union et Optionnal fait un enum ; TODO SRP: derived from lap_flag by an if/elif duplicated 3x (process_telemetry/process_compact_scoring/process_full_scoring)
    track_limits_steps: int = 0
    num_penalties: int = 0
    track_limits_steps_per_point: int = 0
    track_limits_steps_per_penalty: int = 0
    grip_fractions: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    is_on_track: bool = True  # TODO SRP: derived (wheels_on_track > 0), not decoded
    wheels_on_track: int = 4  # TODO SRP: aggregated from surface_types (count not in {2,3,4}), not decoded
    surface_types: Tuple[int, int, int, int] = (0, 0, 0, 0)
    terrain_names: Tuple[str, str, str, str] = ("", "", "", "")
    raw_scoring: Optional[Union[FullScoringSession, CompactScoring]] = None # TODO FUck Union
    raw_telemetry: Optional[TelemInfo] = None

    def to_sensors(self) -> VehicleSensors:
        if self.raw_telemetry is not None:
            return VehicleSensors.from_telem_info(
                telem=self.raw_telemetry,
                scoring=self.raw_scoring,
                explicit_aero_load=self.aero_downforce,
                lap_flag=self.lap_flag,
                track_cut_state=self.track_cut_state,
                in_realtime=self.in_realtime,
            )

        # TODO SRP: remaining_laps is computed here (total_laps - laps_completed), not decoded
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
            explicit_aero_load=self.aero_downforce,
            lap_flag=self.lap_flag,
            track_cut_state=self.track_cut_state,
            grip_fractions=self.grip_fractions,
        )


class LMUParser:
    """
    Standard binary SIMP UDP packet decoder (isiMotor-RawUDP / Le Mans Ultimate).
    """

    # TODO SRP: garage/pause detection state machine — 5 independent, slightly different
    # heuristics recompute these two flags (process_telemetry via speed thresholds,
    # process_compact_scoring via in_garage_stall+speed, process_full_scoring via
    # game_phase+speed, process_system_event via event_id, ExtendedState branch of
    # process_packet via in_realtime_fc+speed). One state, five divergent derivations.
    _last_in_realtime: bool = True
    _in_garage_trap: bool = False

    # Unique DeltaEngine instance
    _delta_engine: DeltaEngine = DeltaEngine()

    # Persistent scoring & telemetry state
    _last_fuel: float = 0.0
    _last_total_laps: int = 0
    _last_laps_completed: int = 0
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
        """
        Convert a TelemInfo or TelemetryData instance into VehicleSensors.

        Architecture Context on the 3 Telemetry Structures:
          1. TelemInfo: Low-level C struct / raw UDP packet from isimotor_rawudp_client (hardware wire format).
          2. TelemetryData: Intermediate parser snapshot in lmu_parser (internal buffer holding raw arrays).
          3. VehicleSensors: High-level normalized domain model in simpulse_sdk (0.0-1.0 signals, ready for UI & plugins).
        """
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

        # TODO SRP: aero_downforce is COMPUTED here (front+rear downforce combined into
        # a normalized 0-100 "load %" via an arbitrary /50 formula) — not decoded.
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
            # TODO SRP: suspension_travels COMPUTED (deflection/0.10, clamped 0..1) — a
            # calibration formula guessing a max deflection, not a decode.
            cls._last_travels = tuple(min(1.0, max(0.0, d / 0.10)) for d in raw_deflections)
            cls._last_grips = tuple(float(w.grip_fraction) for w in wheels[:4])
            # TODO SRP: suspension_velocities is a hardcoded stub, never actually derived
            # from wheel data — dead field kept at (0,0,0,0).
            cls._last_susp_vels = (0.0, 0.0, 0.0, 0.0)
            cls._last_surface_types = tuple(int(w.surface_type) for w in wheels[:4])
            cls._last_terrain_names = tuple(str(w.terrain_name).strip() for w in wheels[:4])
            # TODO SRP: wheels_on_track/is_on_track COMPUTED from surface_types (business
            # rule: which surface codes count as "off track") — not decoded.
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

        # NOTE: does NOT call cls._delta_engine.update_physics() here — TelemetryBus
        # already fed this exact TelemInfo to ReferenceLapManager.update_physics()
        # (same shared DeltaEngine instance) before routing here; calling it again
        # double-processed every physics tick (double EMA smoothing, wasted CPU).
        # Delta/sector display state is DeltaEngine's alone; this parser neither caches
        # nor carries it — diagnostics below read cls._delta_engine directly, and
        # TelemetryBus._apply_delta_fields() is the single place VehicleSensors gets it.

        # LMU track limits / investigation state extraction
        tl_steps = 0
        if telem.lmu:
            tl_steps = int(telem.lmu.track_limits_steps)
            cls._last_track_limits_steps = tl_steps

        # TODO SRP: track_cut_state COMPUTED from lap_flag (1 of 3 near-identical
        # if/elif copies of this same rule — see process_compact_scoring/process_full_scoring).
        if cls._last_lap_flag == 1:
            cls._last_track_cut_state = "yellow"
        elif cls._last_lap_flag == 0:
            cls._last_track_cut_state = "invalid"
        else:
            cls._last_track_cut_state = "green"

        # TODO SRP: garage/pause detection (1 of 5 independent heuristics for the same
        # in_realtime/_in_garage_trap state — see class docstring TODO above).
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
                sector=cls._delta_engine.current_sector,
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
                sector=cls._delta_engine.current_sector,
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
        # TODO SRP: garage/pause detection (2 of 5 independent heuristics for the same
        # in_realtime/_in_garage_trap state — see class docstring TODO above).
        current_speed = float(cls._last_telem_info.speed_mps) if cls._last_telem_info else 0.0
        is_in_garage = bool(scoring.in_garage_stall) or (not bool(scoring.in_realtime) and current_speed < 3.0)
        cls._in_garage_trap = is_in_garage
        cls._last_in_realtime = not is_in_garage

        if 0 < scoring.max_laps < 1000:
            cls._last_total_laps = int(scoring.max_laps)

        cls._last_laps_completed = int(scoring.total_laps)
        cls._last_lap_flag = int(scoring.count_lap_flag)
        # TODO SRP: track_cut_state COMPUTED from lap_flag (2 of 3 near-identical
        # if/elif copies of this same rule).
        if cls._last_lap_flag == 1:
            cls._last_track_cut_state = "yellow"
        else:
            if cls._last_lap_flag == 0:
                cls._last_track_cut_state = "invalid"
            else:
                cls._last_track_cut_state = "green"

        # NOTE: does NOT call cls._delta_engine.update_scoring() here — TelemetryBus
        # already fed this exact CompactScoring packet to ReferenceLapManager.update_scoring()
        # (same shared DeltaEngine instance) before routing here; calling it again
        # double-processed every scoring tick. This only *reads* the already-authoritative
        # engine state, including its jitter-guarded current_sector (see delta_engine.py
        # _handle_sector_transition) and its already-computed sector time/colour display
        # (see delta_engine.py _refresh_display_sector_times) — read live below, never
        # cached or re-derived here: a parser decodes, it does not carry another engine's
        # output.
        de = cls._delta_engine
        raw_sec = int(scoring.sector)
        try:
            from .overlay_anomaly_logger import OverlayAnomalyLogger
            OverlayAnomalyLogger.get_instance().check_sector_update(
                current_sector=de.current_sector,
                raw_sector=raw_sec,
                source="CompactScoring",
                s1_time=de.sector1_time_str,
                s2_time=de.sector2_time_str,
                s3_time=de.sector3_time_str,
                s1_delta=de.sector1_delta,
                s2_delta=de.sector2_delta,
                s3_delta=de.sector3_delta,
                lap_dist=de.last_scoring_dist,
                speed_kmh=float(cls._last_telem_info.speed_mps * 3.6) if cls._last_telem_info else 0.0,
            )
            from .track_limits_logger import TrackLimitsLogger
            TrackLimitsLogger.get_instance().log_telemetry_event(
                source="CompactScoring(10Hz)",
                lap_num=int(scoring.total_laps),
                sector=cls._delta_engine.current_sector,
                lap_flag=cls._last_lap_flag,
                track_limits_steps=cls._last_track_limits_steps,
                steps_per_point=cls._last_steps_per_point,
                steps_per_penalty=cls._last_steps_per_penalty,
                num_penalties=cls._last_num_penalties,
                is_lap_invalid=(cls._last_lap_flag in (0, 1)),
                speed_kmh=float(cls._last_telem_info.speed_mps * 3.6) if cls._last_telem_info else 0.0,
                raw_data_summary=f"count_lap_flag={scoring.count_lap_flag} in_rt={scoring.in_realtime} in_garage={scoring.in_garage_stall} sector={scoring.sector} total_laps={scoring.total_laps}",
            )
            # NOTE: does NOT call TelemetryStateStore.update_compact_scoring() here —
            # PluginManager.dispatch_packet() already does this correctly (with the real
            # packet timestamp) on telemetry_bus.packet_received. The call that used to be
            # here passed only 1 of 2 required positional args and always raised TypeError,
            # silently swallowed by this except clause; it never actually updated the store.
        except Exception:
            pass

        return cls._build_telemetry_snapshot()

    @classmethod
    def process_full_scoring(cls, session: FullScoringSession) -> TelemetryData:
        """Processes a multi-car session FullScoringSession (SIMP Type 4)."""
        cls._last_full_scoring = session
        player_veh = session.player_vehicle

        # TODO SRP: garage/pause detection (3 of 5 independent heuristics for the same
        # in_realtime/_in_garage_trap state — see class docstring TODO above).
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

            # TODO SRP: track_cut_state COMPUTED from lap_flag (3 of 3 near-identical
            # if/elif copies of this same rule).
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
                    sector=cls._delta_engine.current_sector,
                    lap_flag=cls._last_lap_flag,
                    track_limits_steps=cls._last_track_limits_steps,
                    steps_per_point=cls._last_steps_per_point,
                    steps_per_penalty=cls._last_steps_per_penalty,
                    num_penalties=cls._last_num_penalties,
                    is_lap_invalid=(cls._last_lap_flag in (0, 1)),
                    speed_kmh=current_speed * 3.6,
                    raw_data_summary=f"count_lap_flag={player_veh.count_lap_flag} flag={player_veh.flag} under_yellow={player_veh.under_yellow} pens={cls._last_num_penalties} tl_steps={tl_steps} in_pits={player_veh.in_pits}",
                )
            except Exception:
                pass

            # NOTE: does NOT call cls._delta_engine.update_scoring() here — TelemetryBus
            # already fed this exact FullScoringSession to ReferenceLapManager.update_scoring()
            # (same shared DeltaEngine instance) before routing here; calling it again
            # double-processed every grid tick. This only *reads* the already-authoritative
            # engine state, including its jitter-guarded current_sector and its already-computed
            # sector time/colour display — read live below, never cached or re-derived here:
            # a parser decodes, it does not carry another engine's output.
            de = cls._delta_engine
            raw_sec = int(player_veh.sector)
            try:
                from .overlay_anomaly_logger import OverlayAnomalyLogger
                OverlayAnomalyLogger.get_instance().check_sector_update(
                    current_sector=de.current_sector,
                    raw_sector=raw_sec,
                    source="FullScoringSession",
                    s1_time=de.sector1_time_str,
                    s2_time=de.sector2_time_str,
                    s3_time=de.sector3_time_str,
                    s1_delta=de.sector1_delta,
                    s2_delta=de.sector2_delta,
                    s3_delta=de.sector3_delta,
                    lap_dist=float(player_veh.lap_dist),
                    speed_kmh=current_speed * 3.6,
                )
            except Exception:
                pass

        cls._in_garage_trap = is_in_garage
        cls._last_in_realtime = not is_in_garage

        if 0 < session.max_laps < 1000:
            cls._last_total_laps = int(session.max_laps)

        # NOTE: does NOT call TelemetryStateStore.update_full_scoring() here —
        # PluginManager.dispatch_packet() already does this correctly (with the real
        # packet timestamp) on telemetry_bus.packet_received. The call that used to be
        # here passed only 1 of 2 required positional args and always raised TypeError,
        # silently swallowed by a bare except; it never actually updated the store.

        return cls._build_telemetry_snapshot()

    @classmethod
    def process_system_event(cls, event: SystemEvent) -> TelemetryData:
        """Processes a session / cockpit SystemEvent (SIMP Type 3)."""
        # TODO SRP: garage/pause detection (4 of 5 independent heuristics for the same
        # in_realtime/_in_garage_trap state — see class docstring TODO above).
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
            # TODO SRP: garage/pause detection (5 of 5 independent heuristics for the
            # same in_realtime/_in_garage_trap state — see class docstring TODO above).
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
            aero_downforce=cls._last_aero_downforce,
            lap_flag=cls._last_lap_flag,
            track_cut_state=cls._last_track_cut_state,
            track_limits_steps=cls._last_track_limits_steps,
            num_penalties=cls._last_num_penalties,
            track_limits_steps_per_point=cls._last_steps_per_point,
            track_limits_steps_per_penalty=cls._last_steps_per_penalty,
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


