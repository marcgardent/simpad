"""
SimPulse SDK — Contracts and Protocol specifications.
"""
from .plugin import SimPulsePlugin, PluginContext
from .protocols import (
    ITelemetrySubscriber,
    IDeltaSubscriber,
    IPacketSubscriber,
    ITelemetryStateSubscriber,
    ITabProvider,
    IHudWidgetProvider,
)
from .config import IPluginConfigProvider
from .params import (
    RoleParam,
    SubpluginParam,
    ParamDescriptor,
    BoolParam,
    IntRangeParam,
    FloatRangeParam,
    ChoiceParam,
    ParamScalarValue,
)

__all__ = [
    "SimPulsePlugin",
    "PluginContext",
    "ITelemetrySubscriber",
    "IDeltaSubscriber",
    "IPacketSubscriber",
    "ITelemetryStateSubscriber",
    "ITabProvider",
    "IHudWidgetProvider",
    "IPluginConfigProvider",
    "RoleParam",
    "SubpluginParam",
    "ParamDescriptor",
    "BoolParam",
    "IntRangeParam",
    "FloatRangeParam",
    "ChoiceParam",
    "ParamScalarValue",
]
