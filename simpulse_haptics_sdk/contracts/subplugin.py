"""
SimPulse Haptics — Base Haptic Subplugin Contract.
Provides standard lifecycle, parameter declarations, serialization, and evaluation hooks for haptic effects.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Union, Any
from simpulse_sdk import RoleParam, ParamScalarValue, VehicleSensors
from ..models.output import HapticMotorOutput

HapticConfigValue = Union[bool, float, Dict[str, ParamScalarValue]]


class BaseHapticSubplugin(ABC):
    """
    Base contract for modular Haptic Feedback subplugins.
    Each subplugin calculates its contribution to the XInput vibration rumble motors.
    """

    def __init__(
        self,
        subplugin_id: str,
        name: str,
        description: str = "",
        icon: str = "🏎️",
    ):
        self.subplugin_id = subplugin_id
        self.name = name
        self.description = description
        self.icon = icon

        self._param_descriptors: Dict[str, RoleParam] = {}
        self._param_values: Dict[str, ParamScalarValue] = {}

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

    def get_param(self, name: str, fallback: Optional[ParamScalarValue] = None) -> Optional[ParamScalarValue]:
        """Retrieves the current validated value for a named parameter."""
        return self._param_values.get(name, fallback)

    def set_param(self, name: str, value: ParamScalarValue) -> None:
        """Sets and validates a parameter value."""
        descriptor = self._param_descriptors.get(name)
        if descriptor:
            self._param_values[name] = descriptor.cast_and_validate(value)
        else:
            self._param_values[name] = value

    def get_config_dict(self) -> Dict[str, ParamScalarValue]:
        """Serializes subplugin parameters to a dictionary."""
        return dict(self._param_values)

    def load_config_dict(self, cfg: Dict[str, Any]) -> None:
        """Restores subplugin parameters from configuration dictionary."""
        if not isinstance(cfg, dict):
            return

        saved_params = cfg.get("params", cfg) if isinstance(cfg.get("params"), dict) else cfg
        for k, val in saved_params.items():
            if k in self._param_descriptors or k in self._param_values:
                self.set_param(k, val)


IHapticSubplugin = BaseHapticSubplugin
