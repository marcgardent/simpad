"""
SimPad Telemetry — LMU Telemetry Parser with Normalized Wheel Velocities.
"""

import json
import struct
import logging
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

    def to_sensors(self) -> VehicleSensors:
        return VehicleSensors.from_wheel_velocities(
            self.longitudinal_patch_vel,
            self.longitudinal_ground_vel,
            self.lateral_patch_vel,
            self.lateral_ground_vel,
        )


class LMUParser:
    """
    Décodeur de paquets UDP JSON pour Le Mans Ultimate Telemetry Plugin.
    """

    PACKET_FORMAT = "<8f"
    PACKET_SIZE = struct.calcsize(PACKET_FORMAT)

    @classmethod
    def parse(cls, data: bytes) -> Optional[TelemetryData]:
        if not data or len(data) < 10:
            return None

        raw_strip = data.strip()
        if raw_strip.startswith(b"{"):
            try:
                js = json.loads(raw_strip.decode("utf-8", errors="ignore"))
                msg_type = js.get("Type") or js.get("type", "")

                if msg_type == "TelemInfoV01" or "mWheel" in js or "wheels" in js:
                    wheels = js.get("mWheel") or js.get("wheels") or []
                    if isinstance(wheels, list) and len(wheels) >= 4:
                        lpv = tuple(float(w.get("mLongitudinalPatchVel", w.get("longitudinalPatchVel", 0.0))) for w in wheels[:4])
                        lgv = tuple(float(w.get("mLongitudinalGroundVel", w.get("longitudinalGroundVel", lpv[i]))) for i, w in enumerate(wheels[:4]))
                        lat_pv = tuple(float(w.get("mLateralPatchVel", w.get("lateralPatchVel", 0.0))) for w in wheels[:4])
                        lat_gv = tuple(float(w.get("mLateralGroundVel", w.get("lateralGroundVel", 0.0))) for w in wheels[:4])

                        return TelemetryData(
                            longitudinal_patch_vel=lpv,
                            longitudinal_ground_vel=lgv,
                            lateral_patch_vel=lat_pv,
                            lateral_ground_vel=lat_gv,
                        )

            except Exception as e:
                logger.debug(f"[LMUParser] JSON decode error: {e}")

        # 2. Format binaire standard SimPad (32 octets = 8 floats)
        if len(data) >= cls.PACKET_SIZE:
            try:
                values = struct.unpack(cls.PACKET_FORMAT, data[:cls.PACKET_SIZE])
                lpv = (float(values[0]), float(values[1]), float(values[2]), float(values[3]))
                lat_pv = (float(values[4]), float(values[5]), float(values[6]), float(values[7]))
                return TelemetryData(longitudinal_patch_vel=lpv, longitudinal_ground_vel=(0.0, 0.0, 0.0, 0.0), lateral_patch_vel=lat_pv)
            except Exception as e:
                logger.debug(f"[LMUParser] Erreur unpack 32b: {e}")

        return None
