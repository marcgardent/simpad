"""
SimPad Physics — Haptic Processor using Normalized VehicleSensors.
Converts normalized wheel slip ratios into 4 haptic vibration channels.
"""

from typing import Dict, Optional, Tuple, Union
from ..math_utils import apply_response_curve, clamp
from ..telemetry.sensors import VehicleSensors
from ..telemetry.lmu_parser import TelemetryData

# TODO: [DRY] Import unified apply_response_curve from src.core.math_utils instead of duplicating math definitions across physics and GUI modules.


# TODO: [SRP] PhysicsToHaptic should focus strictly on mapping telemetry signals to vibration levels, delegating configuration defaults and math utility functions to dedicated schemas/modules.
class PhysicsToHaptic:
    """
    Physics processor converting VehicleSensors inputs into haptic intensities.
    Handles 4 configurable physical effects with distinct response curves (Low and High):
      1. Wheel lock (Braking / ABS)
      2. Oversteer (Rear lateral slide)
      3. Understeer (Front lateral slide)
      4. Wheel spin (Acceleration / TC)
    """

    def __init__(self, config: Optional[Dict[str, float]] = None):
        self.config = config or self.get_default_config()

    @staticmethod
    def get_default_config() -> Dict[str, float]:
        return {
            # 1. Braking / Wheel lock (ABS) — Threshold at 15%
            "lock_threshold": 0.15,
            "lock_low_gamma": 1.0, "lock_low_gain": 0.3, "lock_low_cutoff": 0.0,
            "lock_high_gamma": 1.5, "lock_high_gain": 1.0, "lock_high_cutoff": 0.0,

            # 2. Oversteer / Rear slip — Threshold at 12%
            "oversteer_threshold": 0.12,
            "oversteer_low_gamma": 1.2, "oversteer_low_gain": 1.0, "oversteer_low_cutoff": 0.0,
            "oversteer_high_gamma": 1.0, "oversteer_high_gain": 0.4, "oversteer_high_cutoff": 0.0,

            # 3. Understeer / Front slip — Threshold at 10%
            "understeer_threshold": 0.10,
            "understeer_low_gamma": 1.5, "understeer_low_gain": 0.5, "understeer_low_cutoff": 0.0,
            "understeer_high_gamma": 1.0, "understeer_high_gain": 0.8, "understeer_high_cutoff": 0.0,

            # 4. Wheel spin (TC / Acceleration) — Threshold at 18%
            "spin_threshold": 0.18,
            "spin_low_gamma": 1.0, "spin_low_gain": 1.0, "spin_low_cutoff": 0.0,
            "spin_high_gamma": 2.0, "spin_high_gain": 0.2, "spin_high_cutoff": 0.0,
        }

    def update_config(self, new_config: Dict[str, float]) -> None:
        self.config.update(new_config)

    # TODO: [SLAP] Keep process() at a single high level of abstraction: extract signals -> compute effect intensities -> mix channels.
    def process(self, telemetry: Union[VehicleSensors, TelemetryData]) -> Tuple[float, float, float, float]:
        """
        Computes vibration intensities (left_low, left_high, right_low, right_high)
        from VehicleSensors domain signals.
        """
        sensors = telemetry.to_sensors() if isinstance(telemetry, TelemetryData) else telemetry

        # Level 1: Calculate raw effect slip levels
        lock_l, lock_r = self._calc_raw_slip(sensors.lock_left, sensors.lock_right, "lock")
        over_l, over_r = self._calc_raw_slip(sensors.rear_left_lat_slip, sensors.rear_right_lat_slip, "oversteer")
        under_l, under_r = self._calc_raw_slip(sensors.front_left_lat_slip, sensors.front_right_lat_slip, "understeer")
        spin_l, spin_r = self._calc_raw_slip(sensors.rear_left_spin, sensors.rear_right_spin, "spin")

        # Level 2: Compute low/high haptic intensities for each wheel
        lock_g_low, lock_g_high, lock_d_low, lock_d_high = self._eval_effect_curves(lock_l, lock_r, "lock")
        over_g_low, over_g_high, over_d_low, over_d_high = self._eval_effect_curves(over_l, over_r, "oversteer")
        under_g_low, under_g_high, under_d_low, under_d_high = self._eval_effect_curves(under_l, under_r, "understeer")
        spin_g_low, spin_g_high, spin_d_low, spin_d_high = self._eval_effect_curves(spin_l, spin_r, "spin")

        # Level 3: Mix final multi-channel outputs using MAX combination
        return self._mix_channels(
            (lock_g_low, lock_g_high, lock_d_low, lock_d_high),
            (over_g_low, over_g_high, over_d_low, over_d_high),
            (under_g_low, under_g_high, under_d_low, under_d_high),
            (spin_g_low, spin_g_high, spin_d_low, spin_d_high)
        )

    # TODO: [DRY] Helper method to normalize slip values above threshold, eliminating 4x repeated boilerplate code.
    def _calc_raw_slip(self, left_val: float, right_val: float, effect_name: str) -> Tuple[float, float]:
        thresh = self.config.get(f"{effect_name}_threshold", 0.15)
        span = max(0.01, 1.0 - thresh)
        raw_l = max(0.0, left_val - thresh) / span if left_val > thresh else 0.0
        raw_r = max(0.0, right_val - thresh) / span if right_val > thresh else 0.0
        return raw_l, raw_r

    # TODO: [DRY] Helper method to apply response curves for both left/right wheels (Low & High channels), fixing previous copy-paste parameter bug.
    def _eval_effect_curves(self, raw_l: float, raw_r: float, effect_name: str) -> Tuple[float, float, float, float]:
        low_g = self.config.get(f"{effect_name}_low_gamma", 1.0)
        low_gain = self.config.get(f"{effect_name}_low_gain", 1.0)
        low_cut = self.config.get(f"{effect_name}_low_cutoff", 0.0)

        high_g = self.config.get(f"{effect_name}_high_gamma", 1.0)
        high_gain = self.config.get(f"{effect_name}_high_gain", 1.0)
        high_cut = self.config.get(f"{effect_name}_high_cutoff", 0.0)

        l_low = apply_response_curve(raw_l, low_g, low_gain, low_cut)
        l_high = apply_response_curve(raw_l, high_g, high_gain, high_cut)
        r_low = apply_response_curve(raw_r, low_g, low_gain, low_cut)
        r_high = apply_response_curve(raw_r, high_g, high_gain, high_cut)

        return l_low, l_high, r_low, r_high

    # TODO: [SLAP] Single function to mix channel signals cleanly.
    @staticmethod
    def _mix_channels(*effects_quads: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
        left_low = clamp(max(quad[0] for quad in effects_quads))
        left_high = clamp(max(quad[1] for quad in effects_quads))
        right_low = clamp(max(quad[2] for quad in effects_quads))
        right_high = clamp(max(quad[3] for quad in effects_quads))
        return left_low, left_high, right_low, right_high
