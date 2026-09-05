"""
SimPad Built-in Plugin — Virtual Race Engineer & Sub-Plugins Orchestrator.
"""

from .plugin import RaceEngineerPlugin
from .manager import RaceEngineer
from .base import BaseRole, BaseEngineerSubplugin, EngineerMessage, RoleStatus
from .context import EngineerContext, TelemetryTriggerPacket
from .registry import RoleRegistry, SubpluginRegistry, RoleMetadata, SubpluginMetadata
from .factory import RoleFactory, SubpluginFactory
from . import subplugins
from . import roles

__all__ = [
    "RaceEngineerPlugin",
    "RaceEngineer",
    "BaseRole",
    "BaseEngineerSubplugin",
    "EngineerMessage",
    "RoleStatus",
    "EngineerContext",
    "TelemetryTriggerPacket",
    "RoleRegistry",
    "SubpluginRegistry",
    "RoleMetadata",
    "SubpluginMetadata",
    "RoleFactory",
    "SubpluginFactory",
    "subplugins",
    "roles",
]
