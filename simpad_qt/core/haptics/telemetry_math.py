"""
SimPad Haptics — Telemetry Signal Math & Physics Calculations.
Extracts and computes physical vehicle telemetry signals (ABS, TC, Oversteer,
Understeer, Engine Regime, Curbs/Travel, Tire Grip) to drive haptic effects.
"""

from __future__ import annotations
from typing import Tuple, Dict, Any
from .math_engine import clamp
from ..telemetry.sensors import VehicleSensors


def calc_abs_lockup(sensors: VehicleSensors, prefer_ecu: bool = True) -> Tuple[float, float, float]:
    """
    Calculates front/rear wheel lockup intensity and ECU ABS intervention.

    :param sensors: Normalized vehicle telemetry state
    :param prefer_ecu: If True, incorporates ECU ABS active flag
    :return: (left_lockup, right_lockup, combined_max_lockup) in [0.0, 1.0]
    """
    ecu_active = sensors.ecu_abs_active if prefer_ecu else 0.0
    left_lock = max(sensors.lock_left, ecu_active)
    right_lock = max(sensors.lock_right, ecu_active)
    comb_lock = max(sensors.lock_intensity, ecu_active)
    return clamp(left_lock), clamp(right_lock), clamp(comb_lock)


def calc_tc_wheelspin(sensors: VehicleSensors, prefer_ecu: bool = True) -> Tuple[float, float, float]:
    """
    Calculates rear wheel power spin intensity and ECU TC intervention.

    :param sensors: Normalized vehicle telemetry state
    :param prefer_ecu: If True, incorporates ECU Traction Control active flag
    :return: (left_spin, right_spin, combined_max_spin) in [0.0, 1.0]
    """
    ecu_active = sensors.ecu_tc_active if prefer_ecu else 0.0
    left_spin = max(sensors.spin_left, ecu_active)
    right_spin = max(sensors.spin_right, ecu_active)
    comb_spin = max(sensors.spin_intensity, ecu_active)
    return clamp(left_spin), clamp(right_spin), clamp(comb_spin)


def calc_oversteer_slip(sensors: VehicleSensors) -> Tuple[float, float, float]:
    """
    Calculates rear axle lateral slip (Oversteer).

    :return: (left_slip, right_slip, combined_max_oversteer) in [0.0, 1.0]
    """
    return (
        clamp(sensors.oversteer_left),
        clamp(sensors.oversteer_right),
        clamp(sensors.oversteer_intensity),
    )


def calc_understeer_scrub(sensors: VehicleSensors) -> Tuple[float, float, float]:
    """
    Calculates front axle lateral slip (Understeer / Front scrub).

    :return: (left_scrub, right_scrub, combined_max_understeer) in [0.0, 1.0]
    """
    return (
        clamp(sensors.understeer_left),
        clamp(sensors.understeer_right),
        clamp(sensors.understeer_intensity),
    )


def calc_engine_rev_state(
    sensors: VehicleSensors,
    upshift_rpm_pct: float = 0.90,
    downshift_rpm_pct: float = 0.45
) -> Dict[str, float]:
    """
    Calculates engine regime indicators (RPM ratio, Over-rev warning, Under-rev warning).

    :param sensors: Normalized vehicle telemetry state
    :param upshift_rpm_pct: Threshold RPM ratio where over-rev intensity begins ramping up
    :param downshift_rpm_pct: Threshold RPM ratio where under-rev intensity begins ramping up
    :return: Dictionary containing rpm_ratio, over_rev, under_rev, rpm, gear
    """
    rpm_ratio = sensors.rpm_ratio
    gear = float(sensors.gear)

    if gear == 0:  # Neutral
        over_rev = 0.0
        under_rev = 0.0
    else:
        # Over-rev (Upshift indicator / Redline)
        if rpm_ratio > upshift_rpm_pct:
            over_rev = clamp((rpm_ratio - upshift_rpm_pct) / max(0.01, 1.0 - upshift_rpm_pct))
        else:
            over_rev = 0.0

        # Under-rev (Downshift / Stall warning)
        if rpm_ratio < downshift_rpm_pct and rpm_ratio > 0.01:
            under_rev = clamp((downshift_rpm_pct - rpm_ratio) / max(0.01, downshift_rpm_pct - 0.20))
        else:
            under_rev = 0.0

    return {
        "rpm_ratio": clamp(rpm_ratio),
        "over_rev": clamp(over_rev),
        "under_rev": clamp(under_rev),
        "rpm": float(sensors.engine_rpm),
        "gear": gear,
    }


def calc_wheel_travel_impacts(sensors: VehicleSensors) -> Dict[str, float]:
    """
    Calculates wheel suspension compression & curb impacts for left/right sides.

    :return: Dictionary with travel_fl, travel_fr, travel_rl, travel_rr, travel_l, travel_r, travel_max
    """
    return {
        "travel_fl": clamp(sensors.front_left_travel),
        "travel_fr": clamp(sensors.front_right_travel),
        "travel_rl": clamp(sensors.rear_left_travel),
        "travel_rr": clamp(sensors.rear_right_travel),
        "travel_left": clamp(sensors.travel_left),
        "travel_right": clamp(sensors.travel_right),
        "travel_max": clamp(sensors.travel_intensity),
    }


def calc_tire_grip_loss(sensors: VehicleSensors) -> Dict[str, float]:
    """
    Calculates tire grip fraction and inverted grip loss (0.0 = full grip, 1.0 = zero grip).

    :return: Dictionary with grip_fraction, grip_loss_max, grip_loss_left, grip_loss_right
    """
    grip_l = clamp(sensors.grip_left)
    grip_r = clamp(sensors.grip_right)
    grip_min = clamp(sensors.grip_intensity)

    return {
        "grip_fraction": grip_min,
        "grip_loss_max": clamp(1.0 - grip_min),
        "grip_loss_left": clamp(1.0 - grip_l),
        "grip_loss_right": clamp(1.0 - grip_r),
    }


def calc_ecu_electronics(sensors: VehicleSensors) -> Dict[str, float]:
    """
    Calculates official car ECU electronics active levels (ABS & TC).

    :return: Dictionary with ecu_abs, ecu_tc
    """
    return {
        "ecu_abs": clamp(sensors.ecu_abs_active),
        "ecu_tc": clamp(sensors.ecu_tc_active),
    }
