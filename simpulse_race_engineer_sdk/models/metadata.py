"""
SimPulse Race Engineer — Metadata Models.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from ..contracts.role import BaseRole


@dataclass
class RoleMetadata:
    """Metadata describing a registered race engineer role."""
    role_id: str
    name: str
    description: str = ""
    default_priority: int = 50
    role_class: Optional[Type[BaseRole]] = None


SubpluginMetadata = RoleMetadata
