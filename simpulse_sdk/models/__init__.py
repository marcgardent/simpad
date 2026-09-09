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
    LmuTelemetryData,
)
from simpulse_sdk.models.delta import (
    LapDeltaPacket,
    SectorInfo,
    DeltaReferenceMode,
    SplitStatus,
    LapColorStatus,
    ExpectedStatus,
)
from simpulse_sdk.models.energy import EnergyPacket
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
from simpulse_sdk.models.view import TelemetryView, TrackCutState
from simpulse_sdk.models.wheels import (
    ALL_WHEEL_POSITIONS,
    TireCorner,
    WheelPosition,
    WheelSet,
)
from simpulse_sdk.models.ecu import (
    AntiLockECU,
    ChassisECU,
    CockpitECU,
    PowertrainECU,
    TractionControlECU,
    VehicleECU,
)
from simpulse_sdk.models.reference_profile import (
    AnnotationType,
    ReferenceLapProfileView,
    ReferenceLapSummary,
    TrackAnnotationView,
)
from simpulse_sdk.models.timing import (
    TimeLap,
    TimeTarget,
    TimeSectorViewModel,
    TimeLapViewModel,
    TimeStatus,
    WallOfFameTimes,
    resolve_target,
    resolve_is_personal_record_target,
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
    format_sector_time,
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
    "LmuTelemetryData",
    "LapDeltaPacket",
    "EnergyPacket",
    "SectorInfo",
    "DeltaReferenceMode",
    "SplitStatus",
    "LapColorStatus",
    "ExpectedStatus",
    "BaseTimingState",
    "FullGridScoringState",
    "TelemetryStateStore",
    "TelemetryView",
    "TrackCutState",
    "ALL_WHEEL_POSITIONS",
    "TireCorner",
    "WheelPosition",
    "WheelSet",
    "AntiLockECU",
    "ChassisECU",
    "CockpitECU",
    "PowertrainECU",
    "TractionControlECU",
    "VehicleECU",
    "PacketSlot",
    "TimingStatus",
    "ValidityEvent",
    "LapStatus",
    "AnnotationType",
    "ReferenceLapProfileView",
    "ReferenceLapSummary",
    "TrackAnnotationView",
    "TimeLap",
    "TimeTarget",
    "TimeSectorViewModel",
    "TimeLapViewModel",
    "TimeStatus",
    "WallOfFameTimes",
    "resolve_target",
    "resolve_is_personal_record_target",
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
    "format_sector_time",
    "BoolParam",
    "IntRangeParam",
    "FloatRangeParam",
    "ChoiceParam",
]

