"""
SimPad Physics — Haptic Processor using Normalized VehicleSensors.
Converts normalized wheel slip ratios into 4 haptic vibration channels.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, Union
from ..math_utils import apply_response_curve, clamp
from ..telemetry.sensors import VehicleSensors
from ..telemetry.lmu_parser import TelemetryData


@dataclass
class HapticChannelCurve:
    """Response curve parameters for a single haptic channel (Low or High)."""
    gamma: float = 1.0
    gain: float = 1.0
    cutoff: float = 0.0


@dataclass
class HapticEffectConfig:
    """Configuration parameters for a single slip effect."""
    threshold: float = 0.15
    low: HapticChannelCurve = field(default_factory=HapticChannelCurve)
    high: HapticChannelCurve = field(default_factory=HapticChannelCurve)


@dataclass
class PhysicsHapticConfig:
    """Strongly-typed 4-effect haptic processor configuration."""
    lock: HapticEffectConfig = field(default_factory=lambda: HapticEffectConfig(
        threshold=0.15,
        low=HapticChannelCurve(gamma=1.0, gain=0.3, cutoff=0.0),
        high=HapticChannelCurve(gamma=1.5, gain=1.0, cutoff=0.0),
    ))
    oversteer: HapticEffectConfig = field(default_factory=lambda: HapticEffectConfig(
        threshold=0.12,
        low=HapticChannelCurve(gamma=1.2, gain=1.0, cutoff=0.0),
        high=HapticChannelCurve(gamma=1.0, gain=0.4, cutoff=0.0),
    ))
    understeer: HapticEffectConfig = field(default_factory=lambda: HapticEffectConfig(
        threshold=0.10,
        low=HapticChannelCurve(gamma=1.5, gain=0.5, cutoff=0.0),
        high=HapticChannelCurve(gamma=1.0, gain=0.8, cutoff=0.0),
    ))
    spin: HapticEffectConfig = field(default_factory=lambda: HapticEffectConfig(
        threshold=0.18,
        low=HapticChannelCurve(gamma=1.0, gain=1.0, cutoff=0.0),
        high=HapticChannelCurve(gamma=2.0, gain=0.2, cutoff=0.0),
    ))

    @classmethod
    def from_dict(cls, d: Dict[str, float]) -> "PhysicsHapticConfig":
        cfg = cls()
        effects = {
            "lock": cfg.lock,
            "oversteer": cfg.oversteer,
            "understeer": cfg.understeer,
            "spin": cfg.spin,
        }
        for name, eff in effects.items():
            if f"{name}_threshold" in d:
                eff.threshold = float(d[f"{name}_threshold"])
            if f"{name}_low_gamma" in d:
                eff.low.gamma = float(d[f"{name}_low_gamma"])
            if f"{name}_low_gain" in d:
                eff.low.gain = float(d[f"{name}_low_gain"])
            if f"{name}_low_cutoff" in d:
                eff.low.cutoff = float(d[f"{name}_low_cutoff"])
            if f"{name}_high_gamma" in d:
                eff.high.gamma = float(d[f"{name}_high_gamma"])
            if f"{name}_high_gain" in d:
                eff.high.gain = float(d[f"{name}_high_gain"])
            if f"{name}_high_cutoff" in d:
                eff.high.cutoff = float(d[f"{name}_high_cutoff"])
        return cfg


class PhysicsToHaptic:
    """
    Physics processor converting VehicleSensors inputs into haptic intensities.
    Handles 4 configurable physical effects with distinct response curves (Low and High):
      1. Wheel lock (Braking / ABS)
      2. Oversteer (Rear lateral slide)
      3. Understeer (Front lateral slide)
      4. Wheel spin (Acceleration / TC)
    """

    def __init__(self, config: Optional[Union[PhysicsHapticConfig, Dict[str, float]]] = None):
        if config is None:
            self.typed_config = PhysicsHapticConfig()
        elif isinstance(config, PhysicsHapticConfig):
            self.typed_config = config
        else:
            self.typed_config = PhysicsHapticConfig.from_dict(config)
        self.config = config if isinstance(config, dict) else self.get_default_config()

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

    def update_config(self, new_config: Union[PhysicsHapticConfig, Dict[str, float]]) -> None:
        if isinstance(new_config, PhysicsHapticConfig):
            self.typed_config = new_config
        else:
            self.config.update(new_config)
            self.typed_config = PhysicsHapticConfig.from_dict(self.config)

    def process(self, telemetry: Union[VehicleSensors, TelemetryData]) -> Tuple[float, float, float, float]:
        """
        Computes vibration intensities (left_low, left_high, right_low, right_high)
        from VehicleSensors domain signals.
        """
        sensors = telemetry.to_sensors() if isinstance(telemetry, TelemetryData) else telemetry

        # Level 1: Calculate raw effect slip levels
        lock_l, lock_r = self._calc_raw_slip(sensors.lock_left, sensors.lock_right, self.typed_config.lock)
        over_l, over_r = self._calc_raw_slip(sensors.rear_left_lat_slip, sensors.rear_right_lat_slip, self.typed_config.oversteer)
        under_l, under_r = self._calc_raw_slip(sensors.front_left_lat_slip, sensors.front_right_lat_slip, self.typed_config.understeer)
        spin_l, spin_r = self._calc_raw_slip(sensors.rear_left_spin, sensors.rear_right_spin, self.typed_config.spin)

        # Level 2: Compute low/high haptic intensities for each wheel
        lock_g_low, lock_g_high, lock_d_low, lock_d_high = self._eval_effect_curves(lock_l, lock_r, self.typed_config.lock)
        over_g_low, over_g_high, over_d_low, over_d_high = self._eval_effect_curves(over_l, over_r, self.typed_config.oversteer)
        under_g_low, under_g_high, under_d_low, under_d_high = self._eval_effect_curves(under_l, under_r, self.typed_config.understeer)
        spin_g_low, spin_g_high, spin_d_low, spin_d_high = self._eval_effect_curves(spin_l, spin_r, self.typed_config.spin)

        # Level 3: Mix final multi-channel outputs using MAX combination
        return self._mix_channels(
            (lock_g_low, lock_g_high, lock_d_low, lock_d_high),
            (over_g_low, over_g_high, over_d_low, over_d_high),
            (under_g_low, under_g_high, under_d_low, under_d_high),
            (spin_g_low, spin_g_high, spin_d_low, spin_d_high)
        )

    def _calc_raw_slip(self, left_val: float, right_val: float, effect_cfg: HapticEffectConfig) -> Tuple[float, float]:
        thresh = effect_cfg.threshold
        span = max(0.01, 1.0 - thresh)
        raw_l = max(0.0, left_val - thresh) / span if left_val > thresh else 0.0
        raw_r = max(0.0, right_val - thresh) / span if right_val > thresh else 0.0
        return raw_l, raw_r

    def _eval_effect_curves(self, raw_l: float, raw_r: float, effect_cfg: HapticEffectConfig) -> Tuple[float, float, float, float]:
        l_low = apply_response_curve(raw_l, effect_cfg.low.gamma, effect_cfg.low.gain, effect_cfg.low.cutoff)
        l_high = apply_response_curve(raw_l, effect_cfg.high.gamma, effect_cfg.high.gain, effect_cfg.high.cutoff)
        r_low = apply_response_curve(raw_r, effect_cfg.low.gamma, effect_cfg.low.gain, effect_cfg.low.cutoff)
        r_high = apply_response_curve(raw_r, effect_cfg.high.gamma, effect_cfg.high.gain, effect_cfg.high.cutoff)
        return l_low, l_high, r_low, r_high

    # TODO: [SLAP] Single function to mix channel signals cleanly.
    @staticmethod
    def _mix_channels(*effects_quads: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
        left_low = clamp(max(quad[0] for quad in effects_quads))
        left_high = clamp(max(quad[1] for quad in effects_quads))
        right_low = clamp(max(quad[2] for quad in effects_quads))
        right_high = clamp(max(quad[3] for quad in effects_quads))
        return left_low, left_high, right_low, right_high
