"""
SimPulse SDK — Domain Models & Value Objects.
"""

from simpulse_sdk.models.telemetry import (
    VehicleSensors,
    TelemetryChannel,
    ChannelRequirement,
    ChannelMetrics,
    TelemetryRawPacket,
    TelemetryPayload,
    TelemetryWakeReason,
)
from simpulse_sdk.models.delta import (
    LapDeltaPacket,
    SectorInfo,
    DeltaReferenceMode,
)
from simpulse_sdk.models.state_store import (
    TelemetryStateStore,
    PacketSlot,
)
from simpulse_sdk.models.plugin_metadata import (
    PluginMetadata,
    PluginState,
    PluginErrorReport,
    HudSlot,
    HudLayoutSpec,
)
from simpulse_sdk.models.math import (
    clamp,
    apply_response_curve,
    format_lap_time,
)

__all__ = [
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
