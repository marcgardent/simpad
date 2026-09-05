"""
SimPulse Race Engineer — Declarative Configurable Parameters for Roles/Subplugins.
Re-exports parameter descriptors from core parameter definitions.
"""

from simpulse.core.params import (
    RoleParam,
    SubpluginParam,
    ParamDescriptor,
    BoolParam,
    IntRangeParam,
    FloatRangeParam,
    ChoiceParam,
    ParamScalarValue,
    ParamWidgetFactory,
)

__all__ = [
    "RoleParam",
    "SubpluginParam",
    "ParamDescriptor",
    "BoolParam",
    "IntRangeParam",
    "FloatRangeParam",
    "ChoiceParam",
    "ParamScalarValue",
    "ParamWidgetFactory",
]

