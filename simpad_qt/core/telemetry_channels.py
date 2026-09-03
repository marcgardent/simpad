"""
SimPad Qt6 Telemetry Channels & Packet Specifications.
Defines strongly-typed telemetry channels, rate levels, plugin desiderata and packet structures.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class TelemetryChannel(Enum):
    """Available isiMotor / LMU raw UDP telemetry channels."""
    TELEMETRY = "Telemetry"                      # TelemInfo (Player vehicle dynamics, wheels, engine)
    OPPONENT_TELEMETRY = "OpponentTelemetry"    # TelemInfo (Opponent / AI vehicles dynamics)
    COMPACT_SCORING = "CompactScoring"          # CompactScoring (Live timings, lap deltas, sectors, positions)
    FULL_SCORING = "FullScoring"                # FullScoringSession (Full grid standings, vehicle classes, rules)
    WEATHER = "Weather"                         # WeatherControl (Track temp, ambient temp, rain intensity, wind)
    EXTENDED_STATE = "ExtendedState"            # ExtendedState (Headlights, wipers, ignition, flags)
    FORCE_FEEDBACK = "ForceFeedback"            # ForceFeedback (FFB torque and forces)
    GRAPHICS = "Graphics"                       # Graphics (Camera and graphical frame telemetry)
    TRACK_RULES = "TrackRules"                  # TrackRules (Yellow flags, safety vehicle, pit limits)
    PIT_MENU = "PitMenu"                        # PitMenu (Pit stop selections, fuel, tires)
    SYSTEM_EVENTS = "SystemEvents"              # SystemEvents (Session transitions, sector crossings)

    @property
    def display_name(self) -> str:
        names = {
            TelemetryChannel.TELEMETRY: "Player Vehicle Physics (TelemInfo)",
            TelemetryChannel.OPPONENT_TELEMETRY: "Opponents Physics (TelemInfo)",
            TelemetryChannel.COMPACT_SCORING: "Compact Scoring (CompactScoring)",
            TelemetryChannel.FULL_SCORING: "Full Scoring & Grid (FullScoring)",
            TelemetryChannel.WEATHER: "Weather Conditions (WeatherControl)",
            TelemetryChannel.EXTENDED_STATE: "Vehicle State & Lights (ExtendedState)",
            TelemetryChannel.FORCE_FEEDBACK: "Force Feedback (ForceFeedback)",
            TelemetryChannel.GRAPHICS: "Graphics Telemetry (Graphics)",
            TelemetryChannel.TRACK_RULES: "Track Rules & Flags (TrackRules)",
            TelemetryChannel.PIT_MENU: "Pit Strategy Menu (PitMenu)",
            TelemetryChannel.SYSTEM_EVENTS: "System Events (SystemEvents)",
        }
        return names.get(self, self.value)

    @property
    def json_variable_name(self) -> str:
        """Name of the key in CustomPluginVariables.JSON."""
        keys = {
            TelemetryChannel.TELEMETRY: "PlayerTelemetryRate",
            TelemetryChannel.OPPONENT_TELEMETRY: "OpponentTelemetryRate",
            TelemetryChannel.COMPACT_SCORING: "CompactScoringRate",
            TelemetryChannel.FULL_SCORING: "FullScoringRate",
            TelemetryChannel.WEATHER: "WeatherRate",
            TelemetryChannel.EXTENDED_STATE: "ExtendedStateRate",
            TelemetryChannel.FORCE_FEEDBACK: "ForceFeedbackRate",
            TelemetryChannel.GRAPHICS: "GraphicsRate",
            TelemetryChannel.TRACK_RULES: "TrackRulesRate",
            TelemetryChannel.PIT_MENU: "PitMenuRate",
            TelemetryChannel.SYSTEM_EVENTS: "SystemEvents",
        }
        return keys.get(self, f"{self.value}Rate")

    @property
    def available_rates(self) -> List[str]:
        """Allowed rate string options in CustomPluginVariables.JSON."""
        if self == TelemetryChannel.SYSTEM_EVENTS:
            return ["Enabled", "Disabled"]
        if self in (TelemetryChannel.TELEMETRY, TelemetryChannel.OPPONENT_TELEMETRY):
            return ["unlimited", "100Hz", "60Hz", "50Hz", "20Hz", "10Hz", "off"]
        if self in (TelemetryChannel.COMPACT_SCORING, TelemetryChannel.FULL_SCORING):
            return ["50Hz", "20Hz", "10Hz", "5Hz", "2Hz", "1Hz", "off"]
        if self == TelemetryChannel.WEATHER:
            return ["10Hz", "5Hz", "2Hz", "1Hz", "0.5Hz", "off"]
        if self == TelemetryChannel.FORCE_FEEDBACK:
            return ["unlimited", "100Hz", "50Hz", "20Hz", "off"]
        return ["50Hz", "20Hz", "10Hz", "5Hz", "1Hz", "off"]


@dataclass(frozen=True)
class ChannelRequirement:
    """Requirement/desiderata declared by a plugin for a specific telemetry channel."""
    channel: TelemetryChannel
    preferred_hz: int
    required: bool = True
    reason: str = ""


@dataclass
class ChannelMetrics:
    """Real-time performance measurements for a single telemetry channel."""
    channel: TelemetryChannel
    configured_rate: str = "off"
    packet_count: int = 0
    total_bytes: int = 0
    measured_hz: float = 0.0
    measured_kbs: float = 0.0
    last_packet_timestamp: float = 0.0
    is_active: bool = False

    def update_measurement(self, packet_bytes: int, now: float) -> None:
        self.packet_count += 1
        self.total_bytes += packet_bytes
        self.last_packet_timestamp = now
        self.is_active = True


@dataclass(frozen=True)
class TelemetryRawPacket:
    """Strongly-typed packet wrapper dispatched from UDP server to plugins."""
    channel: TelemetryChannel
    data: Any
    raw_bytes_len: int
    timestamp: float = field(default_factory=time.time)
