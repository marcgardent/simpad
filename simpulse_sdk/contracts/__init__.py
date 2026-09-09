"""
SimPulse SDK — Contracts and Protocol specifications.
"""
from .plugin import SimPulsePlugin, PluginContext
from .protocols import (
    ITelemetrySubscriber,
    IDeltaSubscriber,
    IEnergySubscriber,
    ITelemetryStateSubscriber,
    IChannelSampleSubscriber,
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
    "IEnergySubscriber",
    "ITelemetryStateSubscriber",
    "IChannelSampleSubscriber",
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

