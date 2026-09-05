"""
SimPulse SDK — Contracts and Protocol specifications.
"""
from .plugin import SimPulsePlugin, PluginContext
from .protocols import (
    ITelemetrySubscriber,
    IDeltaSubscriber,
    ITelemetryStateSubscriber,
    ITabProvider,
    IHudWidgetProvider,
)
from .config import IPluginConfigProvider
from .params import (
    IParamDescriptor,
    ConfigParam,
    PluginParam,
    RoleParam,
    SubpluginParam,
    ParamDescriptor,
    ParamScalarValue,
)

__all__ = [
    "SimPulsePlugin",
    "PluginContext",
    "ITelemetrySubscriber",
    "IDeltaSubscriber",
    "ITelemetryStateSubscriber",
    "ITabProvider",
    "IHudWidgetProvider",
    "IPluginConfigProvider",
    "IParamDescriptor",
    "ConfigParam",
    "PluginParam",
    "RoleParam",
    "SubpluginParam",
    "ParamDescriptor",
    "ParamScalarValue",
]

