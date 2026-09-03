"""
SimPad Haptics — Base Haptic Subplugin Interface.
Provides standard lifecycle, parameter declarations, serialization, and evaluation hooks for haptic effects.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from src.engineer.params import RoleParam, BoolParam, FloatRangeParam, IntRangeParam, ChoiceParam
from src.haptics.models import HapticMotorOutput
from src.telemetry.sensors import VehicleSensors


class BaseHapticSubplugin(ABC):
    """
    Base class for modular Haptic Feedback subplugins.
    Each subplugin calculates its contribution to the XInput vibration rumble motors.
    """

    def __init__(
        self,
        subplugin_id: str,
        name: str,
        description: str = "",
        icon: str = "🏎️",
        enabled: bool = True,
        master_gain: float = 1.0,
    ):
        self.subplugin_id = subplugin_id
        self.name = name
        self.description = description
        self.icon = icon
        self.enabled = enabled
        self.master_gain = master_gain

        self._param_descriptors: Dict[str, RoleParam] = {}
        self._param_values: Dict[str, Any] = {}

        # Initialize default values from declared descriptors
        for p in self.get_declared_params():
            self._param_descriptors[p.name] = p
            self._param_values[p.name] = p.default

    @abstractmethod
    def evaluate(self, sensors: VehicleSensors, time_s: float) -> HapticMotorOutput:
        """
        Evaluates current vehicle telemetry and returns multichannel haptic motor intensities.

        :param sensors: Normalized vehicle sensor telemetry frame
        :param time_s: Current simulation timestamp in seconds (used for periodic waveforms)
        :return: HapticMotorOutput instance
        """
        raise NotImplementedError

    def get_declared_params(self) -> List[RoleParam]:
        """Returns the list of declarative parameter descriptors for UI tuning."""
        return []

    def get_param(self, name: str, fallback: Any = None) -> Any:
        """Retrieves the current validated value for a named parameter."""
        return self._param_values.get(name, fallback)

    def set_param(self, name: str, value: Any) -> None:
        """Sets and validates a parameter value."""
        descriptor = self._param_descriptors.get(name)
        if descriptor:
            self._param_values[name] = descriptor.cast_and_validate(value)
        else:
            self._param_values[name] = value

    def get_config_dict(self) -> Dict[str, Any]:
        """Serializes subplugin state and parameters to a dictionary."""
        return {
            "enabled": self.enabled,
            "master_gain": round(float(self.master_gain), 3),
            "params": dict(self._param_values),
        }

    def load_config_dict(self, cfg: Dict[str, Any]) -> None:
        """Restores subplugin state and parameters from configuration."""
        if not isinstance(cfg, dict):
            return

        if "enabled" in cfg:
            self.enabled = bool(cfg["enabled"])
        if "master_gain" in cfg:
            try:
                self.master_gain = max(0.0, min(5.0, float(cfg["master_gain"])))
            except (ValueError, TypeError):
                pass

        saved_params = cfg.get("params", {})
        if isinstance(saved_params, dict):
            for k, val in saved_params.items():
                self.set_param(k, val)
