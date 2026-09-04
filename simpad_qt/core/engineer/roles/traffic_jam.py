"""
SimPad Race Engineer — Traffic Jam / Slow Vehicles Ahead Role.
Monitors track ahead of player to detect sudden slowdowns,
spinning cars, or traffic jams.
"""

import time
import logging
from typing import Optional, Dict, List, Union
from ..base import BaseRole, EngineerMessage, RoleStatus, AudioEngineType
from ..context import EngineerContext
from ..registry import RoleRegistry
from ..params import RoleParam, FloatRangeParam, BoolParam, ParamScalarValue
from ...telemetry.reference_profile import ReferenceLapProfile
from ...telemetry.state_store import TelemetryStateStore
from simpad_qt.core.telemetry_channels import TelemetryChannel, ChannelRequirement

logger = logging.getLogger(__name__)


@RoleRegistry.register(
    role_id="traffic_jam",
    name="Traffic Jam (Slow Cars Ahead)",
    description="Alerts when vehicles are slow or crashed ahead of player on racing line.",
    default_priority=75,
)
class TrafficJamRole(BaseRole):
    """
    Role monitoring slow or stopped cars ahead of the player.
    """

    def __init__(
        self,
        role_id: str = "traffic_jam",
        name: str = "Traffic Jam (Slow Cars Ahead)",
        description: str = "",
        priority: int = 75,
        enabled: bool = True,
        audio_engine: Optional[AudioEngineType] = None,
        slow_speed_threshold_kmh: float = 50.0,
        warning_distance_m: float = 180.0,
        cooldown_sec: float = 8.0,
        enable_ref_lap_filter: bool = True,
        domain_speed_tolerance_kmh: float = 30.0,
    ):
        super().__init__(
            role_id=role_id,
            name=name,
            description=description,
            priority=priority,
            enabled=enabled,
            audio_engine=audio_engine,
        )
        self.slow_speed_threshold_mps = float(slow_speed_threshold_kmh) / 3.6
        self.warning_distance_m = float(warning_distance_m)
        self.cooldown_sec = float(cooldown_sec)
        self.enable_ref_lap_filter = bool(enable_ref_lap_filter)
        self.domain_speed_tolerance_kmh = float(domain_speed_tolerance_kmh)
        self._custom_profile: Optional[ReferenceLapProfile] = None

        self._last_alert_time: float = 0.0
        self._is_active_alert: bool = False
        self._target_slow_car_info: str = ""

    def set_reference_profile(self, profile: Optional[ReferenceLapProfile]) -> None:
        """Manually injects a reference lap profile."""
        self._custom_profile = profile
        self.reset()

    def get_reference_profile(self, context: Optional[EngineerContext] = None) -> Optional[ReferenceLapProfile]:
        """Retrieves active reference profile (injected or via context/DeltaEngine)."""
        if self._custom_profile is not None:
            return self._custom_profile
        if context:
            return context.get_reference_profile()
        try:
            from ...telemetry.lmu_parser import LMUParser
            delta_eng = LMUParser._delta_engine
            if delta_eng:
                return delta_eng.all_time_best_profile or delta_eng.current_profile
        except Exception:
            pass
        return None

    @property
    def slow_speed_threshold_kmh(self) -> float:
        return round(self.slow_speed_threshold_mps * 3.6, 1)

    @slow_speed_threshold_kmh.setter
    def slow_speed_threshold_kmh(self, value: float) -> None:
        self.slow_speed_threshold_mps = float(value) / 3.6

    def get_parameters(self) -> List[RoleParam]:
        return [
            BoolParam(
                name="enable_ref_lap_filter",
                label="Reference Lap Filter",
                default=True,
                description="Requires at least one vehicle (player or opponent) to be outside normal speed domain",
            ),
            FloatRangeParam(
                name="domain_speed_tolerance_kmh",
                label="Domain Speed Tolerance",
                min_val=5.0,
                max_val=80.0,
                step=5.0,
                unit="km/h",
                default=30.0,
                description="Maximum speed delta with reference lap to be considered in normal domain",
            ),
            FloatRangeParam(
                name="slow_speed_threshold_kmh",
                label="Slow Speed Threshold",
                min_val=10.0,
                max_val=120.0,
                step=5.0,
                unit="km/h",
                default=50.0,
                description="Speed below which a car ahead is considered slow/crashed",
            ),
            FloatRangeParam(
                name="warning_distance_m",
                label="Warning Distance",
                min_val=50.0,
                max_val=400.0,
                step=10.0,
                unit="m",
                default=180.0,
                description="Maximum distance ahead of player to detect slowdowns",
            ),
            FloatRangeParam(
                name="cooldown_sec",
                label="Alert Cooldown",
                min_val=2.0,
                max_val=30.0,
                step=1.0,
                unit="s",
                default=8.0,
                description="Minimum delay between two voice alerts",
            ),
        ]

    def get_channel_requirements(self) -> List[ChannelRequirement]:
        return [
            ChannelRequirement(
                channel=TelemetryChannel.FULL_SCORING,
                preferred_hz=10,
                required=True,
                reason="Positions and speeds of opponents ahead on track trajectory",
            ),
            ChannelRequirement(
                channel=TelemetryChannel.COMPACT_SCORING,
                preferred_hz=10,
                required=False,
                reason="Track spline and forward relative distance calculation",
            ),
        ]

    def get_sound_requirements(self) -> Dict[str, str]:
        return {
            "car": "Car",
        }

    def is_busy(self) -> bool:
        """Returns True if a slow traffic alert is active."""
        return self._is_active_alert

    def on_grid_update(self, state: TelemetryStateStore, context: EngineerContext) -> Optional[EngineerMessage]:
        """Grid update evaluation (FullScoringSession). Slow or stopped vehicles ahead on racing spline."""
        return self._evaluate_traffic_jam(state, context)

    def on_physics_tick(self, state: TelemetryStateStore, context: EngineerContext) -> Optional[EngineerMessage]:
        """Physics tick evaluation (100-120Hz TelemInfo). Player instantaneous speed and track spline distance."""
        return self._evaluate_traffic_jam(state, context)

    def update(self, context: EngineerContext) -> Optional[EngineerMessage]:
        """Polymorphic entry point for direct/manual evaluations."""
        return self._evaluate_traffic_jam(context.state_store, context)

    def _evaluate_traffic_jam(self, state: TelemetryStateStore, context: EngineerContext) -> Optional[EngineerMessage]:
        if not self.enabled or not context.scoring or context.is_private_qualifying():
            self._is_active_alert = False
            self._target_slow_car_info = ""
            return None

        player_veh = context.get_player_vehicle()
        if not player_veh:
            self._is_active_alert = False
            return None

        # If player is in pitlane or garage, disable on-track traffic jam alerts
        if context.is_player_in_pits() or context.is_player_in_garage():
            self._is_active_alert = False
            self._target_slow_car_info = ""
            return None

        now = time.time()
        track_length = context.get_track_length()
        opponents = context.get_track_opponents()
        ref_prof = self.get_reference_profile(context)
        has_valid_ref = bool(ref_prof and ref_prof.num_points >= 2)

        slow_cars_ahead = []
        for opp in opponents:
            dist_behind = context.compute_distance_behind(player_veh, opp, track_length)
            # dist_behind < 0 means car is AHEAD of player
            if -self.warning_distance_m <= dist_behind < -5.0:
                opp_speed = context.extract_vehicle_speed_mps(opp)
                if opp_speed < self.slow_speed_threshold_mps:
                    # Reference lap filter: requires player or opponent to be outside speed domain
                    if self.enable_ref_lap_filter and has_valid_ref:
                        if not context.has_traffic_domain_anomaly(
                            player_veh,
                            opp,
                            profile=ref_prof,
                            tolerance_kmh=self.domain_speed_tolerance_kmh,
                        ):
                            continue

                    dist_ahead = abs(dist_behind)
                    slow_cars_ahead.append((dist_ahead, opp_speed, opp))

        if slow_cars_ahead:
            self._is_active_alert = True
            slow_cars_ahead.sort(key=lambda x: x[0])
            closest_dist, closest_speed, closest_opp = slow_cars_ahead[0]
            driver_name = closest_opp.driver_name or "Car"
            self._target_slow_car_info = f"{driver_name} ({closest_speed * 3.6:.0f} km/h, {closest_dist:.0f}m ahead)"

            if (now - self._last_alert_time) > self.cooldown_sec:
                self._last_alert_time = now
                msg = EngineerMessage(
                    phrase_key="car",
                    priority=self.priority,
                    interrupt=False,
                    role_id=self.role_id,
                )
                self.emit_sound("car", interrupt=False)
                return msg
        else:
            self._is_active_alert = False
            self._target_slow_car_info = ""

        return None

    def reset(self) -> None:
        self._last_alert_time = 0.0
        self._is_active_alert = False
        self._target_slow_car_info = ""

    def get_config(self) -> Dict[str, ParamScalarValue]:
        cfg = super().get_config()
        cfg.update({
            "slow_speed_threshold_kmh": self.slow_speed_threshold_mps * 3.6,
            "warning_distance_m": self.warning_distance_m,
            "cooldown_sec": self.cooldown_sec,
            "enable_ref_lap_filter": self.enable_ref_lap_filter,
            "domain_speed_tolerance_kmh": self.domain_speed_tolerance_kmh,
        })
        return cfg

    def set_config(self, config: Dict[str, ParamScalarValue]) -> None:
        super().set_config(config)
        if "slow_speed_threshold_kmh" in config:
            self.slow_speed_threshold_mps = float(config["slow_speed_threshold_kmh"]) / 3.6
        if "warning_distance_m" in config:
            self.warning_distance_m = float(config["warning_distance_m"])
        if "cooldown_sec" in config:
            self.cooldown_sec = float(config["cooldown_sec"])
        if "enable_ref_lap_filter" in config:
            self.enable_ref_lap_filter = bool(config["enable_ref_lap_filter"])
        if "domain_speed_tolerance_kmh" in config:
            self.domain_speed_tolerance_kmh = float(config["domain_speed_tolerance_kmh"])

    def get_state_summary(self) -> Dict[str, Union[str, int, float, bool, List[str], None]]:
        summary = super().get_state_summary()
        summary.update({
            "is_alert_active": self._is_active_alert,
            "slow_car_info": self._target_slow_car_info or "Clear ahead",
            "enable_ref_lap_filter": self.enable_ref_lap_filter,
            "domain_speed_tolerance_kmh": self.domain_speed_tolerance_kmh,
            "is_busy": self.is_busy(),
        })
        return summary
