"""
SimPad Race Engineer — Base abstractions for Race Engineer Roles.
SOLID, modular, and extensible architecture.
"""

from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass, field
import time
from typing import Optional, Dict, Any, List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from src.engineer.context import EngineerContext

try:
    from simpad_qt.core.telemetry_channels import ChannelRequirement, TelemetryChannel
except ImportError:
    ChannelRequirement = Any
    TelemetryChannel = Any


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


class BaseRole(ABC):
    """
    Abstract base class for all race engineer roles / sub-plugins.
    Each role:
    - has a single responsibility (Clean/Dirty lap, Traffic spotter, etc.),
    - declares its telemetry subscription needs (ChannelRequirement),
    - declares required sound phrases for operation,
    - has configurable priority and reports IDLE or BUSY state.
    """

    def __init__(
        self,
        role_id: str,
        name: str,
        description: str = "",
        priority: int = 50,
        enabled: bool = True,
        audio_engine: Optional[Any] = None,
    ):
        self.role_id = role_id
        self.name = name
        self.description = description
        self.priority = priority
        self.enabled = enabled
        self.audio_engine = audio_engine

    @property
    def status(self) -> RoleStatus:
        """Returns current activity status of role (IDLE or BUSY)."""
        if not self.enabled:
            return RoleStatus.IDLE
        return RoleStatus.BUSY if self.is_busy() else RoleStatus.IDLE

    @abstractmethod
    def is_busy(self) -> bool:
        """Indicates whether role is currently engaged in an active or critical sequence."""
        pass

    @abstractmethod
    def update(self, context: "EngineerContext") -> Optional[EngineerMessage]:
        """
        Evaluates telemetry and scoring data on each tick.
        Returns a message if speech should trigger, or None.
        """
        pass

    def get_channel_requirements(self) -> List[Any]:
        """
        Declares telemetry channels and preferred sample rates required by this role.
        The main RaceEngineer plugin aggregates requirements across all sub-plugins.
        """
        return []

    def get_sound_requirements(self) -> Dict[str, str]:
        """
        Declares catalog of sounds / phrases required by this sub-plugin (phrase_key -> TTS text).
        The main RaceEngineer plugin aggregates sounds and manages verification / generation.
        """
        return {}

    def reset(self) -> None:
        """Resets internal state of role."""
        pass

    def get_parameters(self) -> List[Any]:
        """
        Returns declarative list of parameter descriptors (RoleParam)
        specific to this role (e.g. BoolParam, IntRangeParam, FloatRangeParam).
        """
        return []

    def get_param_value(self, name: str) -> Any:
        """Returns current value of named parameter."""
        if hasattr(self, name):
            return getattr(self, name)
        for p in self.get_parameters():
            if p.name == name:
                return p.default
        return None

    def set_param_value(self, name: str, value: Any) -> None:
        """Sets parameter value with validation and type casting."""
        for p in self.get_parameters():
            if p.name == name:
                valid_val = p.cast_and_validate(value)
                setattr(self, name, valid_val)
                return
        setattr(self, name, value)

    def get_state_summary(self) -> Dict[str, Any]:
        """Returns serializable state summary for GUI and debugging."""
        summary = {
            "role_id": self.role_id,
            "name": self.name,
            "status": self.status.value,
            "enabled": self.enabled,
            "priority": self.priority,
        }
        for p in self.get_parameters():
            summary[p.name] = self.get_param_value(p.name)
        return summary

    def get_config(self) -> Dict[str, Any]:
        """Returns configurable role parameters for persistence."""
        cfg = {
            "enabled": self.enabled,
            "priority": self.priority,
        }
        for p in self.get_parameters():
            cfg[p.name] = self.get_param_value(p.name)
        return cfg

    def set_config(self, config: Dict[str, Any]) -> None:
        """Applies external configuration dictionary."""
        if "enabled" in config:
            self.enabled = bool(config["enabled"])
        if "priority" in config:
            self.priority = int(config["priority"])
        for p in self.get_parameters():
            if p.name in config:
                self.set_param_value(p.name, config[p.name])

    def emit_sound(self, phrase_key: str, interrupt: bool = False) -> None:
        """Plays sound via injected audio engine if configured."""
        if self.audio_engine:
            if hasattr(self.audio_engine, "play_phrase"):
                self.audio_engine.play_phrase(phrase_key, interrupt=interrupt)
            elif callable(self.audio_engine):
                self.audio_engine(phrase_key, interrupt=interrupt)
