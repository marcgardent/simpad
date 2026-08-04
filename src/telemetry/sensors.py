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

    # Vitesse du véhicule (m/s)
    vehicle_speed: float = 0.0

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
    ) -> "VehicleSensors":
        locks = []
        spins = []
        lats = []

        avg_speed = sum(abs(v) for v in long_ground_vels) / 4.0

        for i in range(4):
            lpv = float(long_patch_vels[i])
            lgv = float(long_ground_vels[i]) if i < len(long_ground_vels) else 0.0
            lat_pv = float(lat_patch_vels[i]) if i < len(lat_patch_vels) else 0.0

            speed = abs(lgv)
            if speed > 0.5:
                # Dimenssionless relative slip ratio
                long_slip = (lpv - lgv) / speed
                lat_slip = abs(lat_pv) / speed
            else:
                # Low-speed / simulated synthetic velocity magnitude
                if lgv == 0.0 and lpv != 0.0:
                    lock_val = abs(lpv) if i < 2 else max(0.0, -lpv)
                    spin_val = abs(lpv) if i >= 2 else max(0.0, lpv)
                else:
                    long_slip = math.copysign(min(1.0, abs(lpv - lgv)), lpv - lgv)
                    lock_val = max(0.0, -long_slip)
                    spin_val = max(0.0, long_slip)
                lat_slip = min(1.0, abs(lat_pv))

            locks.append(min(1.0, max(0.0, lock_val)))
            spins.append(min(1.0, max(0.0, spin_val)))
            lats.append(min(1.0, max(0.0, lat_slip)))

        travels = [min(1.0, max(0.0, float(st))) for st in suspension_travels[:4]]
        if len(travels) < 4:
            travels.extend([0.0] * (4 - len(travels)))

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
            vehicle_speed=avg_speed,
        )

    # ── Combined & Per-Side Sensor Intensity Properties (0.0 to 1.0) ──────────
    @property
    def lock_intensity(self) -> float:
        """Over-Braking intensity (Combined Max FL/FR)."""
        return max(self.front_left_lock, self.front_right_lock)

    @property
    def lock_left(self) -> float:
        """Over-Braking Left wheel (FL)."""
        return self.front_left_lock

    @property
    def lock_right(self) -> float:
        """Over-Braking Right wheel (FR)."""
        return self.front_right_lock

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
        """
        r = self.rpm_ratio
        if r <= 0.90:
            return 0.0
        return min(1.0, max(0.0, (r - 0.90) / 0.10))

    @property
    def underrev_intensity(self) -> float:
        """
        Sous-régime / Downshift Warning Intensity (0.0 to 1.0).
        Ramps up from 0.0 at 45% RPM max down to 1.0 at 20% (Idle / Downshift sweet spot).
        """
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

