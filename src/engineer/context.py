"""
SimPad Race Engineer — Evaluation context for race engineer roles.
Provides unified, clean, and optimized access to telemetry and scoring data (LMU).
"""

import math
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple, Union

try:
    from isimotor_rawudp_client import (
        TelemInfo,
        CompactScoring,
        FullScoringSession,
        VehicleScoring,
    )
except ImportError:
    TelemInfo = Any  # type: ignore
    CompactScoring = Any  # type: ignore
    FullScoringSession = Any  # type: ignore
    VehicleScoring = Any  # type: ignore

from src.telemetry.lmu_parser import TelemetryData


ATTRIBUTE_CANDIDATES_MAP: Dict[str, List[str]] = {
    "id": ["id", "mID", "m_id", "ID"],
    "mID": ["id", "mID", "m_id", "ID"],
    "driver_name": ["driver_name", "mDriverName", "driverName"],
    "mDriverName": ["driver_name", "mDriverName", "driverName"],
    "vehicle_name": ["vehicle_name", "mVehicleName", "vehicleName"],
    "mVehicleName": ["vehicle_name", "mVehicleName", "vehicleName"],
    "pit_state": ["pit_state", "mPitState", "pitState"],
    "mPitState": ["pit_state", "mPitState", "pitState"],
    "in_garage_stall": ["in_garage_stall", "mInGarageStall", "inGarageStall"],
    "mInGarageStall": ["in_garage_stall", "mInGarageStall", "inGarageStall"],
    "in_pits": ["in_pits", "mInPits", "inPits"],
    "mInPits": ["in_pits", "mInPits", "inPits"],
    "lap_dist": ["lap_dist", "mLapDist", "lapDist"],
    "mLapDist": ["lap_dist", "mLapDist", "lapDist"],
    "total_laps": ["total_laps", "mTotalLaps", "totalLaps"],
    "mTotalLaps": ["total_laps", "mTotalLaps", "totalLaps"],
    "count_lap_flag": ["count_lap_flag", "mCountLapFlag", "countLapFlag"],
    "mCountLapFlag": ["count_lap_flag", "mCountLapFlag", "countLapFlag"],
    "is_player": ["is_player", "mIsPlayer", "isPlayer"],
    "mIsPlayer": ["is_player", "mIsPlayer", "isPlayer"],
    "control": ["control", "mControl"],
    "mControl": ["control", "mControl"],
    "finish_status": ["finish_status", "mFinishStatus", "finishStatus"],
    "mFinishStatus": ["finish_status", "mFinishStatus", "finishStatus"],
    "speed": ["speed_mps", "speed", "mSpeed", "forward_speed_mps"],
    "speed_mps": ["speed_mps", "speed", "mSpeed", "forward_speed_mps"],
    "mSpeed": ["speed_mps", "speed", "mSpeed", "forward_speed_mps"],
    "sector": ["sector", "mSector"],
    "mSector": ["sector", "mSector"],
    "pos": ["pos", "mPos"],
    "mPos": ["pos", "mPos"],
    "local_vel": ["local_vel", "mLocalVel", "localVel"],
    "mLocalVel": ["local_vel", "mLocalVel", "localVel"],
    "ori": ["ori", "mOri"],
    "mOri": ["ori", "mOri"],
    "track_cut_state": ["track_cut_state", "mTrackCutState", "mIncidentState", "incident_state", "cut_state", "investigation_state", "offtrack_state"],
    "track_limits_steps": ["track_limits_steps", "mTrackLimitsSteps", "steps"],
    "num_penalties": ["num_penalties", "mNumPenalties", "numPenalties", "penalties"],
    "track_limits_steps_per_point": ["track_limits_steps_per_point", "mTrackLimitsStepsPerPoint", "steps_per_point"],
    "track_limits_steps_per_penalty": ["track_limits_steps_per_penalty", "mTrackLimitsStepsPerPenalty", "steps_per_penalty"],
}


def get_vehicle_attr(veh: Any, key: str, default: Any = None) -> Any:
    """
    Retrieves an attribute or dictionary key in a universal, bidirectional, and safe manner
    for a vehicle (typed VehicleScoring or telemetry dictionary).
    """
    if veh is None:
        return default

    candidates = ATTRIBUTE_CANDIDATES_MAP.get(key, [key])
    if key not in candidates:
        candidates = [key] + candidates

    # 1. If it's a dict
    if isinstance(veh, dict):
        for candidate in candidates:
            if candidate in veh and veh[candidate] is not None:
                return veh[candidate]
        # Nested search in "lmu"
        lmu_dict = veh.get("lmu")
        if isinstance(lmu_dict, dict):
            for candidate in candidates:
                if candidate in lmu_dict and lmu_dict[candidate] is not None:
                    return lmu_dict[candidate]
        return default

    # 2. If it's an object (e.g. VehicleScoring from isimotor_rawudp_client)
    for candidate in candidates:
        if hasattr(veh, candidate):
            val = getattr(veh, candidate)
            if val is not None:
                return val

    # Search in typed lmu extension (LMUVehicleScoringExtension / LMUTelemetryExtension)
    if hasattr(veh, "lmu") and getattr(veh, "lmu") is not None:
        lmu_obj = getattr(veh, "lmu")
        for candidate in candidates:
            if hasattr(lmu_obj, candidate):
                val = getattr(lmu_obj, candidate)
                if val is not None:
                    return val

    return default


@dataclass
class EngineerContext:
    """
    Context object passed to roles on every evaluation tick.
    Encapsulates physical telemetry and global scoring/session info (dict or typed isimotor models).
    """
    telemetry: Optional[Union[TelemetryData, TelemInfo, Any]] = None
    scoring: Optional[Union[Dict[str, Any], FullScoringSession, CompactScoring, Any]] = None
    timestamp: float = field(default_factory=time.time)
    audio_engine: Optional[Any] = None
    reference_profile: Optional[Any] = None

    @staticmethod
    def get_attr(veh: Any, key: str, default: Any = None) -> Any:
        """Static helper method to access vehicle attributes."""
        return get_vehicle_attr(veh, key, default)

    def get_session_type(self) -> int:
        """
        Returns mSession code received from scoring packet (LMU / rF2):
        0 = TestDay
        1..4 = Practice (FP1 to FP4)
        5..8 = Qualifying (Q1 to Q4 / Hyperpole / Private Qual)
        9 = Warmup
        10..13 = Race (Race 1 to 4)
        Returns -1 if unavailable.
        """
        if self.scoring is not None:
            if hasattr(self.scoring, "session"):
                try:
                    return int(self.scoring.session)
                except (ValueError, TypeError):
                    pass
            elif isinstance(self.scoring, dict):
                try:
                    return int(self.scoring.get("mSession", self.scoring.get("session", -1)))
                except (ValueError, TypeError):
                    pass
        return -1

    def is_qualifying_session(self) -> bool:
        """Indicates whether active session is a qualifying session (mSession between 5 and 8 inclusive)."""
        return self.get_session_type() in (5, 6, 7, 8)

    def is_private_qualifying(self) -> bool:
        """
        Indicates whether active session is in private qualifying.
        In Le Mans Ultimate, qualifying sessions (mSession 5-8) are isolated
        (ghost/invisible cars, no physical contact possible).
        """
        return self.is_qualifying_session()

    def get_track_name(self) -> str:
        """Returns active track name from scoring packet or reference profile."""
        if self.scoring is not None:
            if hasattr(self.scoring, "track_name"):
                name = str(self.scoring.track_name).strip()
                if name:
                    return name
            elif isinstance(self.scoring, dict):
                name = str(self.scoring.get("mTrackName", self.scoring.get("trackName", ""))).strip()
                if name:
                    return name

        if self.reference_profile is not None:
            ref_name = getattr(self.reference_profile, "track_name", "")
            if ref_name:
                return ref_name
        try:
            from src.telemetry.lmu_parser import LMUParser
            delta_eng = getattr(LMUParser, "_delta_engine", None)
            if delta_eng and delta_eng.track_name:
                return delta_eng.track_name
        except Exception:
            pass
        return ""

    def get_reference_profile(self) -> Optional[Any]:
        """Returns active reference lap profile if it matches current track."""
        scoring_track = self.get_track_name()

        if self.reference_profile is not None:
            ref_track = getattr(self.reference_profile, "track_name", "")
            if scoring_track and ref_track:
                t1 = "".join(c for c in scoring_track if c.isalnum()).lower()
                t2 = "".join(c for c in ref_track if c.isalnum()).lower()
                if t1 and t2 and t1 != t2:
                    return None
            return self.reference_profile

        try:
            from src.telemetry.lmu_parser import LMUParser
            delta_eng = getattr(LMUParser, "_delta_engine", None)
            if delta_eng:
                # Track engineer (traffic, markers) always uses all-time best reference lap
                prof = delta_eng.all_time_best_profile or delta_eng.current_profile
                if prof:
                    ref_track = getattr(prof, "track_name", "")
                    if scoring_track and ref_track:
                        t1 = "".join(c for c in scoring_track if c.isalnum()).lower()
                        t2 = "".join(c for c in ref_track if c.isalnum()).lower()
                        if t1 and t2 and t1 != t2:
                            return None
                    return prof
        except Exception:
            pass
        return None

    def get_reference_speed_mps(
        self,
        track_dist: float,
        profile: Optional[Any] = None,
    ) -> Optional[float]:
        """Returns reference lap speed at given track position (m/s)."""
        ref_prof = profile or self.get_reference_profile()
        if not ref_prof or getattr(ref_prof, "num_points", 0) < 2:
            return None
        val = ref_prof.get_value_at_dist(track_dist)
        return float(val.get("speed_ms", 0.0))

    def is_speed_in_normal_domain(
        self,
        speed_mps: float,
        track_dist: float,
        profile: Optional[Any] = None,
        tolerance_kmh: float = 30.0,
    ) -> bool:
        """
        Checks if given speed is within 'normal racing domain'
        relative to reference lap at exact track position.
        """
        ref_prof = profile or self.get_reference_profile()
        if not ref_prof or getattr(ref_prof, "num_points", 0) < 2:
            return True

        val = ref_prof.get_value_at_dist(track_dist)
        ref_speed_mps = float(val.get("speed_ms", 0.0))
        ref_speed_kmh = ref_speed_mps * 3.6
        actual_speed_kmh = speed_mps * 3.6

        # If reference lap has no valid speed at this location
        if ref_speed_kmh <= 1.0:
            return True

        delta_kmh = abs(actual_speed_kmh - ref_speed_kmh)
        return delta_kmh <= float(tolerance_kmh)

    def is_vehicle_in_normal_domain(
        self,
        veh: Any,
        profile: Optional[Any] = None,
        tolerance_kmh: float = 30.0,
    ) -> bool:
        """
        Determines if vehicle is driving within its 'normal' speed domain
        based on track position.
        """
        if veh is None:
            return True
        track_len = self.get_track_length()
        lap_dist = float(get_vehicle_attr(veh, "lap_dist", 0.0)) % track_len

        speed_mps = self.extract_vehicle_speed_mps(veh)
        return self.is_speed_in_normal_domain(
            speed_mps=speed_mps,
            track_dist=lap_dist,
            profile=profile,
            tolerance_kmh=tolerance_kmh,
        )

    def is_player_in_normal_domain(
        self,
        profile: Optional[Any] = None,
        tolerance_kmh: float = 30.0,
    ) -> bool:
        """Determines if player vehicle is driving within normal speed domain."""
        player_veh = self.get_player_vehicle()
        if not player_veh:
            return True
        track_len = self.get_track_length()
        lap_dist = float(get_vehicle_attr(player_veh, "lap_dist", 0.0)) % track_len
        player_speed = self.get_player_speed_mps()
        return self.is_speed_in_normal_domain(
            speed_mps=player_speed,
            track_dist=lap_dist,
            profile=profile,
            tolerance_kmh=tolerance_kmh,
        )

    def has_traffic_domain_anomaly(
        self,
        player_veh: Any,
        opp_veh: Any,
        profile: Optional[Any] = None,
        tolerance_kmh: float = 30.0,
    ) -> bool:
        """
        Checks filter condition for traffic roles:
        At least one vehicle (player OR opponent) must be out of normal domain.
        """
        ref_prof = profile or self.get_reference_profile()
        if not ref_prof or getattr(ref_prof, "num_points", 0) < 2:
            return True

        player_in = self.is_vehicle_in_normal_domain(player_veh, profile=ref_prof, tolerance_kmh=tolerance_kmh)
        opp_in = self.is_vehicle_in_normal_domain(opp_veh, profile=ref_prof, tolerance_kmh=tolerance_kmh)

        return (not player_in) or (not opp_in)

    def get_track_length(self) -> float:
        """Returns total track length in meters."""
        if self.scoring is not None:
            if hasattr(self.scoring, "lap_dist"):
                lap_dist = float(self.scoring.lap_dist)
                if lap_dist > 500.0:
                    return lap_dist
            elif isinstance(self.scoring, dict):
                lap_dist = float(self.scoring.get("mLapDist", self.scoring.get("lapDist", 0.0)))
                if lap_dist > 500.0:
                    return lap_dist
        return 5000.0  # Fallback default

    def get_player_vehicle(self) -> Optional[Any]:
        """Extracts player vehicle from scoring session (VehicleScoring or dict)."""
        if not self.scoring:
            return None

        if hasattr(self.scoring, "player_vehicle"):
            pv = self.scoring.player_vehicle
            if pv is not None:
                return pv

        vehicles = getattr(self.scoring, "vehicles", None)
        if vehicles is None and isinstance(self.scoring, dict):
            vehicles = self.scoring.get("mVehicles", [])

        if isinstance(vehicles, (list, tuple)):
            for v in vehicles:
                if get_vehicle_attr(v, "is_player") or get_vehicle_attr(v, "mIsPlayer"):
                    return v

            for v in vehicles:
                if get_vehicle_attr(v, "control") == 0:
                    return v

        # CompactScoring / single vehicle scoring object
        if hasattr(self.scoring, "count_lap_flag") or hasattr(self.scoring, "cur_sector1") or hasattr(self.scoring, "total_laps"):
            return self.scoring

        return None

    def is_player_in_pits(self) -> bool:
        """Indicates whether player vehicle is currently in pitlane (between entry and exit)."""
        player = self.get_player_vehicle()
        if not player:
            return False
        return self.is_vehicle_in_pits(player)

    def is_player_in_garage(self) -> bool:
        """Indicates whether player is in garage stall or menus."""
        # 1. If active physical telemetry confirms realtime on track,
        # we are NOT in garage (prevents false positives during UDP transitions)
        if self.telemetry is not None and getattr(self.telemetry, "in_realtime", False):
            player = self.get_player_vehicle()
            if player and bool(get_vehicle_attr(player, "in_garage_stall", False)):
                return True
            return False

        # 2. Check at global scoring session level
        if self.scoring is not None:
            if getattr(self.scoring, "game_phase", 5) == 0:
                return True
            if hasattr(self.scoring, "in_realtime") and not bool(self.scoring.in_realtime):
                return True
            if bool(get_vehicle_attr(self.scoring, "in_garage_stall", False)):
                return True

        # 3. Check on player vehicle
        player = self.get_player_vehicle()
        if player:
            return self.is_vehicle_in_garage(player)

        return False

    @classmethod
    def is_vehicle_in_pits(cls, veh: Any) -> bool:
        """
        Indicates whether a given vehicle is in pitlane.
        Checks in_pits/mInPits flags and pit_state/mPitState (2=entering, 3=stopped, 4=exiting).
        """
        if veh is None:
            return False
        if bool(get_vehicle_attr(veh, "in_pits", False)):
            return True
        pit_state = get_vehicle_attr(veh, "pit_state", 0)
        try:
            if int(pit_state) in (2, 3, 4):
                return True
        except (ValueError, TypeError):
            pass
        return False

    @classmethod
    def is_vehicle_in_garage(cls, veh: Any) -> bool:
        """Indicates whether a given vehicle is in its garage / pit stall."""
        if veh is None:
            return False
        return bool(get_vehicle_attr(veh, "in_garage_stall", False))

    def get_track_opponents(self) -> List[Any]:
        """
        Returns list of active opponent vehicles ON TRACK (excluding pits and garage).
        Ensures no pitlane vehicle interferes with on-track spotter or traffic calculations.
        """
        return self.get_opponent_vehicles(include_pits=False, include_garage=False)

    def get_pit_opponents(self) -> List[Any]:
        """
        Returns list of active opponent vehicles IN PITLANE (excluding garage).
        Enables distinct handling of pitlane traffic.
        """
        if not self.scoring:
            return []

        vehicles = getattr(self.scoring, "vehicles", None)
        if vehicles is None and isinstance(self.scoring, dict):
            vehicles = self.scoring.get("mVehicles", [])

        if not isinstance(vehicles, (list, tuple)):
            return []

        pit_opponents = []
        for v in vehicles:
            if get_vehicle_attr(v, "is_player") or get_vehicle_attr(v, "control") == 0:
                continue
            if self.is_vehicle_in_garage(v):
                continue
            if not self.is_vehicle_in_pits(v):
                continue
            finish_status = get_vehicle_attr(v, "finish_status", 0)
            if finish_status not in (0, "0"):
                continue
            pit_opponents.append(v)
        return pit_opponents

    def get_opponent_vehicles(
        self,
        include_pits: bool = False,
        include_garage: bool = False,
    ) -> List[Any]:
        """
        Returns list of active opponent vehicles.
        Excludes player, vehicles in garage (unless include_garage=True),
        and cars in pits (unless include_pits=True).
        """
        if not self.scoring:
            return []

        vehicles = getattr(self.scoring, "vehicles", None)
        if vehicles is None and isinstance(self.scoring, dict):
            vehicles = self.scoring.get("mVehicles", [])

        if not isinstance(vehicles, (list, tuple)):
            return []

        opponents = []
        for v in vehicles:
            if get_vehicle_attr(v, "is_player") or get_vehicle_attr(v, "control") == 0:
                continue
            if not include_garage and self.is_vehicle_in_garage(v):
                continue
            if not include_pits and self.is_vehicle_in_pits(v):
                continue
            finish_status = get_vehicle_attr(v, "finish_status", 0)
            if finish_status not in (0, "0"):
                continue
            opponents.append(v)
        return opponents

    @classmethod
    def extract_vehicle_speed_mps(cls, veh: Any) -> float:
        """Calculates scalar speed in m/s of vehicle (VehicleScoring or dict)."""
        if veh is None:
            return 0.0
        if hasattr(veh, "speed_mps"):
            return float(veh.speed_mps)

        vel = get_vehicle_attr(veh, "local_vel")
        if isinstance(vel, dict):
            vx = float(vel.get("x", 0.0))
            vy = float(vel.get("y", 0.0))
            vz = float(vel.get("z", 0.0))
            return math.sqrt(vx * vx + vy * vy + vz * vz)
        elif hasattr(vel, "x") and hasattr(vel, "y") and hasattr(vel, "z"):
            return math.sqrt(float(vel.x)**2 + float(vel.y)**2 + float(vel.z)**2)
        elif isinstance(vel, (list, tuple)) and len(vel) >= 3:
            return math.sqrt(float(vel[0])**2 + float(vel[1])**2 + float(vel[2])**2)

        speed = get_vehicle_attr(veh, "speed")
        if speed is not None:
            return float(speed)
        return 0.0

    def get_player_speed_mps(self) -> float:
        """Returns instantaneous player speed in m/s."""
        # 1. From high-frequency telemetry if available
        if self.telemetry is not None:
            if hasattr(self.telemetry, "speed_mps"):
                return float(self.telemetry.speed_mps)
            if hasattr(self.telemetry, "longitudinal_ground_vel") and self.telemetry.longitudinal_ground_vel:
                speeds = [abs(v) for v in self.telemetry.longitudinal_ground_vel if isinstance(v, (int, float))]
                if speeds:
                    return max(speeds)

        # 2. From player vehicle in scoring
        player_veh = self.get_player_vehicle()
        if player_veh is not None:
            return self.extract_vehicle_speed_mps(player_veh)

        return 0.0

    def compute_distance_behind(
        self,
        player_veh: Any,
        opp_veh: Any,
        track_length: Optional[float] = None,
    ) -> float:
        """
        Calculates relative distance along track spline.
        - Value > 0: Opponent is BEHIND player (in meters).
        - Value < 0: Opponent is AHEAD OF player (in meters).
        Handles finish line wraparound.
        """
        l_track = track_length or self.get_track_length()
        p_dist = float(get_vehicle_attr(player_veh, "lap_dist", 0.0)) % l_track
        o_dist = float(get_vehicle_attr(opp_veh, "lap_dist", 0.0)) % l_track

        delta = (p_dist - o_dist) % l_track
        if delta < l_track / 2.0:
            return delta  # Opponent behind
        else:
            return delta - l_track  # Opponent ahead (negative value)

    @classmethod
    def compute_euclidean_distance(cls, veh_a: Any, veh_b: Any) -> float:
        """Calculates 3D Euclidean distance between two vehicles if mPos/pos position is available."""
        def _get_xyz(v):
            if v is None:
                return None
            p = get_vehicle_attr(v, "pos")
            if p is not None:
                if hasattr(p, "x") and hasattr(p, "y") and hasattr(p, "z"):
                    x, y, z = float(p.x), float(p.y), float(p.z)
                    if not (x == 0.0 and y == 0.0 and z == 0.0):
                        return x, y, z
                elif isinstance(p, dict):
                    x, y, z = float(p.get("x", 0.0)), float(p.get("y", 0.0)), float(p.get("z", 0.0))
                    if not (x == 0.0 and y == 0.0 and z == 0.0):
                        return x, y, z
                elif isinstance(p, (list, tuple)) and len(p) >= 3:
                    x, y, z = float(p[0]), float(p[1]), float(p[2])
                    if not (x == 0.0 and y == 0.0 and z == 0.0):
                        return x, y, z
            return None

        pos_a = _get_xyz(veh_a)
        pos_b = _get_xyz(veh_b)
        if pos_a is None or pos_b is None:
            return float("inf")

        xa, ya, za = pos_a
        xb, yb, zb = pos_b
        return math.sqrt((xa - xb)**2 + (ya - yb)**2 + (za - zb)**2)

