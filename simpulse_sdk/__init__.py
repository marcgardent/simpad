"""
SimPulse SDK — Official Python SDK for SimPulse / SimPad Plugins and Extensions.
"""

# Contracts
from simpulse_sdk.contracts import (
    SimPulsePlugin,
    PluginContext,
    IPluginConfigProvider,
    ICoreConfigProvider,
    IConfigManager,
    AppSettings,
    GamePluginConfig,
    LoggerSettings,
    ITelemetrySubscriber,
    IDeltaSubscriber,
    IPacketSubscriber,
    ITelemetryStateSubscriber,
    ITabProvider,
    IHudWidgetProvider,
)

# Models
from simpulse_sdk.models import (
    VehicleSensors,
    TelemetryChannel,
    ChannelRequirement,
    ChannelMetrics,
    TelemetryRawPacket,
    TelemetryPayload,
    TelemetryWakeReason,
    LapDeltaPacket,
    SectorInfo,
    DeltaReferenceMode,
    TelemetryStateStore,
    PacketSlot,
    PluginMetadata,
    PluginState,
    PluginErrorReport,
    HudSlot,
    HudLayoutSpec,
    clamp,
    apply_response_curve,
    format_lap_time,
)

__all__ = [
    # Contracts
    "SimPulsePlugin",
    "PluginContext",
    "IPluginConfigProvider",
    "ICoreConfigProvider",
    "IConfigManager",
    "AppSettings",
    "GamePluginConfig",
    "LoggerSettings",
    "ITelemetrySubscriber",
    "IDeltaSubscriber",
    "IPacketSubscriber",
    "ITelemetryStateSubscriber",
    "ITabProvider",
    "IHudWidgetProvider",
    # Models
    "VehicleSensors",
    "TelemetryChannel",
    "ChannelRequirement",
    "ChannelMetrics",
    "TelemetryRawPacket",
    "TelemetryPayload",
    "TelemetryWakeReason",
    "LapDeltaPacket",
    "SectorInfo",
    "DeltaReferenceMode",
    "TelemetryStateStore",
    "PacketSlot",
    "PluginMetadata",
    "PluginState",
    "PluginErrorReport",
    "HudSlot",
    "HudLayoutSpec",
    "clamp",
    "apply_response_curve",
    "format_lap_time",
]
