"""
SimPad Race Engineer — Declarative Configurable Parameters for Roles.
Provides type descriptors for role parameters (BoolParam, IntRangeParam, FloatRangeParam, ChoiceParam).
SOLID architecture (SRP, OCP, LSP).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, Dict, List


@dataclass
class RoleParam(ABC):
    """
    Abstract descriptor of a configurable role parameter.
    Each parameter has a unique identifier (name), a display label (label),
    a description (description), and a default value.
    """
    name: str
    label: str
    description: str = ""
    default: Any = None

    @abstractmethod
    def cast_and_validate(self, value: Any) -> Any:
        """Converts and clamps value according to descriptor constraints."""
        pass


@dataclass
class BoolParam(RoleParam):
    """Boolean parameter (rendered as a Checkbox in UI)."""
    default: bool = True

    def cast_and_validate(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)


@dataclass
class IntRangeParam(RoleParam):
    """Integer parameter with bounded range (min, max, step, unit) for slider/stepper."""
    min_val: int = 0
    max_val: int = 100
    step: int = 1
    unit: str = ""
    default: int = 0

    def cast_and_validate(self, value: Any) -> int:
        try:
            val_int = int(round(float(value)))
            return max(self.min_val, min(self.max_val, val_int))
        except (ValueError, TypeError):
            return self.default


@dataclass
class FloatRangeParam(RoleParam):
    """Float parameter with bounded range (min, max, step, unit) for slider/stepper."""
    min_val: float = 0.0
    max_val: float = 100.0
    step: float = 0.1
    unit: str = ""
    default: float = 0.0

    def cast_and_validate(self, value: Any) -> float:
        try:
            val_flt = float(value)
            val_rounded = round(val_flt, 3)
            return max(self.min_val, min(self.max_val, val_rounded))
        except (ValueError, TypeError):
            return self.default


@dataclass
class ChoiceParam(RoleParam):
    """Selection parameter among a fixed list of choices (rendered as a QComboBox)."""
    choices: List[str] = None
    default: str = ""

    def __post_init__(self):
        if self.choices is None:
            self.choices = []
        if not self.default and self.choices:
            self.default = self.choices[0]

    def cast_and_validate(self, value: Any) -> str:
        val_str = str(value)
        if val_str in self.choices:
            return val_str
        return self.default

