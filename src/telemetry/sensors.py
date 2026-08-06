"""
SimPad Telemetry — Normalized Vehicle Sensors Domain Abstraction.
Normalizes raw wheel velocities into dimensionless physical slip ratios (0.0 to 1.0).
Zero vibration while cruising; proportional vibration only on lock, spin, oversteer, or understeer.
"""

import math
from dataclasses import dataclass
from typing import Tuple


@dataclass
class VehicleSensors:
    """
    Abstraction normalisée sans dimension des capteurs de glissement (0.0 à 1.0).
    """

    # 1. Glissement longitudinal - Freinage / Blocage de roues (FL, FR, RL, RR)
    front_left_lock: float = 0.0
    front_right_lock: float = 0.0
    rear_left_lock: float = 0.0
    rear_right_lock: float = 0.0

    # 2. Glissement longitudinal - Accélération / Patinage TC (FL, FR, RL, RR)
    front_left_spin: float = 0.0
    front_right_spin: float = 0.0
    rear_left_spin: float = 0.0
    rear_right_spin: float = 0.0

    # 3. Glissement latéral - Virage / Décrochage (FL, FR, RL, RR)
    front_left_lat_slip: float = 0.0
    front_right_lat_slip: float = 0.0
    rear_left_lat_slip: float = 0.0
    rear_right_lat_slip: float = 0.0

    # 4. Régime Moteur
    engine_rpm: float = 0.0
    engine_max_rpm: float = 7500.0

    # 5. Débattement / Suspension Travel des roues (FL, FR, RL, RR) [0.0 à 1.0]
    front_left_travel: float = 0.0
    front_right_travel: float = 0.0
    rear_left_travel: float = 0.0
    rear_right_travel: float = 0.0

    # 6. Adhérence Pneumatique / Grip Fraction (FL, FR, RL, RR) [0.0 à 1.0]
    front_left_grip: float = 1.0
    front_right_grip: float = 1.0
    rear_left_grip: float = 1.0
    rear_right_grip: float = 1.0

    # Vitesse du véhicule (m/s)
    vehicle_speed: float = 0.0

    # Pédales non filtrées (0.0 à 1.0)
    unfiltered_throttle: float = 0.0
    unfiltered_brake: float = 0.0

    # Télémétrie de session, chrono et énergie
    fuel_level: float = 0.0
    remaining_laps: int = 0
    delta_time: float = 0.0
    sector1_time: str = "--"
    sector1_status: str = "default"
    sector2_time: str = "--"
    sector2_status: str = "default"
    sector3_time: str = "--"
    sector3_status: str = "default"
    explicit_aero_load: float = 0.0
    current_sector: int = 1
    sector1_delta: float = 0.0
    sector2_delta: float = 0.0
    sector3_delta: float = 0.0
    lap_flag: int = 2

    # État en piste et rapport engagé
    in_realtime: bool = True
    gear: int = 0

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
        fuel_level: float = 0.0,
        remaining_laps: int = 0,
        delta_time: float = 0.0,
        sector1_time: str = "--",
        sector1_status: str = "default",
        sector2_time: str = "--",
        sector2_status: str = "default",
        sector3_time: str = "--",
        sector3_status: str = "default",
        explicit_aero_load: float = 0.0,
        current_sector: int = 1,
        sector1_delta: float = 0.0,
        sector2_delta: float = 0.0,
        sector3_delta: float = 0.0,
        lap_flag: int = 2,
    ) -> "VehicleSensors":

        if not in_realtime:
            return cls(in_realtime=False, gear=gear)

        locks = []
        spins = []
        lats = []
        grips = []

        avg_speed = sum(abs(v) for v in long_ground_vels) / 4.0

        for i in range(4):
            lpv = float(long_patch_vels[i])
            lgv = float(long_ground_vels[i]) if i < len(long_ground_vels) else 0.0
            lat_pv = float(lat_patch_vels[i]) if i < len(lat_patch_vels) else 0.0

            lpv_mag = abs(lpv)
            lgv_mag = abs(lgv)
            lat_pv_mag = abs(lat_pv)

            # Effective speed for slip ratio calculation
            speed = max(0.5, lgv_mag, lpv_mag)

            # Wheel Lockup (Over-braking): Ground speed > Patch speed par au moins 5% pour filtrer les micro-reliefs de piste
            if lgv_mag > 1.5 and lpv_mag < 0.2 * lgv_mag:
                locks.append(min(1.0, (lgv_mag - lpv_mag) / speed))
            else:
                locks.append(0.0)

            # Wheel Spin (TC / Over-acceleration): Patch speed > Ground speed (wheel spinning faster than vehicle ground speed)
            if lpv_mag > lgv_mag + 2.0 and lgv_mag > 0.5:
                spins.append(min(1.0, (lpv_mag - lgv_mag) / speed))
            else:
                spins.append(0.0)

            # Lateral Slip (Oversteer / Understeer): Lateral patch speed relative to effective speed
            lats.append(min(1.0, lat_pv_mag / speed))
            grips.append(max(0.0, 1.0 - max(locks[-1], spins[-1], lats[-1])))

        # Dynamic kerb / vibreur travel intensity from suspension velocity (scaled: 0.40 m/s = 1.0)
        travels = tuple(min(1.0, max(0.0, t)) for t in suspension_travels)

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
            vehicle_speed=avg_speed,
            unfiltered_throttle=max(0.0, min(1.0, float(unfiltered_throttle))),
            unfiltered_brake=max(0.0, min(1.0, float(unfiltered_brake))),
            fuel_level=fuel_level,
            remaining_laps=remaining_laps,
            delta_time=delta_time,
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
            in_realtime=True,
            gear=gear,
        )


    # ── Timing, Sector & Aero Properties ──────────────────────────────────────
    @property
    def delta_time_str(self) -> str:
        """Chrono Delta formaté (ex: '-0.150' ou '+0.240')."""
        if self.delta_time < 0.0:
            return f"-{abs(self.delta_time):.3f}"
        elif self.delta_time > 0.0:
            return f"+{self.delta_time:.3f}"
        return "--"

    def sector_delta_str(self, sector_num: int) -> str:
        """Delta Live formaté d'un secteur actif (ex: '-0.150' ou '+0.240')."""
        val = getattr(self, f"sector{sector_num}_delta", 0.0)
        if val < 0.0:
            return f"-{abs(val):.3f}"
        elif val > 0.0:
            return f"+{val:.3f}"
        return "--"

    @property
    def sectors_list(self) -> list:
        """Liste structurée des 3 secteurs pour le SectorTimesWidget."""
        return [
            {
                "time": self.sector1_time,
                "status": self.sector1_status,
                "delta": self.sector1_delta,
                "delta_str": self.sector_delta_str(1),
                "is_current": (self.current_sector == 1),
            },
            {
                "time": self.sector2_time,
                "status": self.sector2_status,
                "delta": self.sector2_delta,
                "delta_str": self.sector_delta_str(2),
                "is_current": (self.current_sector == 2),
            },
            {
                "time": self.sector3_time,
                "status": self.sector3_status,
                "delta": self.sector3_delta,
                "delta_str": self.sector_delta_str(3),
                "is_current": (self.current_sector == 3),
            },
        ]

    # ── Combined & Per-Side Sensor Intensity Properties (0.0 to 1.0) ──────────
    @property
    def lock_intensity(self) -> float:
        """Over-Braking intensity (Combined Max FL/FR/RL/RR)."""
        return max(self.front_left_lock, self.front_right_lock, self.rear_left_lock, self.rear_right_lock)

    @property
    def lock_left(self) -> float:
        """Over-Braking Left side (Max FL, RL)."""
        return max(self.front_left_lock, self.rear_left_lock)

    @property
    def lock_right(self) -> float:
        """Over-Braking Right side (Max FR, RR)."""
        return max(self.front_right_lock, self.rear_right_lock)

    @property
    def lock_front(self) -> float:
        """Over-Braking Front axle (Max FL, FR)."""
        return max(self.front_left_lock, self.front_right_lock)

    @property
    def lock_rear(self) -> float:
        """Over-Braking Rear axle (Max RL, RR)."""
        return max(self.rear_left_lock, self.rear_right_lock)

    @property
    def spin_intensity(self) -> float:
        """Over-Acceleration intensity (Combined Max RL/RR)."""
        return max(self.rear_left_spin, self.rear_right_spin)

    @property
    def spin_left(self) -> float:
        """Over-Acceleration Left wheel (RL)."""
        return self.rear_left_spin

    @property
    def spin_right(self) -> float:
        """Over-Acceleration Right wheel (RR)."""
        return self.rear_right_spin

    @property
    def oversteer_intensity(self) -> float:
        """Oversteer intensity (Combined Max RL/RR)."""
        return max(self.rear_left_lat_slip, self.rear_right_lat_slip)

    @property
    def oversteer_left(self) -> float:
        """Oversteer Left wheel (RL)."""
        return self.rear_left_lat_slip

    @property
    def oversteer_right(self) -> float:
        """Oversteer Right wheel (RR)."""
        return self.rear_right_lat_slip

    @property
    def understeer_intensity(self) -> float:
        """Understeer intensity (Combined Max FL/FR)."""
        return max(self.front_left_lat_slip, self.front_right_lat_slip)

    @property
    def understeer_left(self) -> float:
        """Understeer Left wheel (FL)."""
        return self.front_left_lat_slip

    @property
    def understeer_right(self) -> float:
        """Understeer Right wheel (FR)."""
        return self.front_right_lat_slip

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
        Sur-régime / Upshift Warning Intensity (0.0 to 1.0).
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
        Sous-régime / Downshift Warning Intensity (0.0 to 1.0).
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
        return max(self.front_left_travel, self.front_right_travel, self.rear_left_travel, self.rear_right_travel)

    @property
    def travel_left(self) -> float:
        """Wheel Travel Left side (Max FL, RL)."""
        return max(self.front_left_travel, self.rear_left_travel)

    @property
    def travel_right(self) -> float:
        """Wheel Travel Right side (Max FR, RR)."""
        return max(self.front_right_travel, self.rear_right_travel)

    # ── Grip Fraction Properties (0.0 to 1.0) ──────────────────────────────────
    @property
    def grip_intensity(self) -> float:
        """Unified 4-wheel Grip Fraction (min of FL, FR, RL, RR clamped [0.0, 1.0])."""
        val = min(self.front_left_grip, self.front_right_grip, self.rear_left_grip, self.rear_right_grip)
        return min(1.0, max(0.0, val))

    @property
    def grip_left(self) -> float:
        """Grip Fraction Left side (min of FL, RL clamped [0.0, 1.0])."""
        val = min(self.front_left_grip, self.rear_left_grip)
        return min(1.0, max(0.0, val))

    @property
    def grip_right(self) -> float:
        """Grip Fraction Right side (min of FR, RR clamped [0.0, 1.0])."""
        val = min(self.front_right_grip, self.rear_right_grip)
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



