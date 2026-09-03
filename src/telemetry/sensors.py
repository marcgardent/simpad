"""
SimPad Telemetry — Normalized Vehicle Sensors Domain Abstraction.
Normalizes raw wheel velocities into dimensionless physical slip ratios (0.0 to 1.0).
Zero vibration while cruising; proportional vibration only on lock, spin, oversteer, or understeer.
"""

import math
from dataclasses import dataclass
from typing import Tuple, Optional, Any, Union

try:
    from isimotor_rawudp_client import TelemInfo, TelemWheel, CompactScoring, FullScoringSession
except ImportError:
    TelemInfo = Any  # type: ignore
    TelemWheel = Any  # type: ignore
    CompactScoring = Any  # type: ignore
    FullScoringSession = Any  # type: ignore


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

    # 3. Glissement latéral - Virage / Décrochage (FL, FR, RL, RR) [0.0 à 1.0]
    front_left_lat_slip: float = 0.0
    front_right_lat_slip: float = 0.0
    rear_left_lat_slip: float = 0.0
    rear_right_lat_slip: float = 0.0

    # 3b. Glissement latéral orienté Gauche (-1.0) / Droite (+1.0) pour jauge horizontale
    front_left_lat_signed: float = 0.0
    front_right_lat_signed: float = 0.0
    rear_left_lat_signed: float = 0.0
    rear_right_lat_signed: float = 0.0

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

    # Pédales non filtrées et filtrées (0.0 à 1.0)
    unfiltered_throttle: float = 0.0
    unfiltered_brake: float = 0.0
    filtered_throttle: Optional[float] = None
    filtered_brake: Optional[float] = None

    # Télémétrie de session, chrono et énergie
    fuel_level: float = 0.0
    remaining_laps: int = 0
    delta_time: float = 0.0
    estimated_lap_time: float = 0.0
    estimated_lap_time_str: str = "--:--.---"
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
    track_cut_state: Optional[Union[str, int]] = "green"
    has_delta_reference: bool = False
    is_pit_lap: bool = False
    last_lap_time: float = 0.0
    last_lap_time_str: str = "--:--.---"
    last_lap_status: str = "default"
    is_lap_freeze_active: bool = False

    # État en piste et rapport engagé
    in_realtime: bool = True
    gear: int = 0

    # 7. Données Électronique & Cockpit LMU (isiMotor-RawUDP v0.2.0)
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
        track_cut_state: Optional[Union[str, int]] = "green",
        has_delta_reference: bool = False,
        is_pit_lap: bool = False,
        last_lap_time: float = 0.0,
        last_lap_time_str: str = "--:--.---",
        last_lap_status: str = "default",
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
    ) -> "VehicleSensors":

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

    @classmethod
    def from_telem_info(
        cls,
        telem: "TelemInfo",
        scoring: Optional[Any] = None,
        delta_time: float = 0.0,
        estimated_lap_time: float = 0.0,
        estimated_lap_time_str: str = "--:--.---",
        sector1_time: str = "--",
        sector1_status: str = "default",
        sector2_time: str = "--",
        sector2_status: str = "default",
        sector3_time: str = "--",
        sector3_status: str = "default",
        explicit_aero_load: Optional[float] = None,
        current_sector: int = 1,
        sector1_delta: float = 0.0,
        sector2_delta: float = 0.0,
        sector3_delta: float = 0.0,
        lap_flag: int = 2,
        track_cut_state: Optional[Union[str, int]] = "green",
        has_delta_reference: bool = False,
        is_pit_lap: bool = False,
        last_lap_time: float = 0.0,
        last_lap_time_str: str = "--:--.---",
        last_lap_status: str = "default",
        is_lap_freeze_active: bool = False,
        in_realtime: bool = True,
    ) -> "VehicleSensors":
        """Instancie un objet VehicleSensors directement depuis un paquet binaire TelemInfo de isimotor_rawudp_client."""
        wheels = getattr(telem, "wheels", ())
        if wheels and len(wheels) >= 4:
            lpv = tuple(float(w.longitudinal_patch_vel) for w in wheels[:4])
            lgv = tuple(float(w.longitudinal_ground_vel) for w in wheels[:4])
            lat_pv = tuple(float(w.lateral_patch_vel) for w in wheels[:4])
            lat_gv = tuple(float(w.lateral_ground_vel) for w in wheels[:4])
            raw_deflections = tuple(float(getattr(w, "suspension_deflection", 0.0)) for w in wheels[:4])
            travels = tuple(min(1.0, max(0.0, d / 0.10)) for d in raw_deflections)
            raw_grips = tuple(float(getattr(w, "grip_fraction", 1.0)) for w in wheels[:4])
            raw_bpres = tuple(float(getattr(w, "brake_pressure", 0.0)) for w in wheels[:4])
        else:
            lpv = (0.0, 0.0, 0.0, 0.0)
            lgv = (0.0, 0.0, 0.0, 0.0)
            lat_pv = (0.0, 0.0, 0.0, 0.0)
            lat_gv = (0.0, 0.0, 0.0, 0.0)
            travels = (0.0, 0.0, 0.0, 0.0)
            raw_grips = (1.0, 1.0, 1.0, 1.0)
            raw_bpres = (0.0, 0.0, 0.0, 0.0)

        if explicit_aero_load is None:
            f_df = abs(float(getattr(telem, "front_downforce", 0.0)))
            r_df = abs(float(getattr(telem, "rear_downforce", 0.0)))
            aero_downforce = min(100.0, (f_df + r_df) / 50.0)
        else:
            aero_downforce = explicit_aero_load

        remaining_laps = 0
        if scoring is not None:
            if hasattr(scoring, "max_laps") and hasattr(scoring, "total_laps"):
                if 0 < scoring.max_laps < 1000:
                    remaining_laps = max(0, scoring.max_laps - scoring.total_laps)
            elif isinstance(scoring, dict):
                max_laps = int(scoring.get("mMaxLaps", scoring.get("maxLaps", 0)))
                total_laps = int(scoring.get("mTotalLaps", scoring.get("totalLaps", 0)))
                if 0 < max_laps < 1000:
                    remaining_laps = max(0, max_laps - total_laps)

        engine_rpm = float(getattr(telem, "engine_rpm", 0.0))
        engine_max_rpm = float(getattr(telem, "engine_max_rpm", 7500.0))
        gear = int(getattr(telem, "gear", 0))
        unfiltered_throttle = float(getattr(telem, "unfiltered_throttle", 0.0))
        unfiltered_brake = float(getattr(telem, "unfiltered_brake", 0.0))
        filtered_throttle = float(getattr(telem, "filtered_throttle", unfiltered_throttle))
        filtered_brake = float(getattr(telem, "filtered_brake", unfiltered_brake))
        fuel_level = float(getattr(telem, "fuel", 0.0))

        # Extract ECU & Cockpit state from isimotor-rawudp v0.2.0
        ecu = getattr(telem, "ecu", None)
        if ecu is None and hasattr(telem, "lmu") and getattr(telem, "lmu", None):
            ecu = getattr(telem.lmu, "ecu", None)

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

        if ecu is not None:
            ecu_abs_raw = bool(getattr(ecu, "abs_active", False))
            ecu_tc_raw = bool(getattr(ecu, "tc_active", False))
            ecu_abs_level = max(0, int(getattr(ecu, "abs_level", 0)))
            ecu_abs_max = max(0, int(getattr(ecu, "abs_max", 0)))
            ecu_tc_level = max(0, int(getattr(ecu, "tc_level", 0)))
            ecu_tc_max = max(0, int(getattr(ecu, "tc_max", 0)))
            ecu_tc_cut = max(0, int(getattr(ecu, "tc_cut", 0)))
            ecu_tc_cut_max = max(0, int(getattr(ecu, "tc_cut_max", 0)))
            ecu_tc_slip = max(0, int(getattr(ecu, "tc_slip", 0)))
            ecu_tc_slip_max = max(0, int(getattr(ecu, "tc_slip_max", 0)))
            ecu_motor_map = max(0, int(getattr(ecu, "motor_map", 0)))
            ecu_motor_map_max = max(0, int(getattr(ecu, "motor_map_max", 0)))
            ecu_brake_migration = max(0, int(getattr(ecu, "brake_migration", 0)))
            ecu_brake_migration_max = max(0, int(getattr(ecu, "brake_migration_max", 0)))
            ecu_front_arb = max(0, int(getattr(ecu, "front_arb", 0)))
            ecu_front_arb_max = max(0, int(getattr(ecu, "front_arb_max", 0)))
            ecu_rear_arb = max(0, int(getattr(ecu, "rear_arb", 0)))
            ecu_rear_arb_max = max(0, int(getattr(ecu, "rear_arb_max", 0)))
            ecu_wiper_state = int(getattr(ecu, "wiper_state", 0))
            ecu_lift_and_coast = float(getattr(ecu, "lift_and_coast", 0.0))

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
            vehicle_speed=float(getattr(telem, "speed_mps", 0.0)),
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
        )

    # ── Timing, Sector & Aero Properties ──────────────────────────────────────
    @property
    def delta_time_str(self) -> str:
        """Chrono Delta formaté (ex: '-0.150' ou '+0.240')."""
        if not self.has_delta_reference or self.lap_flag != 2 or self.is_pit_lap or not self.in_realtime:
            return "--"
        if self.delta_time < -0.0001:
            return f"-{abs(self.delta_time):.3f}"
        elif self.delta_time > 0.0001:
            return f"+{self.delta_time:.3f}"
        return "+0.000"

    def sector_delta_str(self, sector_num: int) -> str:
        """Delta Live formaté d'un secteur actif (ex: '-0.150' ou '+0.240')."""
        val = getattr(self, f"sector{sector_num}_delta", 0.0)
        if val < 0.0:
            return f"-{abs(val):.3f}"
        elif val > 0.0:
            return f"+{val:.3f}"
        elif val == 0.0 and (self.delta_time != 0.0 or self.sector1_time != "--" or self.sector1_delta != 0.0 or self.sector2_delta != 0.0 or self.sector3_delta != 0.0):
            return "+0.000"
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

    # ── High-Level Haptic Sensor Aggregations ─────────────────────────────────
    @property
    def lock_intensity(self) -> float:
        """Over-Braking intensity (Combined Max 4 wheels)."""
        if self.vehicle_speed <= 1.5:
            return 0.0
        return max(self.front_left_lock, self.front_right_lock, self.rear_left_lock, self.rear_right_lock)

    @property
    def lock_left(self) -> float:
        """Over-Braking Left side (Max FL, RL)."""
        if self.vehicle_speed <= 1.5:
            return 0.0
        return max(self.front_left_lock, self.rear_left_lock)

    @property
    def lock_right(self) -> float:
        """Over-Braking Right side (Max FR, RR)."""
        if self.vehicle_speed <= 1.5:
            return 0.0
        return max(self.front_right_lock, self.rear_right_lock)

    @property
    def lock_front(self) -> float:
        """Over-Braking Front axle (Max FL, FR)."""
        if self.vehicle_speed <= 1.5:
            return 0.0
        return max(self.front_left_lock, self.front_right_lock)

    @property
    def lock_rear(self) -> float:
        """Over-Braking Rear axle (Max RL, RR)."""
        if self.vehicle_speed <= 1.5:
            return 0.0
        return max(self.rear_left_lock, self.rear_right_lock)

    @property
    def spin_intensity(self) -> float:
        """Over-Acceleration intensity (Combined Max RL/RR)."""
        if self.vehicle_speed <= 1.5:
            return 0.0
        return max(self.rear_left_spin, self.rear_right_spin)

    @property
    def spin_left(self) -> float:
        """Over-Acceleration Left wheel (RL)."""
        if self.vehicle_speed <= 1.5:
            return 0.0
        return self.rear_left_spin

    @property
    def spin_right(self) -> float:
        """Over-Acceleration Right wheel (RR)."""
        if self.vehicle_speed <= 1.5:
            return 0.0
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

    # ── Official Car Electronic Aids (ECU ABS & Traction Control) ─────────────
    @property
    def ecu_abs_active(self) -> float:
        """
        Official Car ECU ABS Active Intervention Intensity (0.0 to 1.0).
        Strictly zero at standstill or speed <= 1.5 m/s, or when ABS is disabled (level 0).
        """
        if not self.in_realtime or self.vehicle_speed <= 1.5:
            return 0.0
        if self.ecu_abs_active_raw is True:
            return 1.0
        # If ABS is explicitly disabled at level 0 on an ABS-equipped car, return 0.0
        if self.ecu_abs_level == 0 and self.ecu_abs_max > 0:
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
        if self.ecu_tc_active_raw is True:
            return 1.0
        # If TC is explicitly disabled at level 0 on a TC-equipped car, return 0.0
        if self.ecu_tc_level == 0 and self.ecu_tc_max > 0:
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




