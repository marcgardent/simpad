"""
SimPulse SDK — Normalized Telemetry Domain Models, Channels & Sensors.
Provides IsiMotor standard domain abstractions, channels, and LMU extension telemetry models.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field, replace, InitVar
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union, Self
from warnings import deprecated

from isimotor_rawudp_client import (
    TelemInfo,
    TelemWheel,
    TelemVect3,
    CompactScoring,
    FullScoringSession,
    WeatherControl,
    ExtendedState,
    ForceFeedback,
    Graphics,
    SystemEvent,
)

from simpulse_sdk.models.delta import ExpectedStatus, LapColorStatus, SectorInfo, SplitStatus
from simpulse_sdk.models.view import TelemetryView, TrackCutState
from simpulse_sdk.models.wheels import WheelSet
from simpulse_sdk.models.ecu import (
    AntiLockECU,
    ChassisECU,
    CockpitECU,
    PowertrainECU,
    TractionControlECU,
    VehicleECU,
)


TelemetryPayload = Union[
    TelemInfo,
    CompactScoring,
    FullScoringSession,
    WeatherControl,
    ExtendedState,
    ForceFeedback,
    Graphics,
    SystemEvent,
    bytes,
    None,
]


class TelemetryChannel(Enum):
    """Available isiMotor / LMU raw UDP telemetry channels."""
    TELEMETRY = "Telemetry"                      # TelemInfo (Player vehicle dynamics, wheels, engine)
    OPPONENT_TELEMETRY = "OpponentTelemetry"    # TelemInfo (Opponent / AI vehicles dynamics)
    COMPACT_SCORING = "CompactScoring"          # CompactScoring (Live timings, lap deltas, sectors, positions)
    FULL_SCORING = "FullScoring"                # FullScoringSession (Full grid standings, vehicle classes, rules)
    WEATHER = "Weather"                         # WeatherControl (Track temp, ambient temp, rain intensity, wind)
    EXTENDED_STATE = "ExtendedState"            # ExtendedState (Headlights, wipers, ignition, flags)
    FORCE_FEEDBACK = "ForceFeedback"            # ForceFeedback (FFB torque and forces)
    GRAPHICS = "Graphics"                       # Graphics (Camera and graphical frame telemetry)
    TRACK_RULES = "TrackRules"                  # TrackRules (Yellow flags, safety vehicle, pit limits)
    PIT_MENU = "PitMenu"                        # PitMenu (Pit stop selections, fuel, tires)
    SYSTEM_EVENTS = "SystemEvents"              # SystemEvents (Session transitions, sector crossings)

    @property
    def display_name(self) -> str:
        names = {
            TelemetryChannel.TELEMETRY: "Player Vehicle Physics (TelemInfo)",
            TelemetryChannel.OPPONENT_TELEMETRY: "Opponents Physics (TelemInfo)",
            TelemetryChannel.COMPACT_SCORING: "Compact Scoring (CompactScoring)",
            TelemetryChannel.FULL_SCORING: "Full Scoring & Grid (FullScoring)",
            TelemetryChannel.WEATHER: "Weather Conditions (WeatherControl)",
            TelemetryChannel.EXTENDED_STATE: "Vehicle State & Lights (ExtendedState)",
            TelemetryChannel.FORCE_FEEDBACK: "Force Feedback (ForceFeedback)",
            TelemetryChannel.GRAPHICS: "Graphics Telemetry (Graphics)",
            TelemetryChannel.TRACK_RULES: "Track Rules & Flags (TrackRules)",
            TelemetryChannel.PIT_MENU: "Pit Strategy Menu (PitMenu)",
            TelemetryChannel.SYSTEM_EVENTS: "System Events (SystemEvents)",
        }
        return names.get(self, self.value)

    @property
    def json_variable_name(self) -> str:
        """Name of the key in CustomPluginVariables.JSON."""
        keys = {
            TelemetryChannel.TELEMETRY: "PlayerTelemetryRate",
            TelemetryChannel.OPPONENT_TELEMETRY: "OpponentTelemetryRate",
            TelemetryChannel.COMPACT_SCORING: "CompactScoringRate",
            TelemetryChannel.FULL_SCORING: "FullScoringRate",
            TelemetryChannel.WEATHER: "WeatherRate",
            TelemetryChannel.EXTENDED_STATE: "ExtendedStateRate",
            TelemetryChannel.FORCE_FEEDBACK: "ForceFeedbackRate",
            TelemetryChannel.GRAPHICS: "GraphicsRate",
            TelemetryChannel.TRACK_RULES: "TrackRulesRate",
            TelemetryChannel.PIT_MENU: "PitMenuRate",
            TelemetryChannel.SYSTEM_EVENTS: "SystemEvents",
        }
        return keys.get(self, f"{self.value}Rate")

    @property
    def available_rates(self) -> List[str]:
        """Allowed rate string options in CustomPluginVariables.JSON."""
        if self == TelemetryChannel.SYSTEM_EVENTS:
            return ["Enabled", "Disabled"]
        if self in (TelemetryChannel.TELEMETRY, TelemetryChannel.OPPONENT_TELEMETRY):
            return ["unlimited", "100Hz", "60Hz", "50Hz", "20Hz", "10Hz", "off"]
        if self in (TelemetryChannel.COMPACT_SCORING, TelemetryChannel.FULL_SCORING):
            return ["50Hz", "20Hz", "10Hz", "5Hz", "2Hz", "1Hz", "off"]
        if self == TelemetryChannel.WEATHER:
            return ["10Hz", "5Hz", "2Hz", "1Hz", "0.5Hz", "off"]
        if self == TelemetryChannel.FORCE_FEEDBACK:
            return ["unlimited", "100Hz", "50Hz", "20Hz", "off"]
        return ["50Hz", "20Hz", "10Hz", "5Hz", "1Hz", "off"]


@dataclass(frozen=True)
class ChannelRequirement:
    """Requirement/desiderata declared by a plugin for a specific telemetry channel."""
    channel: TelemetryChannel
    preferred_hz: int
    required: bool = True
    reason: str = ""


@dataclass
class ChannelMetrics:
    """Real-time performance measurements for a single telemetry channel."""
    channel: TelemetryChannel
    configured_rate: str = "off"
    packet_count: int = 0
    total_bytes: int = 0
    measured_hz: float = 0.0
    measured_kbs: float = 0.0
    last_packet_timestamp: float = 0.0
    is_active: bool = False

    def update_measurement(self, packet_bytes: int, now: float) -> None:
        self.packet_count += 1
        self.total_bytes += packet_bytes
        self.last_packet_timestamp = now
        self.is_active = True


@dataclass(frozen=True)
class TelemetryRawPacket:
    """Strongly-typed packet wrapper dispatched from UDP server to plugins."""
    channel: TelemetryChannel
    data: TelemetryPayload
    raw_bytes_len: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ChannelSample:
    """
    Metadata-only sample of an incoming UDP frame.

    Deliberately carries NO decoded payload: this is the ONLY thing stream / monitor
    plugins may consume per raw frame, so UDP data cannot leak out of the ingest layer.
    """
    channel: TelemetryChannel
    raw_bytes_len: int
    timestamp: float = 0.0


@deprecated("Use VehicleSensors.ecu (VehicleECU) instead — see simpulse_sdk/models/ecu.py")
@dataclass(frozen=True)
class LmuTelemetryData:
    """
    Strongly-typed Le Mans Ultimate specific electronic, cockpit, and ECU data.
    Separates game-specific telemetry extensions from IsiMotor standard core sensors.

    DEPRECATED: this is a flat bag duplicating VehicleSensors.ecu (VehicleECU),
    which splits the same 18 values by business domain (abs/tc/powertrain/
    chassis/cockpit) instead of one ecu_* prefix soup. Kept only because
    `VehicleSensors.lmu` still gets populated for backward compatibility — new
    code should read `.ecu.abs` / `.ecu.tc` / etc. instead. Do not add new
    fields here; extend simpulse_sdk/models/ecu.py.
    """
    ecu_abs_active_raw: Optional[bool] = None
    ecu_tc_active_raw: Optional[bool] = None
    ecu_abs_level: int = 0
    ecu_abs_max: int = 0
    ecu_tc_level: int = 0
    ecu_tc_max: int = 0
    ecu_tc_cut: int = 0
    ecu_tc_cut_max: int = 0
    ecu_tc_slip: int = 0
    ecu_tc_slip_max: int = 0
    ecu_motor_map: int = 0
    ecu_motor_map_max: int = 0
    ecu_brake_migration: int = 0
    ecu_brake_migration_max: int = 0
    ecu_front_arb: int = 0
    ecu_front_arb_max: int = 0
    ecu_rear_arb: int = 0
    ecu_rear_arb_max: int = 0
    ecu_wiper_state: int = 0
    ecu_lift_and_coast: float = 0.0

    @classmethod
    def from_telem_info(cls, telem: TelemInfo) -> Optional[Self]:
        """Extracts LMU-specific ECU telemetry from an isiMotor raw packet if present."""
        lmu_ext = getattr(telem, "lmu", None)
        if lmu_ext is not None and getattr(lmu_ext, "ecu", None) is not None:
            e = lmu_ext.ecu
            return cls(
                ecu_abs_active_raw=bool(e.abs_active),
                ecu_tc_active_raw=bool(e.tc_active),
                ecu_abs_level=max(0, int(e.abs_level)),
                ecu_abs_max=max(0, int(e.abs_max)),
                ecu_tc_level=max(0, int(e.tc_level)),
                ecu_tc_max=max(0, int(e.tc_max)),
                ecu_tc_cut=max(0, int(e.tc_cut)),
                ecu_tc_cut_max=max(0, int(e.tc_cut_max)),
                ecu_tc_slip=max(0, int(e.tc_slip)),
                ecu_tc_slip_max=max(0, int(e.tc_slip_max)),
                ecu_motor_map=max(0, int(e.motor_map)),
                ecu_motor_map_max=max(0, int(e.motor_map_max)),
                ecu_brake_migration=max(0, int(e.brake_migration)),
                ecu_brake_migration_max=max(0, int(e.brake_migration_max)),
                ecu_front_arb=max(0, int(e.front_arb)),
                ecu_front_arb_max=max(0, int(e.front_arb_max)),
                ecu_rear_arb=max(0, int(e.rear_arb)),
                ecu_rear_arb_max=max(0, int(e.rear_arb_max)),
                ecu_wiper_state=int(e.wiper_state),
                ecu_lift_and_coast=float(e.lift_and_coast),
            )
        return None


@dataclass
class _VehicleSensorsFields:
    """
    Dataclass mechanics for VehicleSensors — DO NOT use this class directly,
    use `VehicleSensors` (defined at the bottom of this module), which adds the
    deprecated flat-field property aliases on top of this one.

    Split in two purely because Python dataclasses can't have a field and a
    `@property`/`@deprecated` override of the same name in one class body (the
    property would shadow the field's default at class-construction time) — see
    the `VehicleSensors` docstring for the actual field documentation.
    """

    # 1. Longitudinal slip - Braking / Wheel Lock (FL, FR, RL, RR)
    # DEPRECATED (InitVar only, not stored — see VehicleSensors.front_left_lock).
    front_left_lock: InitVar[float] = 0.0
    front_right_lock: InitVar[float] = 0.0
    rear_left_lock: InitVar[float] = 0.0
    rear_right_lock: InitVar[float] = 0.0

    # 2. Longitudinal slip - Acceleration / TC Spin (FL, FR, RL, RR)
    # DEPRECATED (InitVar only, not stored — see VehicleSensors.front_left_spin).
    front_left_spin: InitVar[float] = 0.0
    front_right_spin: InitVar[float] = 0.0
    rear_left_spin: InitVar[float] = 0.0
    rear_right_spin: InitVar[float] = 0.0

    # 3. Lateral slip - Cornering / Sliding (FL, FR, RL, RR) [0.0 to 1.0]
    # DEPRECATED (InitVar only, not stored — see VehicleSensors.front_left_lat_slip).
    front_left_lat_slip: InitVar[float] = 0.0
    front_right_lat_slip: InitVar[float] = 0.0
    rear_left_lat_slip: InitVar[float] = 0.0
    rear_right_lat_slip: InitVar[float] = 0.0

    # 3b. Signed lateral slip Left (-1.0) / Right (+1.0) for horizontal gauge
    # DEPRECATED (InitVar only, not stored — see VehicleSensors.front_left_lat_signed).
    front_left_lat_signed: InitVar[float] = 0.0
    front_right_lat_signed: InitVar[float] = 0.0
    rear_left_lat_signed: InitVar[float] = 0.0
    rear_right_lat_signed: InitVar[float] = 0.0

    # 4. Engine RPM
    engine_rpm: float = 0.0
    engine_max_rpm: float = 7500.0

    # 5. Suspension Travel (FL, FR, RL, RR) [0.0 to 1.0]
    # DEPRECATED (InitVar only, not stored — see VehicleSensors.front_left_travel).
    front_left_travel: InitVar[float] = 0.0
    front_right_travel: InitVar[float] = 0.0
    rear_left_travel: InitVar[float] = 0.0
    rear_right_travel: InitVar[float] = 0.0

    # 6. Tire Grip Fraction (FL, FR, RL, RR) [0.0 to 1.0]
    # DEPRECATED (InitVar only, not stored — see VehicleSensors.front_left_grip).
    front_left_grip: InitVar[float] = 1.0
    front_right_grip: InitVar[float] = 1.0
    rear_left_grip: InitVar[float] = 1.0
    rear_right_grip: InitVar[float] = 1.0

    # Per-corner composite — the source of truth for everything above (§1-3b, §5-6).
    wheels: WheelSet = field(default_factory=WheelSet)

    # Vehicle speed (m/s)
    vehicle_speed: float = 0.0

    # Unfiltered and filtered pedals (0.0 to 1.0)
    unfiltered_throttle: float = 0.0
    unfiltered_brake: float = 0.0
    filtered_throttle: Optional[float] = None
    filtered_brake: Optional[float] = None

    # Session telemetry, lap timing and energy
    fuel_level: float = 0.0
    remaining_laps: int = 0
    delta_time: float = 0.0
    estimated_lap_time: float = 0.0
    estimated_lap_time_str: str = "--:--.---"
    expected_status: ExpectedStatus = ExpectedStatus.WHITE  # unified pink/purple/green/yellow/white of the projected lap
    sector1_time: str = "--"
    sector1_status: SplitStatus = SplitStatus.DEFAULT
    sector2_time: str = "--"
    sector2_status: SplitStatus = SplitStatus.DEFAULT
    sector3_time: str = "--"
    sector3_status: SplitStatus = SplitStatus.DEFAULT
    explicit_aero_load: float = 0.0
    current_sector: int = 1
    sector1_delta: float = 0.0
    sector2_delta: float = 0.0
    sector3_delta: float = 0.0
    lap_flag: int = 2
    track_cut_state: Optional[Union[TrackCutState, int]] = None
    has_delta_reference: bool = False
    is_pit_lap: bool = False
    last_lap_time: float = 0.0
    last_lap_time_str: str = "--:--.---"
    last_lap_status: LapColorStatus = LapColorStatus.DEFAULT
    is_lap_freeze_active: bool = False

    # On-track state and engaged gear
    in_realtime: bool = True
    is_on_track: bool = True
    wheels_on_track: int = 4
    surface_types: Tuple[int, int, int, int] = (0, 0, 0, 0)
    terrain_names: Tuple[str, str, str, str] = ("", "", "", "")
    gear: int = 0

    # 7. LMU Electronic & Cockpit Data (isiMotor-RawUDP v0.2.0)
    # DEPRECATED (whole block, InitVar only, not stored): use `.ecu.abs`/
    # `.ecu.tc`/`.ecu.powertrain`/`.ecu.chassis`/`.ecu.cockpit` (VehicleECU)
    # instead — see VehicleSensors.ecu_abs_level etc. `lmu` below is a second,
    # separate historical copy of the same 18 values.
    ecu_abs_active_raw: InitVar[Optional[bool]] = None
    ecu_tc_active_raw: InitVar[Optional[bool]] = None
    ecu_abs_level: InitVar[int] = 0
    ecu_abs_max: InitVar[int] = 0
    ecu_tc_level: InitVar[int] = 0
    ecu_tc_max: InitVar[int] = 0
    ecu_tc_cut: InitVar[int] = 0
    ecu_tc_cut_max: InitVar[int] = 0
    ecu_tc_slip: InitVar[int] = 0
    ecu_tc_slip_max: InitVar[int] = 0
    ecu_motor_map: InitVar[int] = 0
    ecu_motor_map_max: InitVar[int] = 0
    ecu_brake_migration: InitVar[int] = 0
    ecu_brake_migration_max: InitVar[int] = 0
    ecu_front_arb: InitVar[int] = 0
    ecu_front_arb_max: InitVar[int] = 0
    ecu_rear_arb: InitVar[int] = 0
    ecu_rear_arb_max: InitVar[int] = 0
    ecu_wiper_state: InitVar[int] = 0
    ecu_lift_and_coast: InitVar[float] = 0.0
    # `lmu` is NOT a stored field: VehicleSensors.lmu below builds it lazily
    # (only when actually read) from `.ecu` instead — see VehicleSensors docstring.

    # ECU composite — the source of truth for the whole §7 block above.
    ecu: VehicleECU = field(default_factory=VehicleECU)

    def __post_init__(
        self,
        front_left_lock, front_right_lock, rear_left_lock, rear_right_lock,
        front_left_spin, front_right_spin, rear_left_spin, rear_right_spin,
        front_left_lat_slip, front_right_lat_slip, rear_left_lat_slip, rear_right_lat_slip,
        front_left_lat_signed, front_right_lat_signed, rear_left_lat_signed, rear_right_lat_signed,
        front_left_travel, front_right_travel, rear_left_travel, rear_right_travel,
        front_left_grip, front_right_grip, rear_left_grip, rear_right_grip,
        ecu_abs_active_raw, ecu_tc_active_raw, ecu_abs_level, ecu_abs_max,
        ecu_tc_level, ecu_tc_max, ecu_tc_cut, ecu_tc_cut_max, ecu_tc_slip, ecu_tc_slip_max,
        ecu_motor_map, ecu_motor_map_max, ecu_brake_migration, ecu_brake_migration_max,
        ecu_front_arb, ecu_front_arb_max, ecu_rear_arb, ecu_rear_arb_max,
        ecu_wiper_state, ecu_lift_and_coast,
    ) -> None:
        """Builds `.wheels`/`.ecu` from the legacy flat InitVar params — the only
        place these deprecated flat values still exist as of this call (they are
        not stored on the instance). Skipped when `wheels`/`ecu` were passed in
        explicitly as composites, which then take priority. See VehicleSensors
        docstring: `.wheels`/`.ecu` are the source of truth going forward, the
        flat constructor kwargs are kept only for backward compatibility."""
        if self.wheels == WheelSet():
            self.wheels = WheelSet.from_tuples(
                locks=(front_left_lock, front_right_lock, rear_left_lock, rear_right_lock),
                spins=(front_left_spin, front_right_spin, rear_left_spin, rear_right_spin),
                lat_slips=(front_left_lat_slip, front_right_lat_slip, rear_left_lat_slip, rear_right_lat_slip),
                lat_signed=(front_left_lat_signed, front_right_lat_signed, rear_left_lat_signed, rear_right_lat_signed),
                travels=(front_left_travel, front_right_travel, rear_left_travel, rear_right_travel),
                grips=(front_left_grip, front_right_grip, rear_left_grip, rear_right_grip),
            )
        if self.ecu == VehicleECU():
            self.ecu = VehicleECU(
                abs=AntiLockECU(active_raw=ecu_abs_active_raw, level=ecu_abs_level, level_max=ecu_abs_max),
                tc=TractionControlECU(
                    active_raw=ecu_tc_active_raw, level=ecu_tc_level, level_max=ecu_tc_max,
                    cut=ecu_tc_cut, cut_max=ecu_tc_cut_max, slip=ecu_tc_slip, slip_max=ecu_tc_slip_max,
                ),
                powertrain=PowertrainECU(
                    motor_map=ecu_motor_map, motor_map_max=ecu_motor_map_max, lift_and_coast=ecu_lift_and_coast,
                ),
                chassis=ChassisECU(
                    brake_migration=ecu_brake_migration, brake_migration_max=ecu_brake_migration_max,
                    front_arb=ecu_front_arb, front_arb_max=ecu_front_arb_max,
                    rear_arb=ecu_rear_arb, rear_arb_max=ecu_rear_arb_max,
                ),
                cockpit=CockpitECU(wiper_state=ecu_wiper_state),
            )

    @classmethod
    def from_wheel_velocities(
        cls,
        long_patch_vels: Tuple[float, float, float, float],
        long_ground_vels: Tuple[float, float, float, float],
        lat_patch_vels: Tuple[float, float, float, float],
        lat_ground_vels: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
        engine_rpm: float = 0.0,
        engine_max_rpm: float = 7500.0,
        suspension_travels: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
        suspension_velocities: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
        in_realtime: bool = True,
        gear: int = 0,
        unfiltered_throttle: float = 0.0,
        unfiltered_brake: float = 0.0,
        filtered_throttle: Optional[float] = None,
        filtered_brake: Optional[float] = None,
        fuel_level: float = 0.0,
        remaining_laps: int = 0,
        delta_time: float = 0.0,
        estimated_lap_time: float = 0.0,
        estimated_lap_time_str: str = "--:--.---",
        sector1_time: str = "--",
        sector1_status: SplitStatus = SplitStatus.DEFAULT,
        sector2_time: str = "--",
        sector2_status: SplitStatus = SplitStatus.DEFAULT,
        sector3_time: str = "--",
        sector3_status: SplitStatus = SplitStatus.DEFAULT,
        explicit_aero_load: float = 0.0,
        current_sector: int = 1,
        sector1_delta: float = 0.0,
        sector2_delta: float = 0.0,
        sector3_delta: float = 0.0,
        lap_flag: int = 2,
        track_cut_state: Optional[Union[TrackCutState, int]] = TrackCutState.GREEN,
        has_delta_reference: bool = False,
        is_pit_lap: bool = False,
        last_lap_time: float = 0.0,
        last_lap_time_str: str = "--:--.---",
        last_lap_status: LapColorStatus = LapColorStatus.DEFAULT,
        is_lap_freeze_active: bool = False,
        grip_fractions: Optional[Tuple[float, float, float, float]] = None,
        ecu_abs_active_raw: Optional[bool] = None,
        ecu_tc_active_raw: Optional[bool] = None,
        ecu_abs_level: int = 0,
        ecu_abs_max: int = 0,
        ecu_tc_level: int = 0,
        ecu_tc_max: int = 0,
        ecu_tc_cut: int = 0,
        ecu_tc_cut_max: int = 0,
        ecu_tc_slip: int = 0,
        ecu_tc_slip_max: int = 0,
        ecu_motor_map: int = 0,
        ecu_motor_map_max: int = 0,
        ecu_brake_migration: int = 0,
        ecu_brake_migration_max: int = 0,
        ecu_front_arb: int = 0,
        ecu_front_arb_max: int = 0,
        ecu_rear_arb: int = 0,
        ecu_rear_arb_max: int = 0,
        ecu_wiper_state: int = 0,
        ecu_lift_and_coast: float = 0.0,
        vehicle_speed: Optional[float] = None,
        is_on_track: bool = True,
        wheels_on_track: int = 4,
        surface_types: Tuple[int, int, int, int] = (0, 0, 0, 0),
        terrain_names: Tuple[str, str, str, str] = ("", "", "", ""),
    ) -> Self:
        """
        Builds a normalized VehicleSensors snapshot by evaluating wheel slip dynamics
        alongside powertrain, chassis, and session timing inputs.
        Also accessible as `VehicleSensors.from_telemetry_snapshot(...)`.
        """
        ut_f = max(0.0, min(1.0, float(unfiltered_throttle)))
        ub_f = max(0.0, min(1.0, float(unfiltered_brake)))
        ft_f = max(0.0, min(1.0, float(filtered_throttle))) if filtered_throttle is not None else ut_f
        fb_f = max(0.0, min(1.0, float(filtered_brake))) if filtered_brake is not None else ub_f

        avg_speed = sum(abs(v) for v in long_ground_vels) / max(1, len(long_ground_vels))
        avg_patch = sum(abs(v) for v in long_patch_vels) / max(1, len(long_patch_vels))
        final_speed = float(vehicle_speed) if vehicle_speed is not None else avg_speed

        travels = tuple(min(1.0, max(0.0, float(t))) for t in suspension_travels)
        if len(travels) < 4:
            travels = travels + (0.0,) * (4 - len(travels))

        if not in_realtime:
            return cls(
                in_realtime=False,
                is_on_track=is_on_track,
                wheels_on_track=wheels_on_track,
                surface_types=surface_types,
                terrain_names=terrain_names,
                vehicle_speed=final_speed,
                engine_rpm=max(0.0, float(engine_rpm)),
                engine_max_rpm=max(1000.0, float(engine_max_rpm)),
                front_left_travel=travels[0],
                front_right_travel=travels[1],
                rear_left_travel=travels[2],
                rear_right_travel=travels[3],
                gear=gear,
                unfiltered_throttle=ut_f,
                unfiltered_brake=ub_f,
                filtered_throttle=ft_f,
                filtered_brake=fb_f,
                fuel_level=fuel_level,
                remaining_laps=remaining_laps,
                delta_time=delta_time,
                estimated_lap_time=estimated_lap_time,
                estimated_lap_time_str=estimated_lap_time_str,
                sector1_time=sector1_time,
                sector1_status=sector1_status,
                sector2_time=sector2_time,
                sector2_status=sector2_status,
                sector3_time=sector3_time,
                sector3_status=sector3_status,
                explicit_aero_load=explicit_aero_load,
                current_sector=current_sector,
                sector1_delta=sector1_delta,
                sector2_delta=sector2_delta,
                sector3_delta=sector3_delta,
                lap_flag=lap_flag,
                track_cut_state=track_cut_state,
                has_delta_reference=has_delta_reference,
                is_pit_lap=is_pit_lap,
            )

        locks = []
        spins = []
        lats = []
        signed_lats = []

        # Telemetry convention auto-detection:
        # If avg_patch is high (> 40% avg_speed), lpv is absolute wheel velocity (omega*R).
        # Otherwise, lpv is contact patch relative slip velocity (Delta-V).
        is_circumferential_mode = (avg_speed > 1.5) and (avg_patch > avg_speed * 0.40)

        LOCK_DEADBAND = 0.04      # 4% slip deadband (filter normal tire rolling compliance)
        LOCK_SATURATION = 0.18    # 18% slip saturation (full scale lockup / trail braking critical zone)
        SPIN_DEADBAND = 0.05      # 5% slip deadband (filter normal drive torque compliance)
        SPIN_SATURATION = 0.20    # 20% slip saturation (full scale power wheelspin)
        LAT_DEADBAND = 0.04       # 4% lateral scrub deadband
        LAT_SATURATION = 0.20     # 20% lateral scrub saturation

        for i in range(4):
            lpv = float(long_patch_vels[i])
            lgv = float(long_ground_vels[i]) if i < len(long_ground_vels) else 0.0
            lat_gv = float(lat_ground_vels[i]) if i < len(lat_ground_vels) else 0.0

            speed = abs(lgv)
            if speed > 1.5:
                if is_circumferential_mode:
                    long_slip = (abs(lpv) - abs(lgv)) / speed
                else:
                    long_slip = (lpv / lgv) if abs(lgv) > 0.001 else (lpv / speed)

                raw_lat = abs(lat_gv) / speed

                # Physical Lockup (wheel rotating slower than road, e.g. braking, downshift, lingering flatspot skid)
                raw_lock = max(0.0, -long_slip)
                lock_val = 0.0 if raw_lock <= LOCK_DEADBAND else min(1.0, (raw_lock - LOCK_DEADBAND) / (LOCK_SATURATION - LOCK_DEADBAND))

                # Physical Drive Wheelspin (wheel rotating faster than road under power)
                raw_spin = max(0.0, long_slip)
                spin_val = 0.0 if raw_spin <= SPIN_DEADBAND else min(1.0, (raw_spin - SPIN_DEADBAND) / (SPIN_SATURATION - SPIN_DEADBAND))

                # Lateral scrub / drift
                lat_slip = 0.0 if raw_lat <= LAT_DEADBAND else min(1.0, (raw_lat - LAT_DEADBAND) / (LAT_SATURATION - LAT_DEADBAND))
                lat_sign = 1.0 if lat_gv >= 0.0 else -1.0
                signed_lat = lat_sign * lat_slip
            else:
                # Below 1.5 m/s (5.4 km/h / standstill): slip is strictly zero (Standstill guard)
                lock_val = 0.0
                spin_val = 0.0
                lat_slip = 0.0
                signed_lat = 0.0

            locks.append(min(1.0, max(0.0, lock_val)))
            spins.append(min(1.0, max(0.0, spin_val)))
            lats.append(min(1.0, max(0.0, lat_slip)))
            signed_lats.append(min(1.0, max(-1.0, signed_lat)))

        if grip_fractions is not None and len(grip_fractions) >= 4:
            grips = [min(1.0, max(0.0, float(g))) for g in grip_fractions[:4]]
        else:
            grips = [max(0.0, min(1.0, 1.0 - max(locks[i], spins[i], lats[i]))) for i in range(4)]

        # Dynamic kerb / vibreur travel intensity from suspension velocity (scaled: 0.40 m/s = 1.0)
        travels = tuple(min(1.0, max(0.0, float(t))) for t in suspension_travels)
        if len(travels) < 4:
            travels = travels + (0.0,) * (4 - len(travels))

        return cls(
            front_left_lock=locks[0],
            front_right_lock=locks[1],
            rear_left_lock=locks[2],
            rear_right_lock=locks[3],
            front_left_spin=spins[0],
            front_right_spin=spins[1],
            rear_left_spin=spins[2],
            rear_right_spin=spins[3],
            front_left_lat_slip=lats[0],
            front_right_lat_slip=lats[1],
            rear_left_lat_slip=lats[2],
            rear_right_lat_slip=lats[3],
            front_left_lat_signed=signed_lats[0],
            front_right_lat_signed=signed_lats[1],
            rear_left_lat_signed=signed_lats[2],
            rear_right_lat_signed=signed_lats[3],
            engine_rpm=max(0.0, float(engine_rpm)),
            engine_max_rpm=max(1000.0, float(engine_max_rpm)),
            front_left_travel=travels[0],
            front_right_travel=travels[1],
            rear_left_travel=travels[2],
            rear_right_travel=travels[3],
            front_left_grip=grips[0],
            front_right_grip=grips[1],
            rear_left_grip=grips[2],
            rear_right_grip=grips[3],
            vehicle_speed=final_speed,
            unfiltered_throttle=ut_f,
            unfiltered_brake=ub_f,
            filtered_throttle=ft_f,
            filtered_brake=fb_f,
            fuel_level=fuel_level,
            remaining_laps=remaining_laps,
            delta_time=delta_time,
            estimated_lap_time=estimated_lap_time,
            estimated_lap_time_str=estimated_lap_time_str,
            sector1_time=sector1_time,
            sector1_status=sector1_status,
            sector2_time=sector2_time,
            sector2_status=sector2_status,
            sector3_time=sector3_time,
            sector3_status=sector3_status,
            explicit_aero_load=explicit_aero_load,
            current_sector=current_sector,
            sector1_delta=sector1_delta,
            sector2_delta=sector2_delta,
            sector3_delta=sector3_delta,
            lap_flag=lap_flag,
            track_cut_state=track_cut_state,
            has_delta_reference=has_delta_reference,
            is_pit_lap=is_pit_lap,
            last_lap_time=last_lap_time,
            last_lap_time_str=last_lap_time_str,
            last_lap_status=last_lap_status,
            is_lap_freeze_active=is_lap_freeze_active,
            in_realtime=True,
            is_on_track=is_on_track,
            wheels_on_track=wheels_on_track,
            surface_types=surface_types,
            terrain_names=terrain_names,
            gear=gear,
            ecu_abs_active_raw=ecu_abs_active_raw,
            ecu_tc_active_raw=ecu_tc_active_raw,
            ecu_abs_level=ecu_abs_level,
            ecu_abs_max=ecu_abs_max,
            ecu_tc_level=ecu_tc_level,
            ecu_tc_max=ecu_tc_max,
            ecu_tc_cut=ecu_tc_cut,
            ecu_tc_cut_max=ecu_tc_cut_max,
            ecu_tc_slip=ecu_tc_slip,
            ecu_tc_slip_max=ecu_tc_slip_max,
            ecu_motor_map=ecu_motor_map,
            ecu_motor_map_max=ecu_motor_map_max,
            ecu_brake_migration=ecu_brake_migration,
            ecu_brake_migration_max=ecu_brake_migration_max,
            ecu_front_arb=ecu_front_arb,
            ecu_front_arb_max=ecu_front_arb_max,
            ecu_rear_arb=ecu_rear_arb,
            ecu_rear_arb_max=ecu_rear_arb_max,
            ecu_wiper_state=ecu_wiper_state,
            ecu_lift_and_coast=ecu_lift_and_coast,
        )

    # Alias with explicit naming intent (wheel slips computation + full snapshot construction)
    from_telemetry_snapshot = from_wheel_velocities

    @classmethod
    def from_telem_info(
        cls,
        telem: TelemInfo,
        scoring: Optional[Union[CompactScoring, FullScoringSession, Dict[str, Union[int, float, str, bool]]]] = None,
        remaining_laps: Optional[int] = None,
        delta_time: float = 0.0,
        estimated_lap_time: float = 0.0,
        estimated_lap_time_str: str = "--:--.---",
        sector1_time: str = "--",
        sector1_status: SplitStatus = SplitStatus.DEFAULT,
        sector2_time: str = "--",
        sector2_status: SplitStatus = SplitStatus.DEFAULT,
        sector3_time: str = "--",
        sector3_status: SplitStatus = SplitStatus.DEFAULT,
        explicit_aero_load: Optional[float] = None,
        current_sector: int = 1,
        sector1_delta: float = 0.0,
        sector2_delta: float = 0.0,
        sector3_delta: float = 0.0,
        lap_flag: int = 2,
        track_cut_state: Optional[Union[TrackCutState, int]] = TrackCutState.GREEN,
        has_delta_reference: bool = False,
        is_pit_lap: bool = False,
        last_lap_time: float = 0.0,
        last_lap_time_str: str = "--:--.---",
        last_lap_status: LapColorStatus = LapColorStatus.DEFAULT,
        is_lap_freeze_active: bool = False,
        in_realtime: bool = True,
    ) -> Self:
        """Instantiates a VehicleSensors object directly from a binary TelemInfo packet of isimotor_rawudp_client."""
        wheels = telem.wheels
        if wheels and len(wheels) >= 4:
            lpv = tuple(float(w.longitudinal_patch_vel) for w in wheels[:4])
            lgv = tuple(float(w.longitudinal_ground_vel) for w in wheels[:4])
            lat_pv = tuple(float(w.lateral_patch_vel) for w in wheels[:4])
            lat_gv = tuple(float(w.lateral_ground_vel) for w in wheels[:4])
            raw_deflections = tuple(float(w.suspension_deflection) for w in wheels[:4])
            travels = tuple(min(1.0, max(0.0, d / 0.10)) for d in raw_deflections)
            raw_grips = tuple(float(w.grip_fraction) for w in wheels[:4])
            surface_types = tuple(int(w.surface_type) for w in wheels[:4])
            terrain_names = tuple(str(w.terrain_name).strip() for w in wheels[:4])
            wheels_on_track = sum(1 for s in surface_types if s not in (2, 3, 4))
            is_on_track = (wheels_on_track >= 3)
        else:
            lpv = (0.0, 0.0, 0.0, 0.0)
            lgv = (0.0, 0.0, 0.0, 0.0)
            lat_pv = (0.0, 0.0, 0.0, 0.0)
            lat_gv = (0.0, 0.0, 0.0, 0.0)
            travels = (0.0, 0.0, 0.0, 0.0)
            raw_grips = (1.0, 1.0, 1.0, 1.0)
            surface_types = (0, 0, 0, 0)
            terrain_names = ("", "", "", "")
            wheels_on_track = 4
            is_on_track = True

        if explicit_aero_load is None:
            f_df = abs(float(telem.front_downforce))
            r_df = abs(float(telem.rear_downforce))
            aero_downforce = min(100.0, (f_df + r_df) / 50.0)
        else:
            aero_downforce = explicit_aero_load

        # `remaining_laps` (from the caller, e.g. from_view() below reading the
        # already-unified BaseTimingState) takes priority. `scoring` stays only
        # for direct callers that never went through the Store/View and still
        # hand this a raw CompactScoring/FullScoringSession/legacy-JSON-dict —
        # each is a *different* shape for the same two fields (max_laps/
        # total_laps live one level down under .player_vehicle for
        # FullScoringSession, top-level for CompactScoring, and under
        # differently-cased keys for the JSON dict), so this three-way
        # isinstance dispatch is the trap: it must be kept in lockstep with
        # those raw formats by hand. Never add a fourth caller here — teach it
        # to compute remaining_laps itself (from BaseTimingState if it has one)
        # and pass that instead.
        if remaining_laps is None:
            remaining_laps = 0
            if isinstance(scoring, CompactScoring):
                if 0 < scoring.max_laps < 1000:
                    remaining_laps = max(0, scoring.max_laps - scoring.total_laps)
            elif isinstance(scoring, FullScoringSession):
                player_v = scoring.player_vehicle
                if player_v and 0 < scoring.max_laps < 1000:
                    remaining_laps = max(0, scoring.max_laps - player_v.total_laps)
            elif isinstance(scoring, dict):
                max_laps = int(scoring.get("mMaxLaps", scoring.get("maxLaps", 0)))
                total_laps = int(scoring.get("mTotalLaps", scoring.get("totalLaps", 0)))
                if 0 < max_laps < 1000:
                    remaining_laps = max(0, max_laps - total_laps)

        engine_rpm = float(telem.engine_rpm)
        engine_max_rpm = float(telem.engine_max_rpm)
        gear = int(telem.gear)
        unfiltered_throttle = float(telem.unfiltered_throttle)
        unfiltered_brake = float(telem.unfiltered_brake)
        filtered_throttle = float(telem.filtered_throttle)
        filtered_brake = float(telem.filtered_brake)
        fuel_level = float(telem.fuel)

        # Extract ECU & Cockpit state from isimotor-rawudp v0.2.0
        ecu = telem.lmu.ecu if telem.lmu else None

        if ecu is not None:
            ecu_abs_raw = bool(ecu.abs_active)
            ecu_tc_raw = bool(ecu.tc_active)
            ecu_abs_level = max(0, int(ecu.abs_level))
            ecu_abs_max = max(0, int(ecu.abs_max))
            ecu_tc_level = max(0, int(ecu.tc_level))
            ecu_tc_max = max(0, int(ecu.tc_max))
            ecu_tc_cut = max(0, int(ecu.tc_cut))
            ecu_tc_cut_max = max(0, int(ecu.tc_cut_max))
            ecu_tc_slip = max(0, int(ecu.tc_slip))
            ecu_tc_slip_max = max(0, int(ecu.tc_slip_max))
            ecu_motor_map = max(0, int(ecu.motor_map))
            ecu_motor_map_max = max(0, int(ecu.motor_map_max))
            ecu_brake_migration = max(0, int(ecu.brake_migration))
            ecu_brake_migration_max = max(0, int(ecu.brake_migration_max))
            ecu_front_arb = max(0, int(ecu.front_arb))
            ecu_front_arb_max = max(0, int(ecu.front_arb_max))
            ecu_rear_arb = max(0, int(ecu.rear_arb))
            ecu_rear_arb_max = max(0, int(ecu.rear_arb_max))
            ecu_wiper_state = int(ecu.wiper_state)
            ecu_lift_and_coast = float(ecu.lift_and_coast)
        else:
            ecu_abs_raw = None
            ecu_tc_raw = None
            ecu_abs_level = 0
            ecu_abs_max = 0
            ecu_tc_level = 0
            ecu_tc_max = 0
            ecu_tc_cut = 0
            ecu_tc_cut_max = 0
            ecu_tc_slip = 0
            ecu_tc_slip_max = 0
            ecu_motor_map = 0
            ecu_motor_map_max = 0
            ecu_brake_migration = 0
            ecu_brake_migration_max = 0
            ecu_front_arb = 0
            ecu_front_arb_max = 0
            ecu_rear_arb = 0
            ecu_rear_arb_max = 0
            ecu_wiper_state = 0
            ecu_lift_and_coast = 0.0

        return cls.from_wheel_velocities(
            long_patch_vels=lpv,
            long_ground_vels=lgv,
            lat_patch_vels=lat_pv,
            lat_ground_vels=lat_gv,
            engine_rpm=engine_rpm,
            engine_max_rpm=engine_max_rpm,
            suspension_travels=travels,
            in_realtime=in_realtime,
            gear=gear,
            unfiltered_throttle=unfiltered_throttle,
            unfiltered_brake=unfiltered_brake,
            filtered_throttle=filtered_throttle,
            filtered_brake=filtered_brake,
            fuel_level=fuel_level,
            vehicle_speed=float(telem.speed_mps),
            remaining_laps=remaining_laps,
            delta_time=delta_time,
            estimated_lap_time=estimated_lap_time,
            estimated_lap_time_str=estimated_lap_time_str,
            sector1_time=sector1_time,
            sector1_status=sector1_status,
            sector2_time=sector2_time,
            sector2_status=sector2_status,
            sector3_time=sector3_time,
            sector3_status=sector3_status,
            explicit_aero_load=aero_downforce,
            current_sector=current_sector,
            sector1_delta=sector1_delta,
            sector2_delta=sector2_delta,
            sector3_delta=sector3_delta,
            lap_flag=lap_flag,
            track_cut_state=track_cut_state,
            has_delta_reference=has_delta_reference,
            is_pit_lap=is_pit_lap,
            last_lap_time=last_lap_time,
            last_lap_time_str=last_lap_time_str,
            last_lap_status=last_lap_status,
            is_lap_freeze_active=is_lap_freeze_active,
            grip_fractions=raw_grips,
            ecu_abs_active_raw=ecu_abs_raw,
            ecu_tc_active_raw=ecu_tc_raw,
            ecu_abs_level=ecu_abs_level,
            ecu_abs_max=ecu_abs_max,
            ecu_tc_level=ecu_tc_level,
            ecu_tc_max=ecu_tc_max,
            ecu_tc_cut=ecu_tc_cut,
            ecu_tc_cut_max=ecu_tc_cut_max,
            ecu_tc_slip=ecu_tc_slip,
            ecu_tc_slip_max=ecu_tc_slip_max,
            ecu_motor_map=ecu_motor_map,
            ecu_motor_map_max=ecu_motor_map_max,
            ecu_brake_migration=ecu_brake_migration,
            ecu_brake_migration_max=ecu_brake_migration_max,
            ecu_front_arb=ecu_front_arb,
            ecu_front_arb_max=ecu_front_arb_max,
            ecu_rear_arb=ecu_rear_arb,
            ecu_rear_arb_max=ecu_rear_arb_max,
            ecu_wiper_state=ecu_wiper_state,
            ecu_lift_and_coast=ecu_lift_and_coast,
            is_on_track=is_on_track,
            wheels_on_track=wheels_on_track,
            surface_types=surface_types,
            terrain_names=terrain_names,
        )

    @classmethod
    def from_view(cls, view: "TelemetryView") -> Self:
        """Instantiates a VehicleSensors object from the consolidated, immutable
        TelemetryView — the single source of truth (data + Engine results). This is
        the sanctioned entry point for the real UDP pipeline: it replaces the old
        LMUParser.process_packet(...).to_sensors() detour (LMUParser is gone — the
        Store/View already carries everything from_telem_info() needs).

        Delegates straight to from_telem_info() once a TelemInfo has been ingested
        (view.raw_telemetry is not None, true after the very first physics packet
        of a session); before that, returns near-default sensors stamped with the
        View's own presence/lap-flag fields.

        `remaining_laps` is computed from `view.timing` (BaseTimingState, already
        the single merge of CompactScoring/FullScoringSession — see
        `BaseTimingState.merge()`) instead of handing from_telem_info() a raw
        scoring packet to re-dispatch on by isinstance: the View path never needs
        that ambiguity, max_laps/total_laps are already unified fields here.
        """
        if view.raw_telemetry is not None:
            remaining_laps = 0
            if 0 < view.timing.max_laps < 1000:
                remaining_laps = max(0, view.timing.max_laps - view.timing.total_laps)
            return cls.from_telem_info(
                telem=view.raw_telemetry,
                remaining_laps=remaining_laps,
                lap_flag=view.lap_flag,
                track_cut_state=view.track_cut_state,
                in_realtime=view.in_realtime,
            )
        return cls(in_realtime=view.in_realtime, lap_flag=view.lap_flag)

    # ── Timing, Sector & Aero Properties ──────────────────────────────────────
    @property
    def delta_time_str(self) -> str:
        """Formatted Delta Chrono (e.g. '-0.150' or '+0.240')."""
        if not self.has_delta_reference or self.lap_flag != 2 or self.is_pit_lap or not self.in_realtime:
            return "--"
        if self.delta_time < -0.0001:
            return f"-{abs(self.delta_time):.3f}"
        elif self.delta_time > 0.0001:
            return f"+{self.delta_time:.3f}"
        return "+0.000"

    def sector_delta_str(self, sector_num: int) -> str:
        """Formatted Live Delta for an active sector (e.g. '-0.150' or '+0.240')."""
        if sector_num == 1:
            val = self.sector1_delta
        elif sector_num == 2:
            val = self.sector2_delta
        elif sector_num == 3:
            val = self.sector3_delta
        else:
            val = 0.0
        if val < 0.0:
            return f"-{abs(val):.3f}"
        elif val > 0.0:
            return f"+{val:.3f}"
        elif val == 0.0 and (self.delta_time != 0.0 or self.sector1_time != "--" or self.sector1_delta != 0.0 or self.sector2_delta != 0.0 or self.sector3_delta != 0.0):
            return "+0.000"
        return "--"

    @property
    def sectors_list(self) -> List[SectorInfo]:
        """Structured list of 3 sectors for SectorTimesWidget."""
        return [
            SectorInfo(
                time=self.sector1_time,
                status=self.sector1_status,
                delta=self.sector1_delta,
                delta_str=self.sector_delta_str(1),
                is_current=(self.current_sector == 1),
            ),
            SectorInfo(
                time=self.sector2_time,
                status=self.sector2_status,
                delta=self.sector2_delta,
                delta_str=self.sector_delta_str(2),
                is_current=(self.current_sector == 2),
            ),
            SectorInfo(
                time=self.sector3_time,
                status=self.sector3_status,
                delta=self.sector3_delta,
                delta_str=self.sector_delta_str(3),
                is_current=(self.current_sector == 3),
            ),
        ]

    # ── High-Level Haptic Sensor Aggregations ─────────────────────────────────
    @property
    def lock_intensity(self) -> float:
        """Over-Braking intensity (Combined Max 4 wheels)."""
        if self.vehicle_speed <= 1.5:
            return 0.0
        return max(c.lock for c in self.wheels)

    @property
    def lock_left(self) -> float:
        """Over-Braking Left side (Max FL, RL)."""
        if self.vehicle_speed <= 1.5:
            return 0.0
        return max(c.lock for c in self.wheels.left)

    @property
    def lock_right(self) -> float:
        """Over-Braking Right side (Max FR, RR)."""
        if self.vehicle_speed <= 1.5:
            return 0.0
        return max(c.lock for c in self.wheels.right)

    @property
    def lock_front(self) -> float:
        """Over-Braking Front axle (Max FL, FR)."""
        if self.vehicle_speed <= 1.5:
            return 0.0
        return max(c.lock for c in self.wheels.front)

    @property
    def lock_rear(self) -> float:
        """Over-Braking Rear axle (Max RL, RR)."""
        if self.vehicle_speed <= 1.5:
            return 0.0
        return max(c.lock for c in self.wheels.rear)

    @property
    def spin_intensity(self) -> float:
        """Over-Acceleration intensity (Combined Max RL/RR)."""
        if self.vehicle_speed <= 1.5:
            return 0.0
        return max(self.wheels.rear_left.spin, self.wheels.rear_right.spin)

    @property
    def spin_left(self) -> float:
        """Over-Acceleration Left wheel (RL)."""
        if self.vehicle_speed <= 1.5:
            return 0.0
        return self.wheels.rear_left.spin

    @property
    def spin_right(self) -> float:
        """Over-Acceleration Right wheel (RR)."""
        if self.vehicle_speed <= 1.5:
            return 0.0
        return self.wheels.rear_right.spin

    @property
    def oversteer_intensity(self) -> float:
        """Oversteer intensity (Combined Max RL/RR)."""
        return max(self.wheels.rear_left.lat_slip, self.wheels.rear_right.lat_slip)

    @property
    def oversteer_left(self) -> float:
        """Oversteer Left wheel (RL)."""
        return self.wheels.rear_left.lat_slip

    @property
    def oversteer_right(self) -> float:
        """Oversteer Right wheel (RR)."""
        return self.wheels.rear_right.lat_slip

    @property
    def understeer_intensity(self) -> float:
        """Understeer intensity (Combined Max FL/FR)."""
        return max(self.wheels.front_left.lat_slip, self.wheels.front_right.lat_slip)

    @property
    def understeer_left(self) -> float:
        """Understeer Left wheel (FL)."""
        return self.wheels.front_left.lat_slip

    @property
    def understeer_right(self) -> float:
        """Understeer Right wheel (FR)."""
        return self.wheels.front_right.lat_slip

    # ── Engine Regime Properties ─────────────────────────────────────────────
    @property
    def rpm_ratio(self) -> float:
        """Engine RPM ratio (0.0 to 1.0 relative to max RPM)."""
        if self.engine_max_rpm <= 0.0:
            return 0.0
        return min(1.0, max(0.0, self.engine_rpm / self.engine_max_rpm))

    @property
    def overrev_intensity(self) -> float:
        """
        Overrev / Upshift Warning Intensity (0.0 to 1.0).
        Ramps up from 0.0 at 90% RPM max to 1.0 at 100% (Redline / Upshift sweet spot).
        Disabled in Neutral (gear == 0).
        """
        if self.gear == 0:
            return 0.0
        r = self.rpm_ratio
        if r <= 0.90:
            return 0.0
        return min(1.0, max(0.0, (r - 0.90) / 0.10))

    @property
    def underrev_intensity(self) -> float:
        """
        Underrev / Downshift Warning Intensity (0.0 to 1.0).
        Ramps up from 0.0 at 45% RPM max down to 1.0 at 20% (Idle / Downshift sweet spot).
        Disabled in Neutral (gear == 0).
        """
        if self.gear == 0:
            return 0.0
        r = self.rpm_ratio
        if r >= 0.45:
            return 0.0
        return min(1.0, max(0.0, (0.45 - r) / 0.25))

    # ── Wheel Suspension Travel Properties (Vibreurs / Curbs) ──────────────────
    @property
    def travel_intensity(self) -> float:
        """Wheel Travel intensity (Combined Max FL, FR, RL, RR)."""
        return max(c.travel for c in self.wheels)

    @property
    def travel_left(self) -> float:
        """Wheel Travel Left side (Max FL, RL)."""
        return max(c.travel for c in self.wheels.left)

    @property
    def travel_right(self) -> float:
        """Wheel Travel Right side (Max FR, RR)."""
        return max(c.travel for c in self.wheels.right)

    # ── Grip Fraction Properties (0.0 to 1.0) ──────────────────────────────────
    @property
    def grip_intensity(self) -> float:
        """Unified 4-wheel Grip Fraction (min of FL, FR, RL, RR clamped [0.0, 1.0])."""
        val = min(c.grip for c in self.wheels)
        return min(1.0, max(0.0, val))

    @property
    def grip_left(self) -> float:
        """Grip Fraction Left side (min of FL, RL clamped [0.0, 1.0])."""
        val = min(c.grip for c in self.wheels.left)
        return min(1.0, max(0.0, val))

    @property
    def grip_right(self) -> float:
        """Grip Fraction Right side (min of FR, RR clamped [0.0, 1.0])."""
        val = min(c.grip for c in self.wheels.right)
        return min(1.0, max(0.0, val))

    # ── Aerodynamic Load Property (0.0 to 1.0) ────────────────────────────────
    @property
    def aero_load(self) -> float:
        """
        Aerodynamic downforce load intensity (0.0 to 1.0).
        Uses explicit telemetry aero load if available, or calculates dynamic pressure from speed (v / v_max).
        """
        if self.explicit_aero_load > 0.0:
            return min(1.0, max(0.0, self.explicit_aero_load / 100.0))
        v = abs(self.vehicle_speed)
        v_max = 83.33  # ~300 km/h
        if v <= 0.0:
            return 0.0
        return min(1.0, max(0.0, (v / v_max) ** 1.5))

    # ── Official Car Electronic Aids (ECU ABS & Traction Control) ─────────────
    @property
    def ecu_abs_active(self) -> float:
        """
        Official Car ECU ABS Active Intervention Intensity (0.0 to 1.0).
        Strictly zero at standstill or speed <= 1.5 m/s, or when ABS is disabled (level 0).
        """
        if not self.in_realtime or self.vehicle_speed <= 1.5:
            return 0.0
        if self.ecu.abs.active_raw is True:
            return 1.0
        # If ABS is explicitly disabled at level 0 on an ABS-equipped car, return 0.0
        if self.ecu.abs.level == 0 and self.ecu.abs.level_max > 0:
            return 0.0
        ub = self.unfiltered_brake
        fb = self.filtered_brake if self.filtered_brake is not None else ub
        if ub > 0.05 and fb is not None and fb < ub - 0.005:
            return min(1.0, max(0.0, (ub - fb) / max(0.01, ub)))
        return 0.0

    @property
    def ecu_tc_active(self) -> float:
        """
        Official Car ECU Traction Control (TC) Active Intervention Intensity (0.0 to 1.0).
        Detects native ECU tc_active flag OR ECU throttle cut during acceleration.
        Strictly filters out upshifts, neutral, and rev-limiter cuts.
        Strictly zero at standstill or speed <= 1.5 m/s.
        """
        if not self.in_realtime or self.vehicle_speed <= 1.5:
            return 0.0
        if self.ecu.tc.active_raw is True:
            return 1.0
        # If TC is explicitly disabled at level 0 on a TC-equipped car, return 0.0
        if self.ecu.tc.level == 0 and self.ecu.tc.level_max > 0:
            return 0.0
        # Throttle cut detection (in gear only)
        if self.gear <= 0:
            return 0.0
        ut = self.unfiltered_throttle
        ft = self.filtered_throttle if self.filtered_throttle is not None else ut
        if ut > 0.08 and ft is not None and ft < ut - 0.01:
            # Filter out rev limiter (near max RPM)
            if self.engine_rpm >= self.engine_max_rpm * 0.98:
                return 0.0
            return min(1.0, max(0.0, (ut - ft) / max(0.01, ut)))
        return 0.0

    def to_telem_info(self) -> TelemInfo:
        """Convert normalized VehicleSensors into an official binary TelemInfo structure."""
        return TelemInfo(
            gear=int(self.gear),
            engine_rpm=float(self.engine_rpm),
            engine_max_rpm=float(self.engine_max_rpm),
            unfiltered_throttle=float(self.unfiltered_throttle),
            unfiltered_brake=float(self.unfiltered_brake),
            filtered_throttle=float(self.filtered_throttle if self.filtered_throttle is not None else self.unfiltered_throttle),
            filtered_brake=float(self.filtered_brake if self.filtered_brake is not None else self.unfiltered_brake),
            fuel=float(self.fuel_level),
            local_vel=TelemVect3(x=0.0, y=0.0, z=float(self.vehicle_speed)),
            wheels=tuple(
                TelemWheel(surface_type=st, terrain_name=tn)
                for st, tn in zip(self.surface_types, self.terrain_names)
            ),
            current_sector=int(self.current_sector),
            delta_time=float(self.delta_time),
            lap_number=int(self.remaining_laps),
        )


class VehicleSensors(_VehicleSensorsFields):
    """
    Dimensionless normalized abstraction of slip sensors (0.0 to 1.0).

    `.wheels` (WheelSet) and `.ecu` (VehicleECU) are the current source of
    truth — see simpulse_sdk/models/wheels.py and ecu.py. The properties below
    (`front_left_lock`, `ecu_abs_level`, etc.) are DEPRECATED read/write aliases
    onto `.wheels`/`.ecu`, kept only for backward compatibility with existing
    plugins/tests — each is flagged via `@deprecated` (PEP 702), so IDEs and
    type-checkers (pyright, mypy ≥ 1.13) mark every usage site. New code should
    read `.wheels.front_left.lock`, `.wheels.axle_avg_grip(front=True)`,
    `.ecu.abs.level`, etc. instead. Do not add new flat per-wheel or
    per-ECU-domain fields/properties here — extend WheelSet/VehicleECU instead.

    Constructing with the legacy flat kwargs (`VehicleSensors(front_left_lock=...)`)
    still works — `_VehicleSensorsFields.__post_init__` back-fills `.wheels`/`.ecu`
    from them — but only these properties are statically flagged as deprecated,
    not the constructor kwargs themselves (PEP 702 doesn't cover per-parameter
    deprecation).
    """

    # ── Per-corner deprecated aliases (write-through to `.wheels`) ────────────
    def update_wheel_corner(self, corner: str, **updates: float) -> None:
        """Public, non-deprecated helper to mutate one TireCorner in place (WheelSet
        is frozen — this rebuilds it via dataclasses.replace). `corner` is one of
        "front_left"/"front_right"/"rear_left"/"rear_right"; `updates` are TireCorner
        field names (lock=, spin=, lat_slip=, lat_signed=, travel=, grip=). Used by
        the deprecated flat-field setters below, and by any caller updating `.wheels`
        without rebuilding the whole WheelSet by hand."""
        old_wheels = self.wheels
        new_corner = replace(getattr(old_wheels, corner), **updates)
        self.wheels = replace(old_wheels, **{corner: new_corner})

    @property
    @deprecated("Use .wheels.front_left.lock instead")
    def front_left_lock(self) -> float:
        return self.wheels.front_left.lock

    @front_left_lock.setter
    def front_left_lock(self, value: float) -> None:
        self.update_wheel_corner("front_left", lock=value)

    @property
    @deprecated("Use .wheels.front_right.lock instead")
    def front_right_lock(self) -> float:
        return self.wheels.front_right.lock

    @front_right_lock.setter
    def front_right_lock(self, value: float) -> None:
        self.update_wheel_corner("front_right", lock=value)

    @property
    @deprecated("Use .wheels.rear_left.lock instead")
    def rear_left_lock(self) -> float:
        return self.wheels.rear_left.lock

    @rear_left_lock.setter
    def rear_left_lock(self, value: float) -> None:
        self.update_wheel_corner("rear_left", lock=value)

    @property
    @deprecated("Use .wheels.rear_right.lock instead")
    def rear_right_lock(self) -> float:
        return self.wheels.rear_right.lock

    @rear_right_lock.setter
    def rear_right_lock(self, value: float) -> None:
        self.update_wheel_corner("rear_right", lock=value)

    @property
    @deprecated("Use .wheels.front_left.spin instead")
    def front_left_spin(self) -> float:
        return self.wheels.front_left.spin

    @front_left_spin.setter
    def front_left_spin(self, value: float) -> None:
        self.update_wheel_corner("front_left", spin=value)

    @property
    @deprecated("Use .wheels.front_right.spin instead")
    def front_right_spin(self) -> float:
        return self.wheels.front_right.spin

    @front_right_spin.setter
    def front_right_spin(self, value: float) -> None:
        self.update_wheel_corner("front_right", spin=value)

    @property
    @deprecated("Use .wheels.rear_left.spin instead")
    def rear_left_spin(self) -> float:
        return self.wheels.rear_left.spin

    @rear_left_spin.setter
    def rear_left_spin(self, value: float) -> None:
        self.update_wheel_corner("rear_left", spin=value)

    @property
    @deprecated("Use .wheels.rear_right.spin instead")
    def rear_right_spin(self) -> float:
        return self.wheels.rear_right.spin

    @rear_right_spin.setter
    def rear_right_spin(self, value: float) -> None:
        self.update_wheel_corner("rear_right", spin=value)

    @property
    @deprecated("Use .wheels.front_left.lat_slip instead")
    def front_left_lat_slip(self) -> float:
        return self.wheels.front_left.lat_slip

    @front_left_lat_slip.setter
    def front_left_lat_slip(self, value: float) -> None:
        self.update_wheel_corner("front_left", lat_slip=value)

    @property
    @deprecated("Use .wheels.front_right.lat_slip instead")
    def front_right_lat_slip(self) -> float:
        return self.wheels.front_right.lat_slip

    @front_right_lat_slip.setter
    def front_right_lat_slip(self, value: float) -> None:
        self.update_wheel_corner("front_right", lat_slip=value)

    @property
    @deprecated("Use .wheels.rear_left.lat_slip instead")
    def rear_left_lat_slip(self) -> float:
        return self.wheels.rear_left.lat_slip

    @rear_left_lat_slip.setter
    def rear_left_lat_slip(self, value: float) -> None:
        self.update_wheel_corner("rear_left", lat_slip=value)

    @property
    @deprecated("Use .wheels.rear_right.lat_slip instead")
    def rear_right_lat_slip(self) -> float:
        return self.wheels.rear_right.lat_slip

    @rear_right_lat_slip.setter
    def rear_right_lat_slip(self, value: float) -> None:
        self.update_wheel_corner("rear_right", lat_slip=value)

    @property
    @deprecated("Use .wheels.front_left.lat_signed instead")
    def front_left_lat_signed(self) -> float:
        return self.wheels.front_left.lat_signed

    @front_left_lat_signed.setter
    def front_left_lat_signed(self, value: float) -> None:
        self.update_wheel_corner("front_left", lat_signed=value)

    @property
    @deprecated("Use .wheels.front_right.lat_signed instead")
    def front_right_lat_signed(self) -> float:
        return self.wheels.front_right.lat_signed

    @front_right_lat_signed.setter
    def front_right_lat_signed(self, value: float) -> None:
        self.update_wheel_corner("front_right", lat_signed=value)

    @property
    @deprecated("Use .wheels.rear_left.lat_signed instead")
    def rear_left_lat_signed(self) -> float:
        return self.wheels.rear_left.lat_signed

    @rear_left_lat_signed.setter
    def rear_left_lat_signed(self, value: float) -> None:
        self.update_wheel_corner("rear_left", lat_signed=value)

    @property
    @deprecated("Use .wheels.rear_right.lat_signed instead")
    def rear_right_lat_signed(self) -> float:
        return self.wheels.rear_right.lat_signed

    @rear_right_lat_signed.setter
    def rear_right_lat_signed(self, value: float) -> None:
        self.update_wheel_corner("rear_right", lat_signed=value)

    @property
    @deprecated("Use .wheels.front_left.travel instead")
    def front_left_travel(self) -> float:
        return self.wheels.front_left.travel

    @front_left_travel.setter
    def front_left_travel(self, value: float) -> None:
        self.update_wheel_corner("front_left", travel=value)

    @property
    @deprecated("Use .wheels.front_right.travel instead")
    def front_right_travel(self) -> float:
        return self.wheels.front_right.travel

    @front_right_travel.setter
    def front_right_travel(self, value: float) -> None:
        self.update_wheel_corner("front_right", travel=value)

    @property
    @deprecated("Use .wheels.rear_left.travel instead")
    def rear_left_travel(self) -> float:
        return self.wheels.rear_left.travel

    @rear_left_travel.setter
    def rear_left_travel(self, value: float) -> None:
        self.update_wheel_corner("rear_left", travel=value)

    @property
    @deprecated("Use .wheels.rear_right.travel instead")
    def rear_right_travel(self) -> float:
        return self.wheels.rear_right.travel

    @rear_right_travel.setter
    def rear_right_travel(self, value: float) -> None:
        self.update_wheel_corner("rear_right", travel=value)

    @property
    @deprecated("Use .wheels.front_left.grip instead")
    def front_left_grip(self) -> float:
        return self.wheels.front_left.grip

    @front_left_grip.setter
    def front_left_grip(self, value: float) -> None:
        self.update_wheel_corner("front_left", grip=value)

    @property
    @deprecated("Use .wheels.front_right.grip instead")
    def front_right_grip(self) -> float:
        return self.wheels.front_right.grip

    @front_right_grip.setter
    def front_right_grip(self, value: float) -> None:
        self.update_wheel_corner("front_right", grip=value)

    @property
    @deprecated("Use .wheels.rear_left.grip instead")
    def rear_left_grip(self) -> float:
        return self.wheels.rear_left.grip

    @rear_left_grip.setter
    def rear_left_grip(self, value: float) -> None:
        self.update_wheel_corner("rear_left", grip=value)

    @property
    @deprecated("Use .wheels.rear_right.grip instead")
    def rear_right_grip(self) -> float:
        return self.wheels.rear_right.grip

    @rear_right_grip.setter
    def rear_right_grip(self, value: float) -> None:
        self.update_wheel_corner("rear_right", grip=value)

    # ── ECU deprecated aliases (write-through to `.ecu`) ───────────────────────
    def update_ecu_domain(self, domain: str, **updates) -> None:
        """Public, non-deprecated helper to mutate one ECU sub-model in place
        (VehicleECU is frozen — this rebuilds it via dataclasses.replace). `domain`
        is one of "abs"/"tc"/"powertrain"/"chassis"/"cockpit"; `updates` are that
        sub-model's field names. Used by the deprecated flat-field setters below,
        and by any caller updating `.ecu` without rebuilding it by hand."""
        old_ecu = self.ecu
        new_domain = replace(getattr(old_ecu, domain), **updates)
        self.ecu = replace(old_ecu, **{domain: new_domain})

    @property
    @deprecated("Use .ecu.abs.active_raw instead")
    def ecu_abs_active_raw(self) -> Optional[bool]:
        return self.ecu.abs.active_raw

    @ecu_abs_active_raw.setter
    def ecu_abs_active_raw(self, value: Optional[bool]) -> None:
        self.update_ecu_domain("abs", active_raw=value)

    @property
    @deprecated("Use .ecu.tc.active_raw instead")
    def ecu_tc_active_raw(self) -> Optional[bool]:
        return self.ecu.tc.active_raw

    @ecu_tc_active_raw.setter
    def ecu_tc_active_raw(self, value: Optional[bool]) -> None:
        self.update_ecu_domain("tc", active_raw=value)

    @property
    @deprecated("Use .ecu.abs.level instead")
    def ecu_abs_level(self) -> int:
        return self.ecu.abs.level

    @ecu_abs_level.setter
    def ecu_abs_level(self, value: int) -> None:
        self.update_ecu_domain("abs", level=value)

    @property
    @deprecated("Use .ecu.abs.level_max instead")
    def ecu_abs_max(self) -> int:
        return self.ecu.abs.level_max

    @ecu_abs_max.setter
    def ecu_abs_max(self, value: int) -> None:
        self.update_ecu_domain("abs", level_max=value)

    @property
    @deprecated("Use .ecu.tc.level instead")
    def ecu_tc_level(self) -> int:
        return self.ecu.tc.level

    @ecu_tc_level.setter
    def ecu_tc_level(self, value: int) -> None:
        self.update_ecu_domain("tc", level=value)

    @property
    @deprecated("Use .ecu.tc.level_max instead")
    def ecu_tc_max(self) -> int:
        return self.ecu.tc.level_max

    @ecu_tc_max.setter
    def ecu_tc_max(self, value: int) -> None:
        self.update_ecu_domain("tc", level_max=value)

    @property
    @deprecated("Use .ecu.tc.cut instead")
    def ecu_tc_cut(self) -> int:
        return self.ecu.tc.cut

    @ecu_tc_cut.setter
    def ecu_tc_cut(self, value: int) -> None:
        self.update_ecu_domain("tc", cut=value)

    @property
    @deprecated("Use .ecu.tc.cut_max instead")
    def ecu_tc_cut_max(self) -> int:
        return self.ecu.tc.cut_max

    @ecu_tc_cut_max.setter
    def ecu_tc_cut_max(self, value: int) -> None:
        self.update_ecu_domain("tc", cut_max=value)

    @property
    @deprecated("Use .ecu.tc.slip instead")
    def ecu_tc_slip(self) -> int:
        return self.ecu.tc.slip

    @ecu_tc_slip.setter
    def ecu_tc_slip(self, value: int) -> None:
        self.update_ecu_domain("tc", slip=value)

    @property
    @deprecated("Use .ecu.tc.slip_max instead")
    def ecu_tc_slip_max(self) -> int:
        return self.ecu.tc.slip_max

    @ecu_tc_slip_max.setter
    def ecu_tc_slip_max(self, value: int) -> None:
        self.update_ecu_domain("tc", slip_max=value)

    @property
    @deprecated("Use .ecu.powertrain.motor_map instead")
    def ecu_motor_map(self) -> int:
        return self.ecu.powertrain.motor_map

    @ecu_motor_map.setter
    def ecu_motor_map(self, value: int) -> None:
        self.update_ecu_domain("powertrain", motor_map=value)

    @property
    @deprecated("Use .ecu.powertrain.motor_map_max instead")
    def ecu_motor_map_max(self) -> int:
        return self.ecu.powertrain.motor_map_max

    @ecu_motor_map_max.setter
    def ecu_motor_map_max(self, value: int) -> None:
        self.update_ecu_domain("powertrain", motor_map_max=value)

    @property
    @deprecated("Use .ecu.chassis.brake_migration instead")
    def ecu_brake_migration(self) -> int:
        return self.ecu.chassis.brake_migration

    @ecu_brake_migration.setter
    def ecu_brake_migration(self, value: int) -> None:
        self.update_ecu_domain("chassis", brake_migration=value)

    @property
    @deprecated("Use .ecu.chassis.brake_migration_max instead")
    def ecu_brake_migration_max(self) -> int:
        return self.ecu.chassis.brake_migration_max

    @ecu_brake_migration_max.setter
    def ecu_brake_migration_max(self, value: int) -> None:
        self.update_ecu_domain("chassis", brake_migration_max=value)

    @property
    @deprecated("Use .ecu.chassis.front_arb instead")
    def ecu_front_arb(self) -> int:
        return self.ecu.chassis.front_arb

    @ecu_front_arb.setter
    def ecu_front_arb(self, value: int) -> None:
        self.update_ecu_domain("chassis", front_arb=value)

    @property
    @deprecated("Use .ecu.chassis.front_arb_max instead")
    def ecu_front_arb_max(self) -> int:
        return self.ecu.chassis.front_arb_max

    @ecu_front_arb_max.setter
    def ecu_front_arb_max(self, value: int) -> None:
        self.update_ecu_domain("chassis", front_arb_max=value)

    @property
    @deprecated("Use .ecu.chassis.rear_arb instead")
    def ecu_rear_arb(self) -> int:
        return self.ecu.chassis.rear_arb

    @ecu_rear_arb.setter
    def ecu_rear_arb(self, value: int) -> None:
        self.update_ecu_domain("chassis", rear_arb=value)

    @property
    @deprecated("Use .ecu.chassis.rear_arb_max instead")
    def ecu_rear_arb_max(self) -> int:
        return self.ecu.chassis.rear_arb_max

    @ecu_rear_arb_max.setter
    def ecu_rear_arb_max(self, value: int) -> None:
        self.update_ecu_domain("chassis", rear_arb_max=value)

    @property
    @deprecated("Use .ecu.cockpit.wiper_state instead")
    def ecu_wiper_state(self) -> int:
        return self.ecu.cockpit.wiper_state

    @ecu_wiper_state.setter
    def ecu_wiper_state(self, value: int) -> None:
        self.update_ecu_domain("cockpit", wiper_state=value)

    @property
    @deprecated("Use .ecu.powertrain.lift_and_coast instead")
    def ecu_lift_and_coast(self) -> float:
        return self.ecu.powertrain.lift_and_coast

    @ecu_lift_and_coast.setter
    def ecu_lift_and_coast(self, value: float) -> None:
        self.update_ecu_domain("powertrain", lift_and_coast=value)

    @property
    @deprecated("Use .ecu (VehicleECU) instead — LmuTelemetryData is a second, "
                "flat copy of the same 18 values")
    def lmu(self) -> LmuTelemetryData:
        """Built lazily, on read, straight from `.ecu` — never stored, so
        constructing/reading a VehicleSensors that never touches `.lmu` never
        pays for or warns about this deprecated shape."""
        abs_, tc, pt, ch, cp = self.ecu.abs, self.ecu.tc, self.ecu.powertrain, self.ecu.chassis, self.ecu.cockpit
        return LmuTelemetryData(
            ecu_abs_active_raw=abs_.active_raw, ecu_tc_active_raw=tc.active_raw,
            ecu_abs_level=abs_.level, ecu_abs_max=abs_.level_max,
            ecu_tc_level=tc.level, ecu_tc_max=tc.level_max,
            ecu_tc_cut=tc.cut, ecu_tc_cut_max=tc.cut_max,
            ecu_tc_slip=tc.slip, ecu_tc_slip_max=tc.slip_max,
            ecu_motor_map=pt.motor_map, ecu_motor_map_max=pt.motor_map_max,
            ecu_brake_migration=ch.brake_migration, ecu_brake_migration_max=ch.brake_migration_max,
            ecu_front_arb=ch.front_arb, ecu_front_arb_max=ch.front_arb_max,
            ecu_rear_arb=ch.rear_arb, ecu_rear_arb_max=ch.rear_arb_max,
            ecu_wiper_state=cp.wiper_state, ecu_lift_and_coast=pt.lift_and_coast,
        )
