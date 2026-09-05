"""
SimPad Race Engineer — Fight Spotter Role (CrewChief V4 Cartesian FSM).
OOP Architecture and SOLID principles:
- SRP: Split into specialized modules (2D Geometry, Noise/Velocity filtering, Overlap detection, Temporal FSM, Phrasing strategies).
- OCP: Interchangeable phrasing strategies (Road vs Oval) and extensible declarative parameters.
- LSP: Compliant and substitutable implementation of BaseRole.
- ISP: Clear and targeted protocols for geometry, speed, and FSM.
- DIP: Strict decoupling between spatial logic and audio/telemetry runtime.
"""

import time
import math
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple, Protocol, Union

from isimotor_rawudp_client import TelemVect3
from simpad_qt.builtin_plugins.race_engineer.base import BaseRole, EngineerMessage, RoleStatus, AudioEngineType
from simpad_qt.builtin_plugins.race_engineer.context import EngineerContext
from simpad_qt.builtin_plugins.race_engineer.registry import RoleRegistry
from simpad_qt.builtin_plugins.race_engineer.params import RoleParam, FloatRangeParam, BoolParam, ParamScalarValue
from simpad_qt.core.telemetry.state_store import TelemetryStateStore
from simpad_qt.core.telemetry_channels import TelemetryChannel, ChannelRequirement

logger = logging.getLogger(__name__)


# =============================================================================
# 1. ENUMS AND TYPED DATA STRUCTURES
# =============================================================================

class SpotterSide(str, Enum):
    """Relative side of an opponent relative to player vehicle."""
    NONE = "none"
    LEFT = "left"
    RIGHT = "right"


class SpotterMessageType(str, Enum):
    """Types of vocal messages emitted by Spotter."""
    NONE = "none"
    CAR_LEFT = "car_left"
    CAR_RIGHT = "car_right"
    CLEAR_LEFT = "clear_left"
    CLEAR_RIGHT = "clear_right"
    CLEAR_ALL_ROUND = "clear_all_round"
    THREE_WIDE_MIDDLE = "three_wide_middle"
    THREE_WIDE_LEFT = "three_wide_left"
    THREE_WIDE_RIGHT = "three_wide_right"
    STILL_THERE = "still_there"


class FightSpotterState(str, Enum):
    """Global spatial state of battle situation around player vehicle."""
    IDLE = "IDLE"
    CLEAR = "CLEAR"
    OVERLAP_LEFT = "OVERLAP_LEFT"
    OVERLAP_RIGHT = "OVERLAP_RIGHT"
    THREE_WIDE_MIDDLE = "THREE_WIDE_MIDDLE"
    THREE_WIDE_LEFT = "THREE_WIDE_LEFT"
    THREE_WIDE_RIGHT = "THREE_WIDE_RIGHT"


@dataclass
class OpponentTrackingData:
    """Temporal and kinematic tracking memory for an opponent."""
    opponent_id: int
    pos_x: float
    pos_z: float
    vel_x: float = 0.0
    vel_z: float = 0.0
    last_update_time: float = 0.0


@dataclass
class AlignedOpponent:
    """Relative position and classification of an opponent in player reference frame."""
    opponent_id: int
    side: SpotterSide
    lateral_separation_m: float
    longitudinal_dist_m: float
    is_speed_valid: bool


# =============================================================================
# 2. PHRASING STRATEGIES (STRATEGY PATTERN - OCP)
# =============================================================================

class ISpotterPhrasingStrategy(Protocol):
    """Protocol for resolving Spotter audio phrase keys."""
    def resolve_phrase(self, message_type: SpotterMessageType) -> str:
        """Returns audio phrase key corresponding to message type."""
        ...


class RoadSpotterPhrasingStrategy:
    """Phrasing strategy for road courses (Car Left, Car Right, Clear, 3-Wide)."""
    _PHRASE_MAP = {
        SpotterMessageType.CAR_LEFT: "car_left",
        SpotterMessageType.CAR_RIGHT: "car_right",
        SpotterMessageType.CLEAR_LEFT: "clear_left",
        SpotterMessageType.CLEAR_RIGHT: "clear_right",
        SpotterMessageType.CLEAR_ALL_ROUND: "clear_all_round",
        SpotterMessageType.THREE_WIDE_MIDDLE: "three_wide",
        SpotterMessageType.THREE_WIDE_LEFT: "three_wide_left",
        SpotterMessageType.THREE_WIDE_RIGHT: "three_wide_right",
        SpotterMessageType.STILL_THERE: "still_there",
    }

    def resolve_phrase(self, message_type: SpotterMessageType) -> str:
        return self._PHRASE_MAP.get(message_type, "")


class OvalSpotterPhrasingStrategy:
    """Phrasing strategy for oval tracks (Inside, Outside, Clear Inside/Outside)."""
    _PHRASE_MAP = {
        SpotterMessageType.CAR_LEFT: "car_inside",
        SpotterMessageType.CAR_RIGHT: "car_outside",
        SpotterMessageType.CLEAR_LEFT: "clear_inside",
        SpotterMessageType.CLEAR_RIGHT: "clear_outside",
        SpotterMessageType.CLEAR_ALL_ROUND: "clear_all_round",
        SpotterMessageType.THREE_WIDE_MIDDLE: "three_wide",
        SpotterMessageType.THREE_WIDE_LEFT: "three_wide_inside",
        SpotterMessageType.THREE_WIDE_RIGHT: "three_wide_outside",
        SpotterMessageType.STILL_THERE: "still_there",
    }

    def resolve_phrase(self, message_type: SpotterMessageType) -> str:
        return self._PHRASE_MAP.get(message_type, "")


# =============================================================================
# 3. 2D CARTESIAN GEOMETRY ENGINE (SRP)
# =============================================================================

class CartesianGeometry2D:
    """
    Handles 2D geometric coordinate transformations from world to local vehicle frame.
    Player frame: Origin (0, 0), +Z rearward / -Z forward, +X to left / -X to right.
    """

    @staticmethod
    def get_aligned_xz_coordinates(
        player_rotation_rad: float,
        player_x: float,
        player_z: float,
        opponent_x: float,
        opponent_z: float,
    ) -> Tuple[float, float]:
        """
        Performs coordinate system rotation using 2D trigonometric rotation.
        """
        raw_x = opponent_x - player_x
        raw_z = opponent_z - player_z

        cos_rot = math.cos(player_rotation_rad)
        sin_rot = math.sin(player_rotation_rad)

        # aligned_x: > 0 on left, < 0 on right
        aligned_x = float((cos_rot * raw_x) + (sin_rot * raw_z))
        # aligned_z: > 0 behind, < 0 ahead
        aligned_z = float((cos_rot * raw_z) - (sin_rot * raw_x))

        return aligned_x, aligned_z

    @staticmethod
    def compute_yaw_from_velocity(vel_x: float, vel_z: float) -> float:
        """Calculates yaw angle from world velocity vector."""
        if abs(vel_x) < 0.001 and abs(vel_z) < 0.001:
            return 0.0
        yaw = math.atan2(vel_x, vel_z)
        if yaw < 0.0:
            yaw += 2.0 * math.pi
        return yaw

    @staticmethod
    def compute_yaw_from_orientation(m_ori: Optional[Tuple[TelemVect3, TelemVect3, TelemVect3]]) -> Optional[float]:
        """Extracts yaw angle from rFactor2/LMU orientation matrix if available."""
        if not m_ori or len(m_ori) < 3:
            return None
        try:
            row_z = m_ori[2]
            yaw = math.atan2(float(row_z.x), float(row_z.z))
            return yaw if yaw >= 0 else yaw + 2.0 * math.pi
        except Exception:
            return None


# =============================================================================
# 4. VELOCITY FILTER AND KINEMATIC NOISE REJECTION (SRP)
# =============================================================================

class OpponentSpeedFilter:
    """
    Tracks opponent kinematics via finite differences and filters abnormal speeds
    (e.g. spinning cars, driving wrong way, or teleporting).
    """

    def __init__(
        self,
        calculate_speeds_interval_sec: float = 0.2,
        max_closing_speed_mps: float = 25.0,  # 90 km/h
    ):
        self.calculate_speeds_interval_sec = calculate_speeds_interval_sec
        self.max_closing_speed_mps = max_closing_speed_mps
        self._cache: Dict[int, OpponentTrackingData] = {}

    def update_and_validate(
        self,
        opponent_id: int,
        opp_x: float,
        opp_z: float,
        player_vel_x: float,
        player_vel_z: float,
        now: float,
        opp_vel_x: Optional[float] = None,
        opp_vel_z: Optional[float] = None,
    ) -> bool:
        """
        Updates opponent speed and validates if relative closing speed
        is within realistic racing battle range.
        """
        tracking = self._cache.get(opponent_id)
        if tracking is None:
            vx = opp_vel_x if opp_vel_x is not None else player_vel_x
            vz = opp_vel_z if opp_vel_z is not None else player_vel_z
            self._cache[opponent_id] = OpponentTrackingData(
                opponent_id=opponent_id,
                pos_x=opp_x,
                pos_z=opp_z,
                vel_x=vx,
                vel_z=vz,
                last_update_time=now,
            )
            return True

        if opp_vel_x is not None and opp_vel_z is not None:
            tracking.vel_x = opp_vel_x
            tracking.vel_z = opp_vel_z
            tracking.pos_x = opp_x
            tracking.pos_z = opp_z
            tracking.last_update_time = now
        else:
            time_diff = now - tracking.last_update_time
            if time_diff >= self.calculate_speeds_interval_sec and time_diff > 0.0:
                tracking.vel_x = (opp_x - tracking.pos_x) / time_diff
                tracking.vel_z = (opp_z - tracking.pos_z) / time_diff
                tracking.pos_x = opp_x
                tracking.pos_z = opp_z
                tracking.last_update_time = now

        # Check speed differential (closing speed)
        delta_vx = abs(player_vel_x - tracking.vel_x)
        delta_vz = abs(player_vel_z - tracking.vel_z)

        return delta_vx <= self.max_closing_speed_mps and delta_vz <= self.max_closing_speed_mps

    def purge_inactive(self, active_ids: set) -> None:
        """Removes vehicles no longer in consideration zone from cache."""
        stale_keys = [k for k in self._cache.keys() if k not in active_ids]
        for k in stale_keys:
            del self._cache[k]

    def clear(self) -> None:
        """Clears entire kinematic cache."""
        self._cache.clear()


# =============================================================================
# 5. OVERLAP EVALUATOR AND 3-WIDE DISPERSION (SRP)
# =============================================================================

class CartesianOverlapEvaluator:
    """
    Evaluates overlap presence with clear gap hysteresis
    and analyzes lateral dispersion to distinguish line-astern from 3-Wide.
    """

    def __init__(
        self,
        car_length_m: float = 4.2,
        car_width_m: float = 1.9,
        gap_needed_for_clear_m: float = 1.5,
        car_behind_extra_length_m: float = 0.4,
        track_zone_to_consider_m: float = 20.0,
    ):
        self.car_length_m = car_length_m
        self.car_width_m = car_width_m
        self.gap_needed_for_clear_m = gap_needed_for_clear_m
        self.long_car_length_m = car_length_m + gap_needed_for_clear_m
        self.car_behind_extra_length_m = car_behind_extra_length_m
        self.track_zone_to_consider_m = track_zone_to_consider_m

    def set_dimensions(self, length_m: float, width_m: float, clear_gap_m: Optional[float] = None) -> None:
        """Updates vehicle dimensions dynamically."""
        self.car_length_m = float(length_m)
        self.car_width_m = float(width_m)
        if clear_gap_m is not None:
            self.gap_needed_for_clear_m = float(clear_gap_m)
        self.long_car_length_m = self.car_length_m + self.gap_needed_for_clear_m

    def is_in_consideration_zone(self, aligned_x: float, aligned_z: float) -> bool:
        """Checks if opponent vehicle is within immediate analysis perimeter (20m)."""
        return (abs(aligned_x) <= self.track_zone_to_consider_m and
                abs(aligned_z) <= self.track_zone_to_consider_m)

    def evaluate_opponent_overlap(
        self,
        aligned_x: float,
        aligned_z: float,
        had_overlap_on_side: bool,
        is_speed_valid: bool,
    ) -> Tuple[SpotterSide, float]:
        """
        Determines if opponent is in overlap situation (left or right)
        applying hysteresis rule (longCarLength vs carLength).
        """
        if not self.is_in_consideration_zone(aligned_x, aligned_z):
            return SpotterSide.NONE, -1.0

        # Opponent on RIGHT (X < 0)
        if aligned_x < 0:
            lateral_sep = abs(aligned_x)
            if had_overlap_on_side:
                # If already overlapping, hold until long_car_length
                if abs(aligned_z) < self.long_car_length_m:
                    return SpotterSide.RIGHT, lateral_sep
            else:
                # New overlap: strict check of length + width + speed
                is_longitudinal_overlap = (
                    (aligned_z < 0 and abs(aligned_z) < self.car_length_m) or
                    (aligned_z >= 0 and aligned_z < (self.car_length_m + self.car_behind_extra_length_m))
                )
                if is_longitudinal_overlap and lateral_sep >= (self.car_width_m * 0.4) and is_speed_valid:
                    return SpotterSide.RIGHT, lateral_sep

        # Opponent on LEFT (X > 0)
        elif aligned_x > 0:
            lateral_sep = aligned_x
            if had_overlap_on_side:
                if abs(aligned_z) < self.long_car_length_m:
                    return SpotterSide.LEFT, lateral_sep
            else:
                is_longitudinal_overlap = (
                    (aligned_z < 0 and abs(aligned_z) < self.car_length_m) or
                    (aligned_z >= 0 and aligned_z < (self.car_length_m + self.car_behind_extra_length_m))
                )
                if is_longitudinal_overlap and lateral_sep >= (self.car_width_m * 0.4) and is_speed_valid:
                    return SpotterSide.LEFT, lateral_sep

        return SpotterSide.NONE, -1.0

    def analyze_multi_car_distribution(
        self,
        left_separations: List[float],
        right_separations: List[float],
    ) -> Tuple[int, int]:
        """
        Calculates effective number of side-by-side cars on left and right.
        Filters line-astern vehicles if lateral delta < car_width.
        """
        cars_left = len(left_separations)
        cars_right = len(right_separations)

        if cars_left > 1 and cars_right == 0:
            delta_left = max(left_separations) - min(left_separations)
            if delta_left < self.car_width_m:
                cars_left = 1  # Line astern

        if cars_right > 1 and cars_left == 0:
            delta_right = max(right_separations) - min(right_separations)
            if delta_right < self.car_width_m:
                cars_right = 1  # Line astern

        return cars_left, cars_right


# =============================================================================
# 6. TEMPORAL STATE MACHINE AND ANTI-CHATTER LOGIC (SRP)
# =============================================================================

class SpotterStateMachine:
    """
    Temporal finite state machine inspired by CrewChiefV4.
    Manages confirmation delays (Clear Delay), reminders ("Still there"),
    anti-chatter logic, and radio channel holding.
    """

    def __init__(
        self,
        clear_message_delay_sec: float = 0.35,
        oval_clear_message_delay_sec: float = 0.20,
        repeat_hold_freq_sec: float = 3.0,
        bouncing_wait_sec: float = 1.5,
        on_single_to_3wide_delay_sec: float = 0.5,
        enable_three_wide: bool = True,
        time_to_wait_before_closing_channel_sec: float = 5.0,
    ):
        self.clear_message_delay_sec = clear_message_delay_sec
        self.oval_clear_message_delay_sec = oval_clear_message_delay_sec
        self.repeat_hold_freq_sec = repeat_hold_freq_sec
        self.bouncing_wait_sec = bouncing_wait_sec
        self.on_single_to_3wide_delay_sec = on_single_to_3wide_delay_sec
        self.enable_three_wide = enable_three_wide
        self.time_to_wait_before_closing_channel_sec = time_to_wait_before_closing_channel_sec

        # Internal states
        self.cars_on_left_prev: int = 0
        self.cars_on_right_prev: int = 0
        self.reported_single_overlap_left: bool = False
        self.reported_single_overlap_right: bool = False
        self.reported_double_overlap_left: bool = False
        self.reported_double_overlap_right: bool = False
        self.was_in_middle: bool = False

        self.next_message_type: SpotterMessageType = SpotterMessageType.NONE
        self.next_message_due_time: float = 0.0

        # Open radio channel management
        self.channel_open: bool = False
        self.time_when_channel_should_close: float = float("inf")

    def reset(self) -> None:
        """Resets all state machine states."""
        self.cars_on_left_prev = 0
        self.cars_on_right_prev = 0
        self.reported_single_overlap_left = False
        self.reported_single_overlap_right = False
        self.reported_double_overlap_left = False
        self.reported_double_overlap_right = False
        self.was_in_middle = False
        self.next_message_type = SpotterMessageType.NONE
        self.next_message_due_time = 0.0
        self.channel_open = False
        self.time_when_channel_should_close = float("inf")

    def evaluate_next_message(
        self,
        cars_on_left: int,
        cars_on_right: int,
        now: float,
        use_oval_logic: bool = False,
    ) -> None:
        """
        Determines next message to schedule based on overlap changes.
        """
        clear_delay = self.oval_clear_message_delay_sec if use_oval_logic else self.clear_message_delay_sec

        # 1. Clear All Round (clear on both sides)
        if cars_on_left == 0 and cars_on_right == 0 and (self.cars_on_left_prev > 0 and self.cars_on_right_prev > 0):
            self.next_message_type = SpotterMessageType.CLEAR_ALL_ROUND
            self.next_message_due_time = now + clear_delay

        # 2. Clear Left
        elif cars_on_left == 0 and self.cars_on_left_prev > 0 and (
            (cars_on_right == 0 and self.cars_on_right_prev == 0) or
            (cars_on_right > 0 and self.cars_on_right_prev > 0)
        ):
            self.next_message_type = SpotterMessageType.CLEAR_LEFT
            self.next_message_due_time = now + clear_delay

        # 3. Clear Right
        elif cars_on_right == 0 and self.cars_on_right_prev > 0 and (
            (cars_on_left == 0 and self.cars_on_left_prev == 0) or
            (cars_on_left > 0 and self.cars_on_left_prev > 0)
        ):
            self.next_message_type = SpotterMessageType.CLEAR_RIGHT
            self.next_message_due_time = now + clear_delay

        # 4. Three Wide In the Middle (cars on both sides)
        elif cars_on_left > 0 and cars_on_right > 0 and (self.cars_on_left_prev == 0 or self.cars_on_right_prev == 0):
            has_pending_clear = (self.reported_single_overlap_left or self.reported_double_overlap_left) and \
                                (self.reported_single_overlap_right or self.reported_double_overlap_right)
            self.next_message_due_time = now + (self.bouncing_wait_sec if has_pending_clear else 0.0)
            self.next_message_type = SpotterMessageType.THREE_WIDE_MIDDLE

        # 5. New Overlap on Left
        elif cars_on_left > 0 and cars_on_right == 0 and self.cars_on_left_prev == 0 and self.cars_on_right_prev == 0:
            has_pending_clear = self.reported_single_overlap_left or self.reported_double_overlap_left
            self.next_message_due_time = now + (self.bouncing_wait_sec if has_pending_clear else 0.0)
            if self.enable_three_wide and cars_on_left > 1:
                self.next_message_type = SpotterMessageType.THREE_WIDE_RIGHT
            else:
                self.next_message_type = SpotterMessageType.CAR_LEFT

        # 6. New Overlap on Right
        elif cars_on_left == 0 and cars_on_right > 0 and self.cars_on_left_prev == 0 and self.cars_on_right_prev == 0:
            has_pending_clear = self.reported_single_overlap_right or self.reported_double_overlap_right
            self.next_message_due_time = now + (self.bouncing_wait_sec if has_pending_clear else 0.0)
            if self.enable_three_wide and cars_on_right > 1:
                self.next_message_type = SpotterMessageType.THREE_WIDE_LEFT
            else:
                self.next_message_type = SpotterMessageType.CAR_RIGHT

        # 7. Escalation to 3-Wide on single side
        elif self.enable_three_wide and cars_on_left > 1 and cars_on_right == 0 and self.cars_on_left_prev == 1:
            self.next_message_due_time = now + (self.on_single_to_3wide_delay_sec if self.reported_single_overlap_left else 0.0)
            self.next_message_type = SpotterMessageType.THREE_WIDE_RIGHT

        elif self.enable_three_wide and cars_on_left == 0 and cars_on_right > 1 and self.cars_on_right_prev == 1:
            self.next_message_due_time = now + (self.on_single_to_3wide_delay_sec if self.reported_single_overlap_right else 0.0)
            self.next_message_type = SpotterMessageType.THREE_WIDE_LEFT

        # 8. De-escalation 3-Wide -> single overlap
        elif self.enable_three_wide and cars_on_left == 1 and cars_on_right == 0 and self.cars_on_left_prev > 1:
            self.next_message_type = SpotterMessageType.CAR_LEFT
            self.next_message_due_time = now

        elif self.enable_three_wide and cars_on_left == 0 and cars_on_right == 1 and self.cars_on_right_prev > 1:
            self.next_message_type = SpotterMessageType.CAR_RIGHT
            self.next_message_due_time = now

    def is_message_valid(self, msg_type: SpotterMessageType, cars_on_left: int, cars_on_right: int) -> bool:
        """Verifies contextual validity of message before emission."""
        if msg_type == SpotterMessageType.CAR_LEFT and cars_on_left == 0:
            return False
        if msg_type == SpotterMessageType.CAR_RIGHT and cars_on_right == 0:
            return False
        if msg_type == SpotterMessageType.THREE_WIDE_MIDDLE and (cars_on_left == 0 or cars_on_right == 0):
            return False
        if msg_type == SpotterMessageType.THREE_WIDE_LEFT and cars_on_right < 2:
            return False
        if msg_type == SpotterMessageType.THREE_WIDE_RIGHT and cars_on_left < 2:
            return False
        if msg_type == SpotterMessageType.STILL_THERE and cars_on_left == 0 and cars_on_right == 0:
            return False
        return True

    def process_playback_tick(
        self,
        cars_on_left: int,
        cars_on_right: int,
        now: float,
    ) -> Optional[Tuple[SpotterMessageType, bool]]:
        """
        Consumes ready message if eligible and updates state indicators.
        Returns (message_type, keep_channel_open) or None.
        """
        if self.next_message_type == SpotterMessageType.NONE or now < self.next_message_due_time:
            return None

        if not self.is_message_valid(self.next_message_type, cars_on_left, cars_on_right):
            self.next_message_type = SpotterMessageType.NONE
            return None

        msg_to_play = self.next_message_type

        # State transition machine after emission
        if msg_to_play == SpotterMessageType.THREE_WIDE_MIDDLE:
            self.reported_single_overlap_left = True
            self.reported_single_overlap_right = True
            self.reported_double_overlap_left = False
            self.reported_double_overlap_right = False
            self.was_in_middle = True
            self.channel_open = True
            self.next_message_type = SpotterMessageType.STILL_THERE
            self.next_message_due_time = now + self.repeat_hold_freq_sec
            return msg_to_play, True

        elif msg_to_play == SpotterMessageType.THREE_WIDE_LEFT:
            self.reported_double_overlap_right = True
            self.reported_single_overlap_right = False
            self.channel_open = True
            self.next_message_type = SpotterMessageType.STILL_THERE
            self.next_message_due_time = now + self.repeat_hold_freq_sec
            return msg_to_play, True

        elif msg_to_play == SpotterMessageType.THREE_WIDE_RIGHT:
            self.reported_double_overlap_left = True
            self.reported_single_overlap_left = False
            self.channel_open = True
            self.next_message_type = SpotterMessageType.STILL_THERE
            self.next_message_due_time = now + self.repeat_hold_freq_sec
            return msg_to_play, True

        elif msg_to_play == SpotterMessageType.CAR_LEFT:
            self.reported_single_overlap_left = True
            self.reported_double_overlap_left = False
            self.channel_open = True
            self.next_message_type = SpotterMessageType.STILL_THERE
            self.next_message_due_time = now + self.repeat_hold_freq_sec
            return msg_to_play, True

        elif msg_to_play == SpotterMessageType.CAR_RIGHT:
            self.reported_single_overlap_right = True
            self.reported_double_overlap_right = False
            self.channel_open = True
            self.next_message_type = SpotterMessageType.STILL_THERE
            self.next_message_due_time = now + self.repeat_hold_freq_sec
            return msg_to_play, True

        elif msg_to_play == SpotterMessageType.CLEAR_ALL_ROUND:
            had_overlap = (self.reported_single_overlap_left or self.reported_single_overlap_right or
                           self.reported_double_overlap_left or self.reported_double_overlap_right)
            self.reported_single_overlap_left = False
            self.reported_single_overlap_right = False
            self.reported_double_overlap_left = False
            self.reported_double_overlap_right = False
            self.was_in_middle = False
            self.channel_open = False
            self.next_message_type = SpotterMessageType.NONE
            return (msg_to_play, False) if had_overlap else None

        elif msg_to_play == SpotterMessageType.CLEAR_LEFT:
            had_overlap = self.reported_single_overlap_left or self.reported_double_overlap_left
            self.reported_single_overlap_left = False
            self.reported_double_overlap_left = False

            if cars_on_right == 0 and self.was_in_middle:
                self.was_in_middle = False
                self.channel_open = False
                self.next_message_type = SpotterMessageType.NONE
                return SpotterMessageType.CLEAR_ALL_ROUND, False
            elif self.was_in_middle:
                self.next_message_type = SpotterMessageType.CAR_RIGHT
                self.next_message_due_time = now + self.repeat_hold_freq_sec
                return msg_to_play, True
            else:
                self.channel_open = (cars_on_right > 0)
                self.next_message_type = SpotterMessageType.NONE
                return (msg_to_play, False) if had_overlap else None

        elif msg_to_play == SpotterMessageType.CLEAR_RIGHT:
            had_overlap = self.reported_single_overlap_right or self.reported_double_overlap_right
            self.reported_single_overlap_right = False
            self.reported_double_overlap_right = False

            if cars_on_left == 0 and self.was_in_middle:
                self.was_in_middle = False
                self.channel_open = False
                self.next_message_type = SpotterMessageType.NONE
                return SpotterMessageType.CLEAR_ALL_ROUND, False
            elif self.was_in_middle:
                self.next_message_type = SpotterMessageType.CAR_LEFT
                self.next_message_due_time = now + self.repeat_hold_freq_sec
                return msg_to_play, True
            else:
                self.channel_open = (cars_on_left > 0)
                self.next_message_type = SpotterMessageType.NONE
                return (msg_to_play, False) if had_overlap else None

        elif msg_to_play == SpotterMessageType.STILL_THERE:
            has_active_overlap = (self.reported_single_overlap_left or self.reported_single_overlap_right or
                                  self.reported_double_overlap_left or self.reported_double_overlap_right)
            if has_active_overlap:
                self.next_message_type = SpotterMessageType.STILL_THERE
                self.next_message_due_time = now + self.repeat_hold_freq_sec
                return msg_to_play, True
            else:
                self.next_message_type = SpotterMessageType.NONE
                return None

        return None


# =============================================================================
# 7. MAIN RACE ENGINEER ROLE: FIGHT SPOTTER (SOLID - LSP / DIP)
# =============================================================================

@RoleRegistry.register(
    role_id="fight_spotter",
    name="Fight Spotter (CrewChief Cartesian FSM)",
    description="High-fidelity close-proximity battle spotter based on CrewChief V4: local 2D transformation, kinematic filtering, overlap hysteresis, 3-wide detection, and anti-chatter state machine.",
    default_priority=110,
)
class FightSpotterRole(BaseRole):
    """
    Fight Spotter Role implementing full close-combat architecture of CrewChiefV4.
    """

    def __init__(
        self,
        role_id: str = "fight_spotter",
        name: str = "Fight Spotter (CrewChief Cartesian FSM)",
        description: str = "",
        priority: int = 110,
        enabled: bool = True,
        audio_engine: Optional[AudioEngineType] = None,
        car_length_m: float = 4.2,
        car_width_m: float = 1.9,
        gap_needed_for_clear_m: float = 1.5,
        clear_message_delay_sec: float = 0.35,
        repeat_hold_freq_sec: float = 3.0,
        min_speed_kmh: float = 35.0,
        max_closing_speed_kmh: float = 90.0,
        use_oval_logic: bool = False,
        enable_three_wide: bool = True,
    ):
        super().__init__(
            role_id=role_id,
            name=name,
            description=description,
            priority=priority,
            enabled=enabled,
            audio_engine=audio_engine,
        )

        # Configurable parameters
        self.car_length_m = float(car_length_m)
        self.car_width_m = float(car_width_m)
        self.gap_needed_for_clear_m = float(gap_needed_for_clear_m)
        self.clear_message_delay_sec = float(clear_message_delay_sec)
        self.repeat_hold_freq_sec = float(repeat_hold_freq_sec)
        self.min_speed_mps = float(min_speed_kmh) / 3.6
        self.max_closing_speed_mps = float(max_closing_speed_kmh) / 3.6
        self.use_oval_logic = bool(use_oval_logic)
        self.enable_three_wide = bool(enable_three_wide)

        # Instantiation of modular subsystems (SOLID SRP/ISP/DIP)
        self.geometry_engine = CartesianGeometry2D()
        self.speed_filter = OpponentSpeedFilter(
            calculate_speeds_interval_sec=0.2,
            max_closing_speed_mps=self.max_closing_speed_mps,
        )
        self.overlap_evaluator = CartesianOverlapEvaluator(
            car_length_m=self.car_length_m,
            car_width_m=self.car_width_m,
            gap_needed_for_clear_m=self.gap_needed_for_clear_m,
        )
        self.fsm = SpotterStateMachine(
            clear_message_delay_sec=self.clear_message_delay_sec,
            repeat_hold_freq_sec=self.repeat_hold_freq_sec,
            enable_three_wide=self.enable_three_wide,
        )
        self._road_phrasing = RoadSpotterPhrasingStrategy()
        self._oval_phrasing = OvalSpotterPhrasingStrategy()

        # Dynamic previous telemetry variables
        self._prev_player_x: float = 0.0
        self._prev_player_z: float = 0.0
        self._prev_time: float = 0.0

        # Live diagnostic data for UI
        self._live_cars_left: int = 0
        self._live_cars_right: int = 0
        self._live_channel_open: bool = False
        self._live_last_message: str = "none"

    def get_parameters(self) -> List[RoleParam]:
        """Declares configurable parameters for UI editor."""
        return [
            FloatRangeParam(
                name="car_length_m",
                label="Car Length",
                description="Nominal vehicle length (meters)",
                min_val=2.5,
                max_val=6.0,
                step=0.1,
                unit="m",
                default=4.2,
            ),
            FloatRangeParam(
                name="car_width_m",
                label="Car Width",
                description="Nominal vehicle width (meters)",
                min_val=1.2,
                max_val=2.5,
                step=0.05,
                unit="m",
                default=1.9,
            ),
            FloatRangeParam(
                name="gap_needed_for_clear_m",
                label="Clear Gap Hysteresis",
                description="Extra distance required to declare 'Clear' (meters)",
                min_val=0.2,
                max_val=5.0,
                step=0.1,
                unit="m",
                default=1.5,
            ),
            FloatRangeParam(
                name="clear_message_delay_sec",
                label="Clear Delay",
                description="Confirmation delay before announcing Clear (seconds)",
                min_val=0.0,
                max_val=2.0,
                step=0.05,
                unit="s",
                default=0.35,
            ),
            FloatRangeParam(
                name="repeat_hold_freq_sec",
                label="Hold Repeat Frequency",
                description="Reminder frequency 'Still There' during maintained overlap (seconds)",
                min_val=1.0,
                max_val=10.0,
                step=0.5,
                unit="s",
                default=3.0,
            ),
            FloatRangeParam(
                name="min_speed_kmh",
                label="Min Speed for Spotter",
                description="Minimum speed required to activate Spotter (km/h)",
                min_val=10.0,
                max_val=100.0,
                step=5.0,
                unit="km/h",
                default=35.0,
            ),
            FloatRangeParam(
                name="max_closing_speed_kmh",
                label="Max Closing Speed",
                description="Maximum tolerated closing speed for overlap (km/h)",
                min_val=30.0,
                max_val=200.0,
                step=5.0,
                unit="km/h",
                default=90.0,
            ),
            BoolParam(
                name="use_oval_logic",
                label="Oval Track Phrasing",
                description="Use terms Inside / Outside instead of Left / Right",
                default=False,
            ),
            BoolParam(
                name="enable_three_wide",
                label="Enable 3-Wide Calls",
                description="Enable detection and announcements for 3-Wide situations",
                default=True,
            ),
        ]

    def set_param_value(self, name: str, value: ParamScalarValue) -> None:
        """Applies and synchronizes parameters with internal subsystems."""
        super().set_param_value(name, value)
        if name in ("car_length_m", "car_width_m", "gap_needed_for_clear_m"):
            self.overlap_evaluator.set_dimensions(
                self.car_length_m, self.car_width_m, self.gap_needed_for_clear_m
            )
        elif name == "clear_message_delay_sec":
            self.fsm.clear_message_delay_sec = float(self.clear_message_delay_sec)
        elif name == "repeat_hold_freq_sec":
            self.fsm.repeat_hold_freq_sec = float(self.repeat_hold_freq_sec)
        elif name == "min_speed_kmh":
            self.min_speed_mps = float(self.min_speed_kmh) / 3.6
        elif name == "max_closing_speed_kmh":
            self.max_closing_speed_mps = float(self.max_closing_speed_kmh) / 3.6
            self.speed_filter.max_closing_speed_mps = self.max_closing_speed_mps
        elif name == "enable_three_wide":
            self.fsm.enable_three_wide = bool(self.enable_three_wide)

    def get_channel_requirements(self) -> List[ChannelRequirement]:
        return [
            ChannelRequirement(
                channel=TelemetryChannel.TELEMETRY,
                preferred_hz=100,
                required=True,
                reason="Player yaw orientation and precise local kinematics",
            ),
            ChannelRequirement(
                channel=TelemetryChannel.FULL_SCORING,
                preferred_hz=10,
                required=True,
                reason="3D world positions and velocity vectors for all cars",
            ),
        ]

    def get_sound_requirements(self) -> Dict[str, str]:
        return {
            "car_left": "Car left",
            "car_right": "Car right",
            "clear_left": "Clear left",
            "clear_right": "Clear right",
            "clear_all_round": "Clear all round",
            "three_wide": "Three wide",
            "three_wide_left": "Three wide on the left",
            "three_wide_right": "Three wide on the right",
            "car_inside": "Car inside",
            "car_outside": "Car outside",
            "clear_inside": "Clear inside",
            "clear_outside": "Clear outside",
            "three_wide_inside": "Three wide on the inside",
            "three_wide_outside": "Three wide on the outside",
            "still_there": "Still there",
        }

    def is_busy(self) -> bool:
        """
        Indicates if Spotter is currently engaged in a critical situation
        (active overlap, 3-wide, or pending scheduled announcement).
        """
        return (
            self.fsm.channel_open or
            self.fsm.reported_single_overlap_left or
            self.fsm.reported_single_overlap_right or
            self.fsm.reported_double_overlap_left or
            self.fsm.reported_double_overlap_right or
            self.fsm.next_message_type != SpotterMessageType.NONE
        )

    def reset(self) -> None:
        """Completely resets role state."""
        self.fsm.reset()
        self.speed_filter.clear()
        self._prev_player_x = 0.0
        self._prev_player_z = 0.0
        self._prev_time = 0.0
        self._live_cars_left = 0
        self._live_cars_right = 0
        self._live_channel_open = False
        self._live_last_message = "none"

    def _extract_player_data(
        self,
        context: EngineerContext,
        now: float,
    ) -> Optional[Tuple[float, float, float, float, float]]:
        """
        Extracts position (X, Z), velocity (vx, vz), and yaw orientation of player.
        Returns (player_x, player_z, vel_x, vel_z, player_yaw_rad) or None.
        """
        player_veh = context.get_player_vehicle()
        if not player_veh:
            return None

        px = float(player_veh.pos.x)
        pz = float(player_veh.pos.z)

        if px == 0.0 and pz == 0.0:
            return None

        vx = float(player_veh.local_vel.x)
        vz = float(player_veh.local_vel.z)

        yaw_from_ori = self.geometry_engine.compute_yaw_from_orientation(player_veh.ori)
        if yaw_from_ori is not None:
            yaw = yaw_from_ori
        else:
            yaw = self.geometry_engine.compute_yaw_from_velocity(vx, vz)

        self._prev_player_x = px
        self._prev_player_z = pz
        self._prev_time = now

        return px, pz, vx, vz, yaw

    def on_physics_tick(self, state: TelemetryStateStore, context: EngineerContext) -> Optional[EngineerMessage]:
        """Physics tick evaluation (100-120Hz TelemInfo). Player high-speed cartesian kinematics."""
        return self._evaluate_fight(state, context)

    def on_grid_update(self, state: TelemetryStateStore, context: EngineerContext) -> Optional[EngineerMessage]:
        """Grid update evaluation (FullScoringSession). Opponents 2D positions, side-by-side overlap, and 3-wide."""
        return self._evaluate_fight(state, context)

    def update(self, context: EngineerContext) -> Optional[EngineerMessage]:
        """Polymorphic entry point for direct/manual evaluations."""
        return self._evaluate_fight(context.state_store, context)

    def _evaluate_fight(self, state: TelemetryStateStore, context: EngineerContext) -> Optional[EngineerMessage]:
        """
        Evaluates telemetry and relative positioning on each tick.
        """
        if not self.enabled:
            return None

        now = context.timestamp or time.time()

        # 1. Global filter conditions: Pits, Garage, Private Qualifying
        if context.is_player_in_pits() or context.is_player_in_garage() or context.is_private_qualifying():
            if self.is_busy():
                self.reset()
            return None

        # 2. Extract player data
        player_data = self._extract_player_data(context, now)
        if not player_data:
            return None

        player_x, player_z, player_vx, player_vz, player_yaw = player_data
        player_speed_scalar = math.sqrt(player_vx * player_vx + player_vz * player_vz)

        # Minimum speed filter
        if player_speed_scalar < self.min_speed_mps:
            if self.fsm.channel_open and (now > self.fsm.time_when_channel_should_close):
                self.reset()
            elif self.fsm.channel_open and self.fsm.time_when_channel_should_close == float("inf"):
                self.fsm.time_when_channel_should_close = now + self.fsm.time_to_wait_before_closing_channel_sec
            return None
        else:
            self.fsm.time_when_channel_should_close = float("inf")

        # 3. Retrieve opponents on track (excluding pits and garage)
        opponents = context.get_track_opponents()
        active_ids = set()

        left_separations: List[float] = []
        right_separations: List[float] = []

        had_overlap_left = self.fsm.cars_on_left_prev > 0
        had_overlap_right = self.fsm.cars_on_right_prev > 0

        # 4. Geometric and kinematic processing for each opponent
        for opp in opponents:
            opp_id = opp.id
            ox = float(opp.pos.x)
            oz = float(opp.pos.z)

            if ox == 0.0 and oz == 0.0:
                continue

            active_ids.add(opp_id)

            # Optional opponent velocity extraction
            ovx = float(opp.local_vel.x)
            ovz = float(opp.local_vel.z)

            # 2D Cartesian projection into player local frame
            aligned_x, aligned_z = self.geometry_engine.get_aligned_xz_coordinates(
                player_yaw, player_x, player_z, ox, oz
            )

            # Range pre-filtering check (20m)
            if not self.overlap_evaluator.is_in_consideration_zone(aligned_x, aligned_z):
                continue

            # Closing speed validation
            is_speed_valid = self.speed_filter.update_and_validate(
                opponent_id=opp_id,
                opp_x=ox,
                opp_z=oz,
                player_vel_x=player_vx,
                player_vel_z=player_vz,
                now=now,
                opp_vel_x=ovx,
                opp_vel_z=ovz,
            )

            # Overlap evaluation
            side, lateral_sep = self.overlap_evaluator.evaluate_opponent_overlap(
                aligned_x=aligned_x,
                aligned_z=aligned_z,
                had_overlap_on_side=(had_overlap_left if aligned_x > 0 else had_overlap_right),
                is_speed_valid=is_speed_valid,
            )

            if side == SpotterSide.LEFT:
                left_separations.append(lateral_sep)
            elif side == SpotterSide.RIGHT:
                right_separations.append(lateral_sep)

        # Purge vehicles out of range
        self.speed_filter.purge_inactive(active_ids)

        # 5. 3-Wide detection and line-astern filtering
        cars_on_left, cars_on_right = self.overlap_evaluator.analyze_multi_car_distribution(
            left_separations, right_separations
        )

        self._live_cars_left = cars_on_left
        self._live_cars_right = cars_on_right

        # 6. State machine evaluation (FSM)
        self.fsm.evaluate_next_message(
            cars_on_left=cars_on_left,
            cars_on_right=cars_on_right,
            now=now,
            use_oval_logic=self.use_oval_logic,
        )

        # 7. Audio playback execution
        playback_result = self.fsm.process_playback_tick(
            cars_on_left=cars_on_left,
            cars_on_right=cars_on_right,
            now=now,
        )

        self.fsm.cars_on_left_prev = cars_on_left
        self.fsm.cars_on_right_prev = cars_on_right
        self._live_channel_open = self.fsm.channel_open

        if playback_result is not None:
            msg_type, keep_open = playback_result
            strategy: ISpotterPhrasingStrategy = self._oval_phrasing if self.use_oval_logic else self._road_phrasing
            phrase_key = strategy.resolve_phrase(msg_type)

            if phrase_key:
                self._live_last_message = phrase_key
                # Close-combat spotter alerts have highest priority and interrupt regular messages
                msg = EngineerMessage(
                    phrase_key=phrase_key,
                    priority=self.priority,
                    interrupt=True,
                    role_id=self.role_id,
                )
                self.emit_sound(phrase_key, interrupt=True)
                return msg

        return None

    def get_state_summary(self) -> Dict[str, Union[str, int, float, bool, List[str], None]]:
        """Returns live state diagnostic for UI monitoring."""
        summary = super().get_state_summary()
        summary.update({
            "cars_on_left": self._live_cars_left,
            "cars_on_right": self._live_cars_right,
            "channel_open": self._live_channel_open,
            "last_message": self._live_last_message,
            "is_busy": self.is_busy(),
        })
        return summary


# Sub-plugin alias
FightSpotterSubplugin = FightSpotterRole
