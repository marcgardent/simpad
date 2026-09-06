"""
SimPulse SDK — Domain Models & Value Objects.
"""

from simpulse_sdk.models.telemetry import (
    VehicleSensors,
    TelemetryChannel,
    ChannelRequirement,
    ChannelMetrics,
    TelemetryRawPacket,
    ChannelSample,
    TelemetryPayload,
    TelemetryWakeReason,
    LmuTelemetryData,
)
from simpulse_sdk.models.delta import (
    LapDeltaPacket,
    SectorInfo,
    DeltaReferenceMode,
)
from simpulse_sdk.models.scoring import (
    BaseTimingState,
    FullGridScoringState,
)
from simpulse_sdk.models.state_store import (
    TelemetryStateStore,
    PacketSlot,
    TimingStatus,
    ValidityEvent,
    LapStatus,
)
from simpulse_sdk.models.plugin_metadata import (
    PluginMetadata,
    PluginState,
    PluginErrorReport,
    HudSlot,
    HudLayoutSpec,
    ISize,
    IRect,
    Size2D,
    Rect2D,
)
from simpulse_sdk.models.math import (
    clamp,
    apply_response_curve,
    format_lap_time,
)
from simpulse_sdk.models.params import (
    BoolParam,
    IntRangeParam,
    FloatRangeParam,
    ChoiceParam,
)

__all__ = [
    "VehicleSensors",
    "TelemetryChannel",
    "ChannelRequirement",
    "ChannelMetrics",
    "TelemetryRawPacket",
    "ChannelSample",
    "TelemetryPayload",
    "TelemetryWakeReason",
    "LmuTelemetryData",
    "LapDeltaPacket",
    "SectorInfo",
    "DeltaReferenceMode",
    "BaseTimingState",
    "FullGridScoringState",
    "TelemetryStateStore",
    "PacketSlot",
    "TimingStatus",
    "ValidityEvent",
    "LapStatus",
    "PluginMetadata",
    "PluginState",
    "PluginErrorReport",
    "HudSlot",
    "HudLayoutSpec",
    "ISize",
    "IRect",
    "Size2D",
    "Rect2D",
    "clamp",
    "apply_response_curve",
    "format_lap_time",
    "BoolParam",
    "IntRangeParam",
    "FloatRangeParam",
    "ChoiceParam",
]

