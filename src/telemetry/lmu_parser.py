"""
SimPad Telemetry — LMU Telemetry Parser mapped precisely to LeMansUltimateTelemetryPlugin Spec.

Spec reference (from plugin documentation):
TelemInfoV01:
- mDeltaTime: Delta time in seconds (+/-)
- mFuel: Remaining fuel in liters
- mFrontDownforce, mRearDownforce: Aerodynamic downforce
- mUnfilteredThrottle, mUnfilteredBrake: Pedal inputs
- mGear, mEngineRPM, mEngineMaxRPM: Engine telemetry

ScoringInfoV01:
- mMaxLaps: Session max laps
- mVehicles -> player_veh (mIsPlayer == True):
    - mTotalLaps: Laps completed
    - mCurSector1, mCurSector2: Current sector times
    - mLastSector1, mLastSector2, mLastLapTime: Last lap sector & total times
    - mBestSector1, mBestSector2, mBestLapTime: Personal best sector & lap times
"""

import json
import math
import struct
import logging
from dataclasses import dataclass
from typing import Tuple, Optional, List

from src.telemetry.sensors import VehicleSensors
from src.telemetry.delta_engine import DeltaEngine

logger = logging.getLogger(__name__)


def format_time_sec(seconds: float) -> str:
    """Formatte les secondes en représentation propre [MM:]ss.mmm."""
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

    """Représentation structurée de la télémétrie décodée."""
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
    unfiltered_steering: float = 0.0
    in_realtime: bool = True
    gear: int = 0
    # Additional telemetry & scoring fields bound to HUD
    fuel: float = 0.0
    total_laps: int = 0
    laps_completed: int = 0
    delta_time: float = 0.0
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
    raw_scoring: Optional[dict] = None

    def to_sensors(self) -> VehicleSensors:
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
            fuel_level=self.fuel,
            remaining_laps=remaining,
            delta_time=self.delta_time,
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
        )




class LMUParser:
    """
    Décodeur de paquets UDP JSON pour Le Mans Ultimate Telemetry Plugin.
    Conforme à la spécification LeMansUltimateTelemetryPlugin (TelemInfoV01 & ScoringInfoV01).
    """

    PACKET_FORMAT = "<8f"
    PACKET_SIZE = struct.calcsize(PACKET_FORMAT)
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
    _last_unfiltered_steering: float = 0.0
    _last_lpv: tuple = (0.0, 0.0, 0.0, 0.0)
    _last_lgv: tuple = (0.0, 0.0, 0.0, 0.0)
    _last_lat_pv: tuple = (0.0, 0.0, 0.0, 0.0)
    _last_lat_gv: tuple = (0.0, 0.0, 0.0, 0.0)
    _last_travels: tuple = (0.0, 0.0, 0.0, 0.0)
    _last_susp_vels: tuple = (0.0, 0.0, 0.0, 0.0)

    _last_current_sector: int = 1
    _last_sector1_delta: float = 0.0
    _last_sector2_delta: float = 0.0
    _last_sector3_delta: float = 0.0
    _s1_checkpoint_delta: float = 0.0
    _s2_checkpoint_delta: float = 0.0
    _last_lap_flag: int = 2
    _last_scoring_json: Optional[dict] = None

    @classmethod
    def get_latest_scoring(cls) -> Optional[dict]:
        """Retourne le dernier paquet ScoringInfoV01 reçu."""
        return cls._last_scoring_json


    # Live lap reference spline recorder
    _best_lap_samples: List[Tuple[float, float]] = []
    _current_lap_samples: List[Tuple[float, float]] = []
    _last_recorded_lap_num: int = -1
    _best_lap_time_val: float = 999999.0

    ENABLE_DISK_DUMP: bool = False

    @classmethod
    def _dump_to_file(cls, js: dict) -> None:
        """Enregistre le paquet JSON brut si le dump est activé."""
        # TODO [SLAP]: File dumping operations mixed with telemetry parser logic.
        if not cls.ENABLE_DISK_DUMP:
            return
        try:
            from pathlib import Path
            project_root = Path(__file__).resolve().parent.parent.parent
            dump_file = project_root / "telemetry_dump.jsonl"
            with open(dump_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(js) + "\n")
        except Exception as e:
            logger.debug(f"[LMUParser] Error dumping telemetry: {e}")

    @classmethod
    def _dump_scoring_to_file(cls, js: dict) -> None:
        """Enregistre le paquet ScoringInfoV01 brut si le dump est activé."""
        if not cls.ENABLE_DISK_DUMP:
            return
        try:
            from pathlib import Path
            project_root = Path(__file__).resolve().parent.parent.parent
            dump_file = project_root / "scoring_dump.json"
            dump_file.write_text(json.dumps(js, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug(f"[LMUParser] Error dumping scoring: {e}")

    @classmethod
    def _extract_player_vehicle(cls, vehicles: list) -> Optional[dict]:
        """Extracts the player vehicle dictionary from the vehicle list (DRY helper)."""
        if not isinstance(vehicles, list):
            return None
        for v in vehicles:
            if isinstance(v, dict) and (v.get("mIsPlayer") or v.get("isPlayer")):
                return v
        for v in vehicles:
            if isinstance(v, dict) and v.get("mControl") == 0:
                return v
        return None

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
        """SLAP Helper: Computes session best sector 1, individual sector 2, and individual sector 3 times."""
        s1, s2_indiv, s3_indiv = 999999.0, 999999.0, 999999.0
        if not isinstance(vehicles, list):
            return s1, s2_indiv, s3_indiv

        for v in vehicles:
            if isinstance(v, dict):
                bs1 = float(v.get("mBestSector1", -1.0))
                bs2 = float(v.get("mBestSector2", -1.0))
                blap = float(v.get("mBestLapTime", -1.0))

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
    def _update_player_sector_times(cls, player_veh: dict, session_bests: Tuple[float, float, float]) -> None:
        """SLAP Helper: Formats sector times and assigns purple/green/default status colors for player vehicle."""
        session_best_s1, session_best_s2_indiv, session_best_s3_indiv = session_bests

        # Sector 1
        cur_s1 = float(player_veh.get("mCurSector1", -1.0))
        last_s1 = float(player_veh.get("mLastSector1", -1.0))
        best_s1 = float(player_veh.get("mBestSector1", -1.0))

        if cur_s1 > 0.0:
            cls._last_sector1_time = format_time_sec(cur_s1)
            cls._last_sector1_status = cls._calculate_sector_status(cur_s1, best_s1, session_best_s1)
        elif last_s1 > 0.0:
            cls._last_sector1_time = format_time_sec(last_s1)
            cls._last_sector1_status = cls._calculate_sector_status(last_s1, best_s1, session_best_s1)

        # Sector 2
        cur_s2 = float(player_veh.get("mCurSector2", -1.0))
        last_s2 = float(player_veh.get("mLastSector2", -1.0))
        best_s2 = float(player_veh.get("mBestSector2", -1.0))

        if cur_s2 > 0.0 and cur_s1 > 0.0:
            indiv_s2 = cur_s2 - cur_s1
            best_indiv_s2 = (best_s2 - best_s1) if (best_s2 > 0.0 and best_s1 > 0.0) else -1.0
            if indiv_s2 > 0.0:
                cls._last_sector2_time = format_time_sec(indiv_s2)
                cls._last_sector2_status = cls._calculate_sector_status(indiv_s2, best_indiv_s2, session_best_s2_indiv)
        elif last_s2 > 0.0 and last_s1 > 0.0:
            indiv_s2 = last_s2 - last_s1
            best_indiv_s2 = (best_s2 - best_s1) if (best_s2 > 0.0 and best_s1 > 0.0) else -1.0
            if indiv_s2 > 0.0:
                cls._last_sector2_time = format_time_sec(indiv_s2)
                cls._last_sector2_status = cls._calculate_sector_status(indiv_s2, best_indiv_s2, session_best_s2_indiv)

        # Sector 3
        last_lap = float(player_veh.get("mLastLapTime", -1.0))
        best_lap = float(player_veh.get("mBestLapTime", -1.0))

        if last_lap > 0.0 and last_s2 > 0.0:
            indiv_s3 = last_lap - last_s2
            best_indiv_s3 = (best_lap - best_s2) if (best_lap > 0.0 and best_s2 > 0.0) else -1.0
            if indiv_s3 > 0.0:
                cls._last_sector3_time = format_time_sec(indiv_s3)
                cls._last_sector3_status = cls._calculate_sector_status(indiv_s3, best_indiv_s3, session_best_s3_indiv)

    @classmethod
    def _parse_json_scoring(cls, js: dict) -> TelemetryData:
        """Parses ScoringInfoV01 packets (SLAP/KISS/SRP helper, CCN < 8)."""
        cls._dump_scoring_to_file(js)
        cls._last_scoring_json = js

        in_rt_top = js.get("mInRealtime", js.get("inRealtime", False))
        is_in_realtime = bool(in_rt_top != 0 and in_rt_top is not False)

        max_laps = int(js.get("mMaxLaps", js.get("maxLaps", 0)))
        if 0 < max_laps < 1000:
            cls._last_total_laps = max_laps

        vehicles = js.get("mVehicles", [])
        session_bests = cls._calculate_session_bests(vehicles)
        player_veh = cls._extract_player_vehicle(vehicles)

        cls._in_garage_trap = False
        if player_veh:
            in_garage = bool(player_veh.get("mInGarageStall", player_veh.get("inGarageStall", False)))
            ctrl = player_veh.get("mControl", 0)
            if in_garage or ctrl != 0:
                is_in_realtime = False
                cls._in_garage_trap = True

            if "mTotalLaps" in player_veh:
                cls._last_laps_completed = int(player_veh["mTotalLaps"])

            if "mCountLapFlag" in player_veh:
                cls._last_lap_flag = int(player_veh["mCountLapFlag"])
            elif "countLapFlag" in player_veh:
                cls._last_lap_flag = int(player_veh["countLapFlag"])

            cls._update_player_sector_times(player_veh, session_bests)

            cls._delta_engine.update_scoring(js)
            cls._last_delta_time = cls._delta_engine.live_delta
            cls._last_sector1_delta = cls._delta_engine.sector1_delta
            cls._last_sector2_delta = cls._delta_engine.sector2_delta
            cls._last_sector3_delta = cls._delta_engine.sector3_delta
            raw_sec = int(player_veh.get("mSector", 1))
            cls._last_current_sector = 3 if raw_sec == 0 else (raw_sec if raw_sec in (1, 2, 3) else 1)

        cls._last_in_realtime = is_in_realtime
        return cls._build_telemetry_snapshot()

    @classmethod
    def _extract_wheel_velocities(cls, wheels: list, veh_speed: float):
        """SLAP Helper: Computes wheel longitudinal, lateral, suspension travel and velocity vectors."""
        def _get_ground_vel(w: dict, default_speed: float) -> float:
            for k in ("mLongitudinalGroundVel", "longitudinalGroundVel", "mGroundSpeed", "groundSpeed"):
                if k in w:
                    return float(w[k])
            return default_speed

        def _get_patch_vel(w: dict, default_speed: float, ground_v: float) -> float:
            if "mRotation" in w and "mUnloadedRadius" in w:
                r = float(w["mUnloadedRadius"]) if float(w.get("mUnloadedRadius", 0)) > 0.05 else 0.33
                return float(w["mRotation"]) * r
            for k in ("mLongitudinalPatchVel", "longitudinalPatchVel", "mWheelSpeed", "wheelSpeed"):
                if k in w:
                    val = float(w[k])
                    if val == 0.0 and abs(ground_v) > 0.5:
                        return 0.0
                    if abs(ground_v) > 0.5 and abs(abs(val) - abs(ground_v)) < 0.3 * abs(ground_v):
                        return val
                    if abs(ground_v) > 0.5 and 0.0 < abs(val) < 0.5 * abs(ground_v):
                        return ground_v
                    return val
            return ground_v if abs(ground_v) > 0.1 else default_speed

        lgv = tuple(_get_ground_vel(w, veh_speed) for w in wheels[:4])
        lpv = tuple(_get_patch_vel(w, veh_speed, lgv[i]) for i, w in enumerate(wheels[:4]))
        lat_pv = tuple(float(w.get("mLateralPatchVel", w.get("lateralPatchVel", 0.0))) for w in wheels[:4])
        lat_gv = tuple(float(w.get("mLateralGroundVel", w.get("lateralGroundVel", 0.0))) for w in wheels[:4])
        raw_deflections = tuple(float(w.get("mSuspensionDeflection", w.get("suspensionDeflection", 0.0))) for w in wheels[:4])
        travels = tuple(min(1.0, max(0.0, d / 0.10)) for d in raw_deflections)
        susp_vels = tuple(abs(float(w.get("mSuspensionVelocity", w.get("suspensionVelocity", 0.0)))) for w in wheels[:4])

        return lpv, lgv, lat_pv, lat_gv, travels, susp_vels

    @classmethod
    def _determine_realtime_status(cls, js: dict) -> bool:
        """SLAP Helper: Determines if game engine is currently driving in active realtime."""
        if "mInRealtime" in js or "inRealtime" in js:
            in_rt_val = js.get("mInRealtime", js.get("inRealtime", None))
            if in_rt_val is not None:
                in_rt_flag = bool(in_rt_val != 0 and in_rt_val is not False)
                cls._in_garage_trap = not in_rt_flag
                cls._last_in_realtime = in_rt_flag
                return in_rt_flag

        return False if cls._in_garage_trap else cls._last_in_realtime

    @classmethod
    def _parse_json_telemetry(cls, js: dict) -> TelemetryData:
        """Parses TelemInfoV01 packets (SLAP/KISS helper, CCN < 6)."""
        if "mFuel" in js:
            cls._last_fuel = float(js["mFuel"])

        if "mFrontDownforce" in js and "mRearDownforce" in js:
            f_df = abs(float(js["mFrontDownforce"]))
            r_df = abs(float(js["mRearDownforce"]))
            cls._last_aero_downforce = min(100.0, (f_df + r_df) / 50.0)

        wheels = js.get("mWheel") or js.get("wheels") or []
        if isinstance(wheels, list) and len(wheels) >= 4:
            vel = js.get("mLocalVel")
            if isinstance(vel, dict) and any(k in vel for k in ("x", "y", "z")):
                vx = float(vel.get("x", 0.0))
                vy = float(vel.get("y", 0.0))
                vz = float(vel.get("z", 0.0))
                veh_speed = math.sqrt(vx * vx + vy * vy + vz * vz)
            elif isinstance(vel, (list, tuple)) and len(vel) >= 3:
                veh_speed = math.sqrt(float(vel[0])**2 + float(vel[1])**2 + float(vel[2])**2)
            else:
                veh_speed = float(js.get("mSpeed", js.get("speed", 0.0)))

            if any(k in js for k in ("mUnfilteredThrottle", "mThrottle", "unfilteredThrottle", "throttle")):
                cls._last_unfiltered_throttle = float(js.get("mUnfilteredThrottle", js.get("mThrottle", js.get("unfilteredThrottle", js.get("throttle", 0.0)))))

            if any(k in js for k in ("mUnfilteredBrake", "mBrake", "unfilteredBrake", "brake")):
                cls._last_unfiltered_brake = float(js.get("mUnfilteredBrake", js.get("mBrake", js.get("unfilteredBrake", js.get("brake", 0.0)))))

            if any(k in js for k in ("mUnfilteredSteering", "mSteering", "unfilteredSteering", "steering")):
                cls._last_unfiltered_steering = float(js.get("mUnfilteredSteering", js.get("mSteering", js.get("unfilteredSteering", js.get("steering", 0.0)))))

            cls._delta_engine.update_physics(
                veh_speed,
                throttle=cls._last_unfiltered_throttle,
                brake=cls._last_unfiltered_brake,
                steering=cls._last_unfiltered_steering,
            )
            cls._last_delta_time = cls._delta_engine.live_delta
            cls._last_sector1_delta = cls._delta_engine.sector1_delta
            cls._last_sector2_delta = cls._delta_engine.sector2_delta
            cls._last_sector3_delta = cls._delta_engine.sector3_delta

            lpv, lgv, lat_pv, lat_gv, travels, susp_vels = cls._extract_wheel_velocities(wheels, veh_speed)
            cls._last_lpv = lpv
            cls._last_lgv = lgv
            cls._last_lat_pv = lat_pv
            cls._last_lat_gv = lat_gv
            cls._last_travels = travels
            cls._last_susp_vels = susp_vels

        if "mEngineRPM" in js or "engineRPM" in js:
            cls._last_engine_rpm = float(js.get("mEngineRPM", js.get("engineRPM", 0.0)))
        if "mEngineMaxRPM" in js or "engineMaxRPM" in js:
            cls._last_engine_max_rpm = float(js.get("mEngineMaxRPM", js.get("engineMaxRPM", 7500.0)))

        cls._last_in_realtime = cls._determine_realtime_status(js)

        if "mGear" in js or "gear" in js:
            cls._last_gear = int(js["mGear"]) if "mGear" in js else int(js["gear"])

        if any(k in js for k in ("mUnfilteredThrottle", "mThrottle", "unfilteredThrottle", "throttle")):
            cls._last_unfiltered_throttle = float(js.get("mUnfilteredThrottle", js.get("mThrottle", js.get("unfilteredThrottle", js.get("throttle", 0.0)))))

        if any(k in js for k in ("mUnfilteredBrake", "mBrake", "unfilteredBrake", "brake")):
            cls._last_unfiltered_brake = float(js.get("mUnfilteredBrake", js.get("mBrake", js.get("unfilteredBrake", js.get("brake", 0.0)))))

        if any(k in js for k in ("mUnfilteredSteering", "mSteering", "unfilteredSteering", "steering")):
            cls._last_unfiltered_steering = float(js.get("mUnfilteredSteering", js.get("mSteering", js.get("unfilteredSteering", js.get("steering", 0.0)))))

        return cls._build_telemetry_snapshot()

    @classmethod
    def _build_telemetry_snapshot(cls) -> TelemetryData:
        """Helper to instantiate TelemetryData with current class state (DRY helper)."""
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
            unfiltered_steering=cls._last_unfiltered_steering,
            in_realtime=cls._last_in_realtime,
            gear=cls._last_gear,
            fuel=cls._last_fuel,
            total_laps=cls._last_total_laps,
            laps_completed=cls._last_laps_completed,
            delta_time=cls._last_delta_time,
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
            raw_scoring=cls._last_scoring_json,
        )

    @classmethod
    def parse(cls, data: bytes) -> Optional[TelemetryData]:
        """
        Décodeur principal conforme SLAP/KISS.
        Délègue le traitement aux sous-fonctions spécialisées par type de paquet.
        """
        if not data or len(data) < 10:
            return None

        raw_strip = data.strip()
        if raw_strip.startswith(b"{"):
            try:
                js = json.loads(raw_strip.decode("utf-8", errors="ignore"))
                msg_type = js.get("Type") or js.get("type", "")

                cls._dump_to_file(js)

                if msg_type == "System" or "Message" in js:
                    msg_text = str(js.get("Message", "")).lower()
                    if "enter realtime" in msg_text or "start session" in msg_text:
                        cls._in_garage_trap = False
                        cls._last_in_realtime = True
                        return cls._build_telemetry_snapshot()
                    elif "exit realtime" in msg_text or "end session" in msg_text:
                        cls._in_garage_trap = True
                        cls._last_in_realtime = False
                        return TelemetryData(in_realtime=False)

                if msg_type == "ScoringInfoV01" or "mVehicles" in js:
                    return cls._parse_json_scoring(js)

                if msg_type == "TelemInfoV01" or "mWheel" in js or "wheels" in js or "mEngineRPM" in js:
                    return cls._parse_json_telemetry(js)

            except Exception as e:
                logger.debug(f"[LMUParser] JSON decode error: {e}")

        if len(data) >= cls.PACKET_SIZE:
            try:
                values = struct.unpack(cls.PACKET_FORMAT, data[:cls.PACKET_SIZE])
                lpv = (float(values[0]), float(values[1]), float(values[2]), float(values[3]))
                lat_pv = (float(values[4]), float(values[5]), float(values[6]), float(values[7]))
                max_v = max(abs(v) for v in lpv)
                lgv = (max_v, max_v, max_v, max_v)
                return TelemetryData(
                    longitudinal_patch_vel=lpv,
                    longitudinal_ground_vel=lgv,
                    lateral_patch_vel=lat_pv,
                    in_realtime=True,
                    fuel=cls._last_fuel,
                    total_laps=cls._last_total_laps,
                    laps_completed=cls._last_laps_completed,
                    delta_time=cls._last_delta_time,
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
                )
            except Exception as e:
                logger.debug(f"[LMUParser] Erreur unpack 32b: {e}")

        return None
