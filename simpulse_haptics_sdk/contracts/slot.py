"""
SimPulse Haptics — Haptic Host Slot Contract.
Encapsulates host-side activation state (enabled), effect intensity (master_gain),
and evaluation dispatch for a single BaseHapticSubplugin.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any
from simpulse_sdk import VehicleSensors
from .subplugin import BaseHapticSubplugin
from ..models.output import HapticMotorOutput


@dataclass
class HapticHostSlot:
    """
    Host-side slot managing activation state, master gain scaling, and configuration
    serialization for a single Haptic Subplugin instance.
    """
    subplugin: BaseHapticSubplugin
    enabled: bool = True
    master_gain: float = 1.0

    @property
    def subplugin_id(self) -> str:
        return self.subplugin.subplugin_id

    def evaluate(self, sensors: VehicleSensors, time_s: float) -> HapticMotorOutput:
        """
        Evaluates the subplugin if enabled and gain is above threshold,
        applying master_gain scaling to the result.
        """
        if not self.enabled or self.master_gain <= 0.001:
            return HapticMotorOutput()

        out = self.subplugin.evaluate(sensors, time_s)
        if abs(self.master_gain - 1.0) > 0.0001:
            return out.scaled(self.master_gain)
        return out

    def get_config_dict(self) -> Dict[str, Any]:
        """Serializes slot activation state, gain, and subplugin parameters."""
        return {
            "enabled": self.enabled,
            "master_gain": round(float(self.master_gain), 3),
            "params": self.subplugin.get_config_dict(),
        }

    def load_config_dict(self, cfg: Dict[str, Any]) -> None:
        """Restores slot activation state, gain, and subplugin parameters from dictionary."""
        if not isinstance(cfg, dict):
            return

        if "enabled" in cfg:
            self.enabled = bool(cfg["enabled"])

        if "master_gain" in cfg:
            try:
                self.master_gain = max(0.0, min(5.0, float(cfg["master_gain"])))
            except (ValueError, TypeError):
                pass

        params_cfg = cfg.get("params")
        if isinstance(params_cfg, dict):
            self.subplugin.load_config_dict(params_cfg)
        else:
            self.subplugin.load_config_dict(cfg)


SubpluginHostSlot = HapticHostSlot
