"""
SimPulse SDK — Declarative Concrete Parameter Descriptors.
Provides pure-Python typed descriptors (BoolParam, IntRangeParam, FloatRangeParam, ChoiceParam).
Fully decoupled from any UI framework (no Qt dependencies).
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List

from simpulse_sdk.contracts.params import ConfigParam, ParamScalarValue


@dataclass
class BoolParam(ConfigParam[bool]):
    """Boolean parameter descriptor."""
    default: bool = True

    def cast_and_validate(self, value: ParamScalarValue) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)


@dataclass
class IntRangeParam(ConfigParam[int]):
    """Integer parameter descriptor with bounded range (min, max, step, unit)."""
    min_val: int = 0
    max_val: int = 100
    step: int = 1
    unit: str = ""
    default: int = 0

    def cast_and_validate(self, value: ParamScalarValue) -> int:
        try:
            val_int = int(round(float(value)))
            return max(self.min_val, min(self.max_val, val_int))
        except (ValueError, TypeError):
            return self.default


@dataclass
class FloatRangeParam(ConfigParam[float]):
    """Float parameter descriptor with bounded range (min, max, step, unit)."""
    min_val: float = 0.0
    max_val: float = 100.0
    step: float = 0.1
    unit: str = ""
    default: float = 0.0

    def cast_and_validate(self, value: ParamScalarValue) -> float:
        try:
            val_flt = float(value)
            val_rounded = round(val_flt, 3)
            return max(self.min_val, min(self.max_val, val_rounded))
        except (ValueError, TypeError):
            return self.default


@dataclass
class ChoiceParam(ConfigParam[str]):
    """Selection parameter descriptor among a fixed list of choices."""
    choices: Optional[List[str]] = None
    default: str = ""

    def __post_init__(self):
        if self.choices is None:
            self.choices = []
        if not self.default and self.choices:
            self.default = self.choices[0]

    def cast_and_validate(self, value: ParamScalarValue) -> str:
        val_str = str(value)
        if self.choices and val_str in self.choices:
            return val_str
        return self.default


__all__ = [
    "BoolParam",
    "IntRangeParam",
    "FloatRangeParam",
    "ChoiceParam",
]
