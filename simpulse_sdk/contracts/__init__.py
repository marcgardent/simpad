"""
SimPulse SDK — Core Contracts & Interfaces.
"""

from simpulse_sdk.contracts.config import (
    IPluginConfigProvider,
    ICoreConfigProvider,
    IConfigManager,
    AppSettings,
    GamePluginConfig,
    LoggerSettings,
)
from simpulse_sdk.contracts.plugin import (
    SimPulsePlugin,
    PluginContext,
)
from simpulse_sdk.contracts.protocols import (
    ITelemetrySubscriber,
    IDeltaSubscriber,
    IPacketSubscriber,
    ITelemetryStateSubscriber,
    ITabProvider,
    IHudWidgetProvider,
)

__all__ = [
    "IPluginConfigProvider",
    "ICoreConfigProvider",
    "IConfigManager",
    "AppSettings",
    "GamePluginConfig",
    "LoggerSettings",
    "SimPulsePlugin",
    "PluginContext",
    "ITelemetrySubscriber",
    "IDeltaSubscriber",
    "IPacketSubscriber",
    "ITelemetryStateSubscriber",
    "ITabProvider",
    "IHudWidgetProvider",
]
