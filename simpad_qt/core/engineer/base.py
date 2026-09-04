"""
SimPad Race Engineer — Base abstractions for Race Engineer Roles.
SOLID, modular, and extensible architecture.
"""

from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass, field
import time
from typing import Optional, Dict, List, Tuple, TYPE_CHECKING, Callable, Union, Protocol, runtime_checkable

from ..telemetry.state_store import TelemetryStateStore, TelemetryWakeReason
from simpad_qt.core.telemetry_channels import ChannelRequirement, TelemetryChannel
from .params import RoleParam, ParamScalarValue

if TYPE_CHECKING:
    from .context import EngineerContext


@runtime_checkable
class AudioEngineProtocol(Protocol):
    """Protocol for audio engines playing race engineer phrases."""
    def play_phrase(self, phrase_key: str, interrupt: bool = False, text_override: Optional[str] = None) -> None:
        ...


AudioEngineType = Union[AudioEngineProtocol, Callable[..., None], type]


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
    - has a single responsibility (Lap validity, Traffic spotter, etc.),
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
        audio_engine: Optional[AudioEngineType] = None,
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

    # =========================================================================
    # Polymorphic Telemetry State Event Hooks (Default pass/None)
    # Roles override only the specific hooks they need to evaluate.
    # =========================================================================

    def on_physics_tick(
        self,
        state: TelemetryStateStore,
        context: "EngineerContext",
    ) -> Optional[EngineerMessage]:
        """Hook called on high-frequency physics tick (TelemInfo 100-120Hz)."""
        return None

    def on_scoring_update(
        self,
        state: TelemetryStateStore,
        context: "EngineerContext",
    ) -> Optional[EngineerMessage]:
        """Hook called on scoring timing update (CompactScoring 10Hz)."""
        return None

    def on_grid_update(
        self,
        state: TelemetryStateStore,
        context: "EngineerContext",
    ) -> Optional[EngineerMessage]:
        """Hook called on grid / standings update (FullScoringSession 2-5Hz)."""
        return None

    def on_weather_update(
        self,
        state: TelemetryStateStore,
        context: "EngineerContext",
    ) -> Optional[EngineerMessage]:
        """Hook called on weather condition changes (WeatherControl ~1Hz)."""
        return None

    def on_session_event(
        self,
        state: TelemetryStateStore,
        context: "EngineerContext",
    ) -> Optional[EngineerMessage]:
        """Hook called on session / system transitions (SystemEvents)."""
        return None

    def update(self, context: "EngineerContext") -> Optional[EngineerMessage]:
        """
        Default polymorphic dispatcher. Routes evaluation to the specific event hook
        based on context.wake_reason. Roles can override specific hooks rather than
        writing monolithic update switches.
        """
        wake = context.wake_reason
        store = context.state_store
        if wake is not None:
            if wake == TelemetryWakeReason.PHYSICS_TICK:
                return self.on_physics_tick(store, context)
            elif wake == TelemetryWakeReason.SCORING_UPDATE:
                return self.on_scoring_update(store, context)
            elif wake == TelemetryWakeReason.WEATHER_UPDATE:
                return self.on_weather_update(store, context)
            elif wake == TelemetryWakeReason.SYSTEM_EVENT:
                return self.on_session_event(store, context)
            elif wake == TelemetryWakeReason.LAP_TRANSITION:
                return self.on_lap_transition(store, context)
            elif wake == TelemetryWakeReason.TRACK_LIMITS:
                return self.on_track_limits(store, context)

        # Fallback evaluation for manual/unspecified triggers
        msg = self.on_physics_tick(store, context)
        if msg is not None:
            return msg
        return self.on_scoring_update(store, context)

    def get_channel_requirements(self) -> List[ChannelRequirement]:
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

    def get_parameters(self) -> List[RoleParam]:
        """
        Returns declarative list of parameter descriptors (RoleParam)
        specific to this role (e.g. BoolParam, IntRangeParam, FloatRangeParam).
        """
        return []

    def get_param_value(self, name: str) -> Optional[ParamScalarValue]:
        """Returns current value of named parameter."""
        if name in self.__dict__:
            return self.__dict__[name]
        for p in self.get_parameters():
            if p.name == name:
                return p.default
        return None

    def set_param_value(self, name: str, value: ParamScalarValue) -> None:
        """Sets parameter value with validation and type casting."""
        for p in self.get_parameters():
            if p.name == name:
                valid_val = p.cast_and_validate(value)
                setattr(self, name, valid_val)
                return
        setattr(self, name, value)

    def get_state_summary(self) -> Dict[str, Union[str, int, float, bool, List[str], None]]:
        """Returns serializable state summary for GUI and debugging."""
        summary: Dict[str, Union[str, int, float, bool, List[str], None]] = {
            "role_id": self.role_id,
            "name": self.name,
            "status": self.status.value,
            "enabled": self.enabled,
            "priority": self.priority,
        }
        for p in self.get_parameters():
            summary[p.name] = self.get_param_value(p.name)
        return summary

    def get_config(self) -> Dict[str, ParamScalarValue]:
        """Returns configurable role parameters for persistence."""
        cfg: Dict[str, ParamScalarValue] = {
            "enabled": self.enabled,
            "priority": self.priority,
        }
        for p in self.get_parameters():
            val = self.get_param_value(p.name)
            if val is not None:
                cfg[p.name] = val
        return cfg

    def set_config(self, config: Dict[str, ParamScalarValue]) -> None:
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
