"""
SimPulse Race Engineer — Base abstractions for Race Engineer Roles.
Re-exports BaseRole from simpulse_race_engineer_sdk and defines host audio plumbing.
"""

from typing import Optional, Union, Callable, Protocol, runtime_checkable
from simpulse_race_engineer_sdk import (
    BaseRole,
    BaseEngineerSubplugin,
    EngineerSubplugin,
    EngineerMessage,
    RoleStatus,
    RoleHostSlot,
    EngineerHostSlot,
)


@runtime_checkable
class AudioEngineProtocol(Protocol):
    """Protocol for audio engines playing race engineer phrases in SimPulse host."""
    def play_phrase(self, phrase_key: str, interrupt: bool = False, text_override: Optional[str] = None) -> None:
        ...


AudioEngineType = Union[AudioEngineProtocol, Callable[..., None], type]

__all__ = [
    "BaseRole",
    "BaseEngineerSubplugin",
    "EngineerSubplugin",
    "EngineerMessage",
    "RoleStatus",
    "RoleHostSlot",
    "EngineerHostSlot",
    "AudioEngineProtocol",
    "AudioEngineType",
]
