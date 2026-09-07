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

    # Reference profile for track annotations / line
    reference_profile: Optional[Any] = None

    def get_track_name(self) -> str:
        """Returns clean track name from the unified state (timing/grid/delta) or reference profile."""
        if self.state_store:
            store = self.state_store
            if store.timing is not None and getattr(store.timing, "track_name", ""):
                name = str(store.timing.track_name).strip()
                if name:
                    return name
            if store.grid is not None and getattr(store.grid, "track_name", ""):
                name = str(store.grid.track_name).strip()
                if name:
                    return name
            # store.delta is a real PacketSlot (has .data) when state_store is
            # an actual TelemetryStateStore, or already the plain
            # Optional[LapDeltaPacket] when it's a consolidated TelemetryView
            # (the dispatcher hands non-raw-ingest plugins the latter).
            delta = store.delta.data if hasattr(store.delta, "data") else store.delta
            if delta is not None and getattr(delta, "track_name", ""):
                name = str(delta.track_name).strip()
                if name:
                    return name
        if self.reference_profile and getattr(self.reference_profile, "track_name", None):
            return str(self.reference_profile.track_name)
        return ""

    def get_reference_profile(self) -> Optional[Any]:
        """Returns active reference lap profile if available."""
        return self.reference_profile
