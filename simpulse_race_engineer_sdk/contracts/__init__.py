"""
SimPulse Race Engineer SDK — Subplugin Contracts.
"""

from .role import (
    BaseRole,
    BaseEngineerSubplugin,
    EngineerSubplugin,
)
from .slot import (
    RoleHostSlot,
    EngineerHostSlot,
    SubpluginHostSlot,
)

__all__ = [
    "BaseRole",
    "BaseEngineerSubplugin",
    "EngineerSubplugin",
    "RoleHostSlot",
    "EngineerHostSlot",
    "SubpluginHostSlot",
]
