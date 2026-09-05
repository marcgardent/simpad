"""
SimPulse Race Engineer — Message & Status Models.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RoleStatus(str, Enum):
    """Activity state of a race engineer role."""
    IDLE = "IDLE"      # Role idle / inactive / no alerts
    BUSY = "BUSY"      # Role active / speaking / critical sequence


@dataclass
class EngineerMessage:
    """Audio / vocal message emitted by a role."""
    phrase_key: str
    priority: int = 50
    interrupt: bool = False
    text_override: Optional[str] = None
    role_id: str = ""
    timestamp: float = field(default_factory=time.time)
