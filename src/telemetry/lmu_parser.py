"""
SimPad Telemetry — LMU Telemetry Parser with Normalized Wheel Velocities.
"""

import json
import struct
import logging
import time
from dataclasses import dataclass
from typing import Tuple, Optional
from src.telemetry.sensors import VehicleSensors

logger = logging.getLogger(__name__)


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
    in_realtime: bool = True
    gear: int = 0

    def to_sensors(self) -> VehicleSensors:
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
        )


class LMUParser:
    """
    Décodeur de paquets UDP JSON pour Le Mans Ultimate Telemetry Plugin.
    """

    PACKET_FORMAT = "<8f"
    PACKET_SIZE = struct.calcsize(PACKET_FORMAT)
    _last_in_realtime: bool = True

    @classmethod
    def parse(cls, data: bytes) -> Optional[TelemetryData]:
        if not data or len(data) < 10:
            return None

        raw_strip = data.strip()
        if raw_strip.startswith(b"{"):
            try:
                js = json.loads(raw_strip.decode("utf-8", errors="ignore"))
                msg_type = js.get("Type") or js.get("type", "")

                # 1. Message de type ScoringInfoV01 (mise à jour de l'état InGame / Menu / Garage)
                if msg_type == "ScoringInfoV01" or "mVehicles" in js:
                    in_rt_top = js.get("mInRealtime", js.get("inRealtime", False))
                    is_in_realtime = bool(in_rt_top != 0 and in_rt_top is not False)

                    vehicles = js.get("mVehicles", [])
                    player_veh = None
                    if isinstance(vehicles, list):
                        for v in vehicles:
                            if isinstance(v, dict) and (v.get("mIsPlayer") or v.get("isPlayer")):
                                player_veh = v
                                break
                        if not player_veh and vehicles:
                            for v in vehicles:
                                if isinstance(v, dict) and v.get("mControl") == 0:
                                    player_veh = v
                                    break

                    if player_veh:
                        # Piege : Si la voiture est dans le stand (garage stall) ou pas sous contrôle humain (mControl != 0)
                        in_garage = bool(player_veh.get("mInGarageStall", player_veh.get("inGarageStall", False)))
                        ctrl = player_veh.get("mControl", 0)
                        if in_garage or ctrl != 0:
                            is_in_realtime = False

                    cls._last_in_realtime = is_in_realtime
                    return TelemetryData(in_realtime=cls._last_in_realtime)

                # 2. Message de type TelemInfoV01 (données télémétriques de conduite)
                if msg_type == "TelemInfoV01" or "mWheel" in js or "wheels" in js or "mEngineRPM" in js:
                    wheels = js.get("mWheel") or js.get("wheels") or []
                    lpv, lgv, lat_pv, lat_gv, travels, susp_vels = (
                        (0.0, 0.0, 0.0, 0.0),
                        (0.0, 0.0, 0.0, 0.0),
                        (0.0, 0.0, 0.0, 0.0),
                        (0.0, 0.0, 0.0, 0.0),
                        (0.0, 0.0, 0.0, 0.0),
                        (0.0, 0.0, 0.0, 0.0),
                    )

                    if isinstance(wheels, list) and len(wheels) >= 4:
                        veh_speed = float(js.get("mSpeed", js.get("speed", 0.0)))

                        def _get_ground_vel(w: dict, default_speed: float) -> float:
                            for k in ("mLongitudinalGroundVel", "longitudinalGroundVel", "mGroundSpeed", "groundSpeed"):
                                if k in w:
                                    return float(w[k])
                            return default_speed

                        def _get_patch_vel(w: dict, default_speed: float, ground_v: float) -> float:
                            # 1. Direct wheel rotation * radius calculation if available
                            if "mRotation" in w and "mUnloadedRadius" in w:
                                r = float(w["mUnloadedRadius"]) if float(w.get("mUnloadedRadius", 0)) > 0.05 else 0.33
                                return float(w["mRotation"]) * r

                            # 2. Wheel speed / patch vel
                            for k in ("mLongitudinalPatchVel", "longitudinalPatchVel", "mWheelSpeed", "wheelSpeed"):
                                if k in w:
                                    val = float(w[k])
                                    # Absolute 0.0 is explicit lockup when moving
                                    if val == 0.0 and abs(ground_v) > 0.5:
                                        return 0.0
                                    # If val is within reasonable range of ground speed, return val directly
                                    if abs(ground_v) > 0.5 and abs(abs(val) - abs(ground_v)) < 0.3 * abs(ground_v):
                                        return val
                                    # If val is small unscaled rad/s, fallback to ground_v when not locking
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

                    e_rpm = float(js.get("mEngineRPM", js.get("engineRPM", 0.0)))
                    e_max_rpm = float(js.get("mEngineMaxRPM", js.get("engineMaxRPM", 7500.0)))

                    if "mInRealtime" in js or "inRealtime" in js:
                        in_rt_val = js.get("mInRealtime", js.get("inRealtime", 1))
                        in_rt = bool(in_rt_val != 0 and in_rt_val is not False)
                        cls._last_in_realtime = in_rt
                    else:
                        in_rt = cls._last_in_realtime

                    gear_val = int(js["mGear"]) if "mGear" in js else (int(js["gear"]) if "gear" in js else 1)

                    return TelemetryData(
                        longitudinal_patch_vel=lpv,
                        longitudinal_ground_vel=lgv,
                        lateral_patch_vel=lat_pv,
                        lateral_ground_vel=lat_gv,
                        engine_rpm=e_rpm,
                        engine_max_rpm=e_max_rpm,
                        suspension_travels=travels,
                        suspension_velocities=susp_vels,
                        in_realtime=in_rt,
                        gear=gear_val,
                    )

            except Exception as e:
                logger.debug(f"[LMUParser] JSON decode error: {e}")

        # 3. Format binaire standard SimPad (32 octets = 8 floats)
        if len(data) >= cls.PACKET_SIZE:
            try:
                values = struct.unpack(cls.PACKET_FORMAT, data[:cls.PACKET_SIZE])
                lpv = (float(values[0]), float(values[1]), float(values[2]), float(values[3]))
                lat_pv = (float(values[4]), float(values[5]), float(values[6]), float(values[7]))
                max_v = max(abs(v) for v in lpv)
                lgv = (max_v, max_v, max_v, max_v)
                return TelemetryData(longitudinal_patch_vel=lpv, longitudinal_ground_vel=lgv, lateral_patch_vel=lat_pv, in_realtime=True)
            except Exception as e:
                logger.debug(f"[LMUParser] Erreur unpack 32b: {e}")

        return None
