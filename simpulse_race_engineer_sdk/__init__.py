"""
SimPulse Virtual Race Engineer & Spotters SDK.
Third-party developers implement BaseRole to create custom spotters and telemetry advisors.
"""

from simpulse_race_engineer_sdk.contracts import (
    BaseRole,
    BaseEngineerSubplugin,
    EngineerSubplugin,
    RoleHostSlot,
    EngineerHostSlot,
    SubpluginHostSlot,
)
from simpulse_race_engineer_sdk.models import (
    RoleStatus,
    EngineerMessage,
    RoleMetadata,
    SubpluginMetadata,
    EngineerContext,
    TelemetryTriggerPacket,
)

__all__ = [
    # Contracts
    "BaseRole",
    "BaseEngineerSubplugin",
    "EngineerSubplugin",
    "RoleHostSlot",
    "EngineerHostSlot",
    "SubpluginHostSlot",
    # Models
    "RoleStatus",
    "EngineerMessage",
    "RoleMetadata",
    "SubpluginMetadata",
    "EngineerContext",
    "TelemetryTriggerPacket",
]
