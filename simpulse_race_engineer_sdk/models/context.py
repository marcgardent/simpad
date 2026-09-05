"""
SimPulse Race Engineer — Context Models.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Union, List, Any

from isimotor_rawudp_client import (
    TelemInfo,
    CompactScoring,
    FullScoringSession,
    VehicleScoring,
    TelemVect3,
)
from simpulse_sdk import (
    TelemetryStateStore,
    TelemetryWakeReason,
    TelemetryRawPacket,
)
from .message import EngineerMessage

TelemetryTriggerPacket = Union[TelemInfo, FullScoringSession, CompactScoring, TelemetryRawPacket]


@dataclass
class EngineerContext:
    """
    Unified telemetry & scoring context passed to each role during evaluation.
    Encapsulates all necessary data for intelligent situational decisions.
    """
    # Raw UDP packet triggering the current update
    trigger_packet: Optional[TelemetryTriggerPacket] = None

    # Central telemetry state store instance
    state_store: Optional[TelemetryStateStore] = None

    # Normalized telemetry timestamp
    timestamp: float = 0.0

    # Wake reason for the pipeline tick
    wake_reason: Optional[TelemetryWakeReason] = None

    # Reference profile for track annotations / line
    reference_profile: Optional[Any] = None

    def get_track_name(self) -> str:
        """Returns clean track name from active scoring or reference profile."""
        if self.state_store:
            cs = self.state_store.compact_scoring.data
            if cs and cs.track_name:
                return cs.track_name
            fs = self.state_store.full_scoring.data
            if fs and fs.track_name:
                return fs.track_name
        if self.reference_profile and getattr(self.reference_profile, "track_name", None):
            return str(self.reference_profile.track_name)
        return ""

    def get_reference_profile(self) -> Optional[Any]:
        """Returns active reference lap profile if available."""
        return self.reference_profile
