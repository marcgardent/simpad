"""
SimPad Race Engineer — Pitlane Spotter & Unsafe Release Protection Role (High Precision FSM).
Monitors the pitlane for:
1. Preventing Unsafe Release (alerts when a car approaches in Fast Lane behind the pit box).
2. Confirming clear lane (Safe Release / Clear) to rejoin safely.
3. Alerting on pitlane traffic jams or stopped vehicles ahead in pitlane.
4. Signaling vehicles alongside exiting adjacent boxes.
"""

import time
import math
import logging
from enum import Enum
from typing import Optional, Dict, Any, List, Tuple
from src.engineer.base import BaseRole, EngineerMessage, RoleStatus
from src.engineer.context import EngineerContext, get_vehicle_attr
from src.engineer.registry import RoleRegistry
from src.engineer.params import RoleParam, FloatRangeParam, BoolParam

logger = logging.getLogger(__name__)


class PitlaneSpotterState(str, Enum):
    """States of the Pitlane Spotter finite state machine (FSM)."""
    IDLE = "IDLE"                            # Track clear / On track or no pitlane threat
    BOX_MONITORING = "BOX_MONITORING"        # Player in box / pit stop / active monitoring
    UNSAFE_HAZARD = "UNSAFE_HAZARD"          # Hazard! Fast approaching vehicle in Fast Lane
    RELEASE_CLEAR = "RELEASE_CLEAR"          # Lane clear after hazard passed (Safe Release)
    PIT_TRAFFIC_AHEAD = "PIT_TRAFFIC_AHEAD"  # Blocked or very slow vehicle ahead in pitlane
    PIT_OVERLAP = "PIT_OVERLAP"              # Side-by-side vehicle / adjacent merge in pitlane


@RoleRegistry.register(
    role_id="pitlane_spotter",
    name="Pitlane Spotter & Unsafe Release",
    description="High-precision state machine protecting against unsafe release from pit box and monitoring pitlane traffic.",
    default_priority=95,
)
class PitlaneSpotterRole(BaseRole):
    """
    Role for advanced traffic monitoring in the pitlane and unsafe release protection.
    """

    def __init__(
        self,
        role_id: str = "pitlane_spotter",
        name: str = "Pitlane Spotter & Unsafe Release",
        description: str = "",
        priority: int = 95,
        enabled: bool = True,
        audio_engine: Optional[Any] = None,
        unsafe_release_distance_m: float = 28.0,
        unsafe_release_ttc_sec: float = 2.5,
        pit_slow_ahead_distance_m: float = 35.0,
        pit_slow_speed_threshold_kmh: float = 20.0,
        enable_unsafe_release: bool = True,
        enable_pit_traffic_ahead: bool = True,
        enable_pit_overlap: bool = True,
    ):
        super().__init__(
            role_id=role_id,
            name=name,
            description=description,
            priority=priority,
            enabled=enabled,
            audio_engine=audio_engine,
        )
        self.state = PitlaneSpotterState.IDLE
        self.unsafe_release_distance_m = float(unsafe_release_distance_m)
        self.unsafe_release_ttc_sec = float(unsafe_release_ttc_sec)
        self.pit_slow_ahead_distance_m = float(pit_slow_ahead_distance_m)
        self.pit_slow_speed_threshold_mps = float(pit_slow_speed_threshold_kmh) / 3.6
        self.enable_unsafe_release = bool(enable_unsafe_release)
        self.enable_pit_traffic_ahead = bool(enable_pit_traffic_ahead)
        self.enable_pit_overlap = bool(enable_pit_overlap)

        # Dynamic tracking variables
        self.target_threat_id: Optional[int] = None
        self.target_threat_name: str = ""
        self._last_state_change_time: float = 0.0
        self._last_alert_time: float = 0.0
        self._was_in_box: bool = False
        self._hazard_cleared: bool = False

        # Live diagnostics
        self._live_hazard_dist: float = 0.0
        self._live_hazard_speed_kmh: float = 0.0
        self._live_hazard_ttc: float = float("inf")
        self._live_pit_info: str = "Track clear"

    @property
    def pit_slow_speed_threshold_kmh(self) -> float:
        return round(self.pit_slow_speed_threshold_mps * 3.6, 1)

    @pit_slow_speed_threshold_kmh.setter
    def pit_slow_speed_threshold_kmh(self, value: float) -> None:
        self.pit_slow_speed_threshold_mps = float(value) / 3.6

    def get_parameters(self) -> List[RoleParam]:
        return [
            BoolParam(
                name="enable_unsafe_release",
                label="Unsafe Release Protection",
                default=True,
                description="Alert if a car approaches in fast lane during pit stop or pit exit",
            ),
            FloatRangeParam(
                name="unsafe_release_distance_m",
                label="Fast Lane Alert Distance",
                min_val=10.0,
                max_val=60.0,
                step=2.0,
                unit="m",
                default=28.0,
                description="Maximum rear distance in fast lane to trigger hazard alert",
            ),
            FloatRangeParam(
                name="unsafe_release_ttc_sec",
                label="Fast Lane TTC Threshold",
                min_val=1.0,
                max_val=5.0,
                step=0.2,
                unit="s",
                default=2.5,
                description="Time to collision (TTC) triggering pit exit hazard",
            ),
            BoolParam(
                name="enable_pit_traffic_ahead",
                label="Pitlane Slow Traffic Alert",
                default=True,
                description="Alert for stopped or idling vehicles ahead in pitlane",
            ),
            FloatRangeParam(
                name="pit_slow_ahead_distance_m",
                label="Forward Detection Distance",
                min_val=15.0,
                max_val=80.0,
                step=5.0,
                unit="m",
                default=35.0,
                description="Maximum forward distance to detect a slow vehicle in pitlane",
            ),
            BoolParam(
                name="enable_pit_overlap",
                label="Pitlane Alongside Alert",
                default=True,
                description="Warns when a car merges alongside in pitlane",
            ),
        ]

    def get_channel_requirements(self) -> List[Any]:
        try:
            from simpad_qt.core.telemetry_channels import TelemetryChannel, ChannelRequirement
            return [
                ChannelRequirement(
                    channel=TelemetryChannel.TELEMETRY,
                    preferred_hz=100,
                    required=True,
                    reason="Player speed and pit state (in_garage_stall / pit_state)",
                ),
                ChannelRequirement(
                    channel=TelemetryChannel.FULL_SCORING,
                    preferred_hz=10,
                    required=True,
                    reason="3D positions and speeds of opponents in pitlane and fast lane",
                ),
            ]
        except ImportError:
            return []

    def get_sound_requirements(self) -> Dict[str, str]:
        return {
            "car": "Car",
            "alongside": "Alongside",
            "clear": "Clear",
        }

    def is_busy(self) -> bool:
        """Returns True if unsafe release hazard or traffic alert is active."""
        return self.state in (
            PitlaneSpotterState.UNSAFE_HAZARD,
            PitlaneSpotterState.RELEASE_CLEAR,
            PitlaneSpotterState.PIT_TRAFFIC_AHEAD,
            PitlaneSpotterState.PIT_OVERLAP,
        )

    def update(self, context: EngineerContext) -> Optional[EngineerMessage]:
        if not self.enabled or not context.scoring or context.is_private_qualifying():
            if self.state != PitlaneSpotterState.IDLE:
                self.reset()
            return None

        # If player is NOT in pitlane, role stays idle
        if not context.is_player_in_pits() and not context.is_player_in_garage():
            if self.state != PitlaneSpotterState.IDLE:
                self.reset()
            return None

        player_veh = context.get_player_vehicle()
        if not player_veh:
            if self.state != PitlaneSpotterState.IDLE:
                self.reset()
            return None

        player_speed = context.get_player_speed_mps()
        track_length = context.get_track_length()
        pit_opponents = context.get_pit_opponents()

        # Evaluate if player is in box (stopped / servicing / launching)
        pit_state = int(get_vehicle_attr(player_veh, "pit_state", 0))
        in_garage = bool(get_vehicle_attr(player_veh, "in_garage_stall", False))
        is_stationary_or_in_box = (
            in_garage
            or pit_state in (3, 4)  # 3=stopped, 4=exiting
            or player_speed < 2.5   # Stopped or very slow in box
        )

        now = time.time()

        # =========================================================================
        # 1. PLAYER IN BOX / PIT STOP CASE (UNSAFE RELEASE PROTECTION)
        # =========================================================================
        if is_stationary_or_in_box and self.enable_unsafe_release:
            self._was_in_box = True
            return self._handle_unsafe_release_monitoring(context, player_veh, pit_opponents, track_length, now)

        # If player drives in pitlane after a stop where hazard was flagged
        if self._was_in_box and self.state == PitlaneSpotterState.UNSAFE_HAZARD:
            # If hazard cleared while player launches
            return self._check_release_clear(now)

        # =========================================================================
        # 2. PLAYER DRIVING IN PITLANE CASE (UNDER PIT LIMITER)
        # =========================================================================
        self._was_in_box = False
        return self._handle_pitlane_driving_traffic(context, player_veh, player_speed, pit_opponents, track_length, now)

    def _handle_unsafe_release_monitoring(
        self,
        context: EngineerContext,
        player_veh: Any,
        pit_opponents: List[Any],
        track_length: float,
        now: float,
    ) -> Optional[EngineerMessage]:
        """Monitors cars traveling down Fast Lane from behind to prevent Unsafe Release."""
        threats = []

        for opp in pit_opponents:
            opp_speed = context.extract_vehicle_speed_mps(opp)
            dist_behind = context.compute_distance_behind(player_veh, opp, track_length)
            euc_dist = context.compute_euclidean_distance(player_veh, opp)
            dist_effective = min(dist_behind, euc_dist) if dist_behind > 0 else euc_dist

            # A car is a threat if it approaches from behind in fast lane
            # with significant speed (> 20 km/h) and in range
            if 0.0 < dist_behind <= self.unsafe_release_distance_m or (0.0 < euc_dist <= self.unsafe_release_distance_m and dist_behind >= -2.0):
                speed_delta = max(0.1, opp_speed)
                ttc = dist_effective / speed_delta if speed_delta > 0.5 else float("inf")

                if opp_speed >= self.pit_slow_speed_threshold_mps and (dist_effective <= self.unsafe_release_distance_m or ttc <= self.unsafe_release_ttc_sec):
                    threats.append({
                        "id": get_vehicle_attr(opp, "id", -1),
                        "name": get_vehicle_attr(opp, "driver_name", "Opponent"),
                        "speed_mps": opp_speed,
                        "dist": dist_effective,
                        "ttc": ttc,
                        "opp": opp,
                    })

        if threats:
            threats.sort(key=lambda t: t["ttc"])
            target = threats[0]

            self.target_threat_id = target["id"]
            self.target_threat_name = target["name"]
            self._live_hazard_dist = target["dist"]
            self._live_hazard_speed_kmh = target["speed_mps"] * 3.6
            self._live_hazard_ttc = target["ttc"]
            self._live_pit_info = f"UNSAFE HAZARD: {target['name']} ({self._live_hazard_speed_kmh:.0f} km/h, {self._live_hazard_dist:.0f}m behind)"

            if self.state != PitlaneSpotterState.UNSAFE_HAZARD:
                self.state = PitlaneSpotterState.UNSAFE_HAZARD
                self._last_state_change_time = now
                self._last_alert_time = now
                self._hazard_cleared = False

                # Immediate interruptive hazard announcement
                msg = EngineerMessage(
                    phrase_key="car",
                    priority=self.priority,
                    interrupt=True,
                    role_id=self.role_id,
                )
                self.emit_sound("car", interrupt=True)
                return msg

            return None

        # If no threat detected
        self._live_hazard_dist = 0.0
        self._live_hazard_speed_kmh = 0.0
        self._live_hazard_ttc = float("inf")

        # If we were in hazard alert and lane just cleared -> Safe Release!
        if self.state == PitlaneSpotterState.UNSAFE_HAZARD:
            self.state = PitlaneSpotterState.RELEASE_CLEAR
            self._last_state_change_time = now
            self._live_pit_info = "Fast Lane CLEAR (Safe to release)"

            msg = EngineerMessage(
                phrase_key="clear",
                priority=self.priority,
                interrupt=True,
                role_id=self.role_id,
            )
            self.emit_sound("clear", interrupt=True)
            return msg

        elif self.state == PitlaneSpotterState.RELEASE_CLEAR:
            if (now - self._last_state_change_time) > 2.0:
                self.state = PitlaneSpotterState.BOX_MONITORING
            return None

        self.state = PitlaneSpotterState.BOX_MONITORING
        self._live_pit_info = "Box monitoring — Fast lane clear"
        return None

    def _check_release_clear(self, now: float) -> Optional[EngineerMessage]:
        """Confirms that lane is clear when relaunching."""
        self.state = PitlaneSpotterState.RELEASE_CLEAR
        self._last_state_change_time = now
        self._live_pit_info = "Pitlane Clear"
        msg = EngineerMessage(
            phrase_key="clear",
            priority=self.priority,
            interrupt=False,
            role_id=self.role_id,
        )
        self.emit_sound("clear", interrupt=False)
        return msg

    def _handle_pitlane_driving_traffic(
        self,
        context: EngineerContext,
        player_veh: Dict[str, Any],
        player_speed: float,
        pit_opponents: List[Dict[str, Any]],
        track_length: float,
        now: float,
    ) -> Optional[EngineerMessage]:
        """Handles traffic during pitlane driving under pit speed limiter."""
        # 1. Detection of slow / stopped vehicle AHEAD in pitlane
        if self.enable_pit_traffic_ahead:
            slow_ahead = []
            for opp in pit_opponents:
                dist_behind = context.compute_distance_behind(player_veh, opp, track_length)
                euc_dist = context.compute_euclidean_distance(player_veh, opp)
                # dist_behind < 0 means ahead
                if (-self.pit_slow_ahead_distance_m <= dist_behind < -2.0) or (0.0 < euc_dist <= self.pit_slow_ahead_distance_m and dist_behind < 0):
                    opp_speed = context.extract_vehicle_speed_mps(opp)
                    if opp_speed < self.pit_slow_speed_threshold_mps:
                        dist_ahead = abs(dist_behind) if dist_behind < 0 else euc_dist
                        slow_ahead.append((dist_ahead, opp_speed, opp))

            if slow_ahead:
                slow_ahead.sort(key=lambda x: x[0])
                closest_dist, closest_speed, closest_opp = slow_ahead[0]
                driver_name = get_vehicle_attr(closest_opp, "driver_name", "Car")
                self._live_pit_info = f"Slow car ahead in pits: {driver_name} ({closest_dist:.0f}m)"

                if self.state != PitlaneSpotterState.PIT_TRAFFIC_AHEAD:
                    self.state = PitlaneSpotterState.PIT_TRAFFIC_AHEAD
                    self._last_state_change_time = now

                    if (now - self._last_alert_time) > 6.0:
                        self._last_alert_time = now
                        msg = EngineerMessage(
                            phrase_key="car",
                            priority=self.priority,
                            interrupt=False,
                            role_id=self.role_id,
                        )
                        self.emit_sound("car", interrupt=False)
                        return msg
                return None

        # 2. Detection of alongside vehicle (Overlap) in pitlane
        if self.enable_pit_overlap:
            alongside_cars = []
            for opp in pit_opponents:
                dist_behind = context.compute_distance_behind(player_veh, opp, track_length)
                euc_dist = context.compute_euclidean_distance(player_veh, opp)
                if abs(dist_behind) <= 5.0 or euc_dist <= 5.5:
                    alongside_cars.append(opp)

            if alongside_cars:
                alongside_name = get_vehicle_attr(alongside_cars[0], "driver_name", "Car")
                self._live_pit_info = f"Car alongside in pitlane: {alongside_name}"
                if self.state != PitlaneSpotterState.PIT_OVERLAP:
                    self.state = PitlaneSpotterState.PIT_OVERLAP
                    self._last_state_change_time = now

                    if (now - self._last_alert_time) > 4.0:
                        self._last_alert_time = now
                        msg = EngineerMessage(
                            phrase_key="alongside",
                            priority=self.priority,
                            interrupt=True,
                            role_id=self.role_id,
                        )
                        self.emit_sound("alongside", interrupt=True)
                        return msg
                return None

        # If traffic is clear and unobstructed
        if self.state in (PitlaneSpotterState.PIT_TRAFFIC_AHEAD, PitlaneSpotterState.PIT_OVERLAP):
            self.state = PitlaneSpotterState.IDLE
            self._live_pit_info = "Pitlane clear"
            return None

        self.state = PitlaneSpotterState.IDLE
        self._live_pit_info = "Pitlane clear"
        return None

    def reset(self) -> None:
        self.state = PitlaneSpotterState.IDLE
        self.target_threat_id = None
        self.target_threat_name = ""
        self._last_state_change_time = 0.0
        self._last_alert_time = 0.0
        self._was_in_box = False
        self._hazard_cleared = False
        self._live_hazard_dist = 0.0
        self._live_hazard_speed_kmh = 0.0
        self._live_hazard_ttc = float("inf")
        self._live_pit_info = "Track clear"

    def get_config(self) -> Dict[str, Any]:
        cfg = super().get_config()
        cfg.update({
            "unsafe_release_distance_m": self.unsafe_release_distance_m,
            "unsafe_release_ttc_sec": self.unsafe_release_ttc_sec,
            "pit_slow_ahead_distance_m": self.pit_slow_ahead_distance_m,
            "pit_slow_speed_threshold_kmh": self.pit_slow_speed_threshold_mps * 3.6,
            "enable_unsafe_release": self.enable_unsafe_release,
            "enable_pit_traffic_ahead": self.enable_pit_traffic_ahead,
            "enable_pit_overlap": self.enable_pit_overlap,
        })
        return cfg

    def set_config(self, config: Dict[str, Any]) -> None:
        super().set_config(config)
        if "unsafe_release_distance_m" in config:
            self.unsafe_release_distance_m = float(config["unsafe_release_distance_m"])
        if "unsafe_release_ttc_sec" in config:
            self.unsafe_release_ttc_sec = float(config["unsafe_release_ttc_sec"])
        if "pit_slow_ahead_distance_m" in config:
            self.pit_slow_ahead_distance_m = float(config["pit_slow_ahead_distance_m"])
        if "pit_slow_speed_threshold_kmh" in config:
            self.pit_slow_speed_threshold_mps = float(config["pit_slow_speed_threshold_kmh"]) / 3.6
        if "enable_unsafe_release" in config:
            self.enable_unsafe_release = bool(config["enable_unsafe_release"])
        if "enable_pit_traffic_ahead" in config:
            self.enable_pit_traffic_ahead = bool(config["enable_pit_traffic_ahead"])
        if "enable_pit_overlap" in config:
            self.enable_pit_overlap = bool(config["enable_pit_overlap"])

    def get_state_summary(self) -> Dict[str, Any]:
        summary = super().get_state_summary()
        summary.update({
            "fsm_state": self.state.value,
            "target_threat": self.target_threat_name or "None",
            "live_hazard_dist": round(self._live_hazard_dist, 1),
            "live_hazard_speed_kmh": round(self._live_hazard_speed_kmh, 1),
            "live_hazard_ttc": round(self._live_hazard_ttc, 1) if self._live_hazard_ttc < 99 else "--",
            "pit_info": self._live_pit_info,
            "is_busy": self.is_busy(),
        })
        return summary
