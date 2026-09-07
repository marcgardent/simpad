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
    suspension_travels: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # unused: from_telem_info recomputes this itself; only ever reaches from_wheel_velocities' fallback at its default
    suspension_velocities: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # dead/stub field, never actually derived from wheel data
    unfiltered_throttle: float = 0.0
    unfiltered_brake: float = 0.0
    filtered_throttle: Optional[float] = None
    filtered_brake: Optional[float] = None
    unfiltered_steering: float = 0.0
    in_realtime: bool = True  # sourced from TelemetryStateStore's PresenceTracker (single fused source); this default is only used by the from_wheel_velocities fallback path
    gear: int = 0
    fuel: float = 0.0
    total_laps: int = 0
    laps_completed: int = 0
    aero_downforce: float = 0.0  # unused by the real path (to_sensors() no longer passes it); kept only as the from_wheel_velocities fallback's input, always 0.0 there since raw_telemetry is None
    lap_flag: int = 2
    track_cut_state: Optional[Union[str, int]] = None  # TODO MGT FUCK Union et Optionnal fait un enum ; TODO SRP: derived from lap_flag by an if/elif duplicated 3x (process_telemetry/process_compact_scoring/process_full_scoring)
    track_limits_steps: int = 0
    num_penalties: int = 0
    track_limits_steps_per_point: int = 0
    track_limits_steps_per_penalty: int = 0
    grip_fractions: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    is_on_track: bool = True  # sourced from TelemetryStateStore (single canonical formula, >= 3 wheels on track — see §5.1 of the architecture plan)
    wheels_on_track: int = 4  # sourced from TelemetryStateStore
    surface_types: Tuple[int, int, int, int] = (0, 0, 0, 0)
    terrain_names: Tuple[str, str, str, str] = ("", "", "", "")
    raw_scoring: Optional[Union[FullScoringSession, CompactScoring]] = None # TODO FUck Union
    raw_telemetry: Optional[TelemInfo] = None

    def to_sensors(self) -> VehicleSensors:
        if self.raw_telemetry is not None:
            return VehicleSensors.from_telem_info(
                telem=self.raw_telemetry,
                scoring=self.raw_scoring,
                # aero_downforce left unset (None): from_telem_info computes it itself
                # from the front/rear downforce fields already on raw_telemetry — no
                # need for LMUParser to duplicate that formula (see §Phase A of the
                # architecture plan).
                lap_flag=self.lap_flag,
                track_cut_state=self.track_cut_state,
                in_realtime=self.in_realtime,
            )

        # remaining_laps: left at from_wheel_velocities' default (0) — this fallback
        # only fires transiently, before the first TelemInfo has ever been decoded;
        # the SDK's from_telem_info() (real path above) already computes the complete
        # version from `scoring` (CompactScoring/FullScoringSession/dict), so this
        # duplicate total_laps-minus-laps_completed formula served no purpose here.
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
            explicit_aero_load=self.aero_downforce,
            lap_flag=self.lap_flag,
            track_cut_state=self.track_cut_state,
            grip_fractions=self.grip_fractions,
        )


class LMUParser:
    """
    Standard binary SIMP UDP packet decoder (isiMotor-RawUDP / Le Mans Ultimate).
    """


    # Unique DeltaEngine instance
    _delta_engine: DeltaEngine = DeltaEngine()

    # Persistent scoring & telemetry state
    _last_fuel: float = 0.0
    _last_total_laps: int = 0
    _last_laps_completed: int = 0

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
    _last_grips: tuple = (1.0, 1.0, 1.0, 1.0)

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

        # aero_downforce: no longer computed here — VehicleSensors.from_telem_info()
        # derives it itself from raw_telemetry's front/rear downforce fields (see
        # TelemetryData.to_sensors()); duplicating the formula here served no purpose
        # in the real (raw_telemetry is not None) path.

        wheels = telem.wheels
        if wheels and len(wheels) >= 4:
            cls._last_lpv = tuple(float(w.longitudinal_patch_vel) for w in wheels[:4])
            cls._last_lgv = tuple(float(w.longitudinal_ground_vel) for w in wheels[:4])
            cls._last_lat_pv = tuple(float(w.lateral_patch_vel) for w in wheels[:4])
            cls._last_lat_gv = tuple(float(w.lateral_ground_vel) for w in wheels[:4])
            cls._last_grips = tuple(float(w.grip_fraction) for w in wheels[:4])

        # wheels_on_track/is_on_track/surface_types/terrain_names: no longer computed
        # here — TelemetryStateStore.update_telemetry() (called below) derives them
        # from this exact TelemInfo using the single canonical formula (>= 3 wheels on
        # a legal surface, see §5.1 of the architecture plan); read back live in
        # _build_telemetry_snapshot() and in the surface-event diagnostic below.

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

        speed = float(telem.speed_mps)

        # Presence (in_realtime/in_garage) is fused once by TelemetryStateStore's
        # PresenceTracker (simpulse_sdk/models/presence.py) from every relevant
        # channel — this parser neither computes nor caches it. In production
        # PluginManager.dispatch_packet already fed this exact TelemInfo to the Store
        # before routing here; this call is redundant there but load-bearing for
        # callers that invoke process_telemetry() directly, bypassing TelemetryBus
        # (must run before _build_telemetry_snapshot() below, not after).
        try:
            TelemetryStateStore.get_instance().update_telemetry(telem, timestamp=time.time())
        except Exception:
            pass

        snap = cls._build_telemetry_snapshot()
        try:
            from .telemetry_logger import TelemetryDiagnosticLogger
            TelemetryDiagnosticLogger.get_instance().log_sample(
                sensors=snap.to_sensors(),
                raw_lpv=cls._last_lpv,
                raw_lgv=cls._last_lgv,
            )
            from .overlay_anomaly_logger import OverlayAnomalyLogger
            store = TelemetryStateStore.get_instance()
            in_realtime = store.in_realtime
            OverlayAnomalyLogger.get_instance().check_telemetry_anomaly(
                speed_kmh=speed * 3.6,
                throttle_pct=cls._last_unfiltered_throttle * 100.0,
                brake_pct=cls._last_unfiltered_brake * 100.0,
                gear=cls._last_gear,
                in_realtime=in_realtime,
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
                raw_data_summary=f"lap_num={telem.lap_number} gear={telem.gear} flap_legal={telem.rear_flap_legal_status} in_rt={in_realtime}",
            )
            TrackLimitsLogger.get_instance().log_surface_event(
                source="TelemInfo(120Hz)",
                is_on_track=store.is_on_track,
                wheels_on_track=store.wheels_on_track,
                surface_types=store.surface_types,
                terrain_names=store.terrain_names,
                speed_kmh=speed * 3.6,
                throttle_pct=cls._last_unfiltered_throttle * 100.0,
                brake_pct=cls._last_unfiltered_brake * 100.0,
                lap_num=int(telem.lap_number),
                sector=cls._delta_engine.current_sector,
                lap_flag=cls._last_lap_flag,
            )
        except Exception:
            pass
        return snap

    @classmethod
    def process_compact_scoring(cls, scoring: CompactScoring) -> TelemetryData:
        """Processes a binary CompactScoring packet (SIMP Type 2)."""
        cls._last_compact_scoring = scoring
        # Presence: fused once by TelemetryStateStore's PresenceTracker from this
        # exact packet — TelemetryBus already routed it there before LMUParser ever
        # runs; this parser does not re-derive it (see process_telemetry's NOTE and
        # simpulse_sdk/models/presence.py).

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

        # Presence: fused once by TelemetryStateStore's PresenceTracker from this
        # exact packet — see process_compact_scoring's NOTE above.
        current_speed = float(cls._last_telem_info.speed_mps) if cls._last_telem_info else 0.0

        if session.lmu:
            cls._last_steps_per_point = int(session.lmu.track_limits_steps_per_point)
            cls._last_steps_per_penalty = int(session.lmu.track_limits_steps_per_penalty)

        if player_veh and (player_veh.is_player or player_veh.control == 0):
            cls._player_slot_id = int(player_veh.id)

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
        # Presence: fused once by TelemetryStateStore's PresenceTracker from this
        # exact event — see process_compact_scoring's NOTE above. In production the
        # Store has already ingested this event by the time LMUParser sees it, so
        # there is no reliable "before" value to diff here any more — log the
        # resulting state, informational only, not a claimed before/after toggle.
        try:
            from .overlay_anomaly_logger import OverlayAnomalyLogger
            OverlayAnomalyLogger.get_instance().log_event(
                "SYSTEM_EVENT_REALTIME",
                f"SystemEvent(event_id={event.event_id}) -> in_realtime={TelemetryStateStore.get_instance().in_realtime}"
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
            # Presence: fused once by TelemetryStateStore's PresenceTracker from this
            # exact packet — see process_compact_scoring's NOTE above.
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
        store = TelemetryStateStore.get_instance()
        return TelemetryData(
            longitudinal_patch_vel=cls._last_lpv,
            longitudinal_ground_vel=cls._last_lgv,
            lateral_patch_vel=cls._last_lat_pv,
            lateral_ground_vel=cls._last_lat_gv,
            engine_rpm=cls._last_engine_rpm,
            engine_max_rpm=cls._last_engine_max_rpm,
            # suspension_travels/suspension_velocities: left at TelemetryData's default
            # (0,0,0,0) — dead in the real path (from_telem_info recomputes travels
            # itself from raw_telemetry; velocities was never anything but a stub),
            # only reached by the from_wheel_velocities fallback before any TelemInfo
            # has arrived, where it was already always (0,0,0,0).
            unfiltered_throttle=cls._last_unfiltered_throttle,
            unfiltered_brake=cls._last_unfiltered_brake,
            filtered_throttle=cls._last_filtered_throttle,
            filtered_brake=cls._last_filtered_brake,
            unfiltered_steering=cls._last_unfiltered_steering,
            in_realtime=store.in_realtime,
            gear=cls._last_gear,
            fuel=cls._last_fuel,
            total_laps=cls._last_total_laps,
            laps_completed=cls._last_laps_completed,
            lap_flag=cls._last_lap_flag,
            track_cut_state=cls._last_track_cut_state,
            track_limits_steps=cls._last_track_limits_steps,
            num_penalties=cls._last_num_penalties,
            track_limits_steps_per_point=cls._last_steps_per_point,
            track_limits_steps_per_penalty=cls._last_steps_per_penalty,
            grip_fractions=cls._last_grips,
            is_on_track=store.is_on_track,
            wheels_on_track=store.wheels_on_track,
            surface_types=store.surface_types,
            terrain_names=store.terrain_names,
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


