"""
SimPulse Race Engineer — Base Role Contract.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Tuple, Callable, Union, Any, TYPE_CHECKING
from simpulse_sdk import (
    TelemetryStateStore,
    TelemetryWakeReason,
    ChannelRequirement,
    RoleParam,
    ParamScalarValue,
)
from ..models.message import RoleStatus, EngineerMessage

if TYPE_CHECKING:
    from ..models.context import EngineerContext


class BaseRole(ABC):
    """
    Abstract contract for all race engineer roles / sub-plugins.
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
        audio_engine: Optional[Any] = None,
    ):
        self.role_id = role_id
        self.name = name
        self.description = description
        self.priority = priority
        self.audio_engine = audio_engine

    @property
    def status(self) -> RoleStatus:
        """Returns current activity status of role (IDLE or BUSY)."""
        return RoleStatus.BUSY if self.is_busy() else RoleStatus.IDLE

    @abstractmethod
    def is_busy(self) -> bool:
        """Indicates whether role is currently engaged in an active or critical sequence."""
        pass

    def on_physics_tick(
        self,
        state: TelemetryStateStore,
        context: EngineerContext,
    ) -> Optional[EngineerMessage]:
        """Hook called on high-frequency physics tick (TelemInfo 100-120Hz)."""
        return None

    def on_scoring_update(
        self,
        state: TelemetryStateStore,
        context: EngineerContext,
    ) -> Optional[EngineerMessage]:
        """Hook called on scoring timing update (CompactScoring 10Hz)."""
        return None

    def on_grid_update(
        self,
        state: TelemetryStateStore,
        context: EngineerContext,
    ) -> Optional[EngineerMessage]:
        """Hook called on grid / standings update (FullScoringSession 2-5Hz)."""
        return None

    def on_weather_update(
        self,
        state: TelemetryStateStore,
        context: EngineerContext,
    ) -> Optional[EngineerMessage]:
        """Hook called on weather condition changes (WeatherControl ~1Hz)."""
        return None

    def on_session_event(
        self,
        state: TelemetryStateStore,
        context: EngineerContext,
    ) -> Optional[EngineerMessage]:
        """Hook called on session / system transitions (SystemEvents)."""
        return None

    def on_lap_transition(
        self,
        state: TelemetryStateStore,
        context: EngineerContext,
    ) -> Optional[EngineerMessage]:
        """Hook called on lap transitions."""
        return None

    def on_track_limits(
        self,
        state: TelemetryStateStore,
        context: EngineerContext,
    ) -> Optional[EngineerMessage]:
        """Hook called on track limits violations."""
        return None

    def update(self, context: EngineerContext) -> Optional[EngineerMessage]:
        """
        Default polymorphic dispatcher. Routes evaluation to the specific event hook
        based on context.wake_reason.
        """
        wake = context.wake_reason
        store = context.state_store
        if wake is not None:
            if wake == TelemetryWakeReason.PHYSICS_TICK:
                return self.on_physics_tick(store, context)
            elif wake == TelemetryWakeReason.SCORING_UPDATE:
                return self.on_scoring_update(store, context)
            elif wake == TelemetryWakeReason.GRID_UPDATE:
                return self.on_grid_update(store, context)
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

    def reset(self) -> None:
        """Resets internal role state."""
        pass

    def get_parameters(self) -> List[RoleParam]:
        """Returns declarative configurable parameters for this role."""
        return []

    def get_channel_requirements(self) -> List[ChannelRequirement]:
        """Declares telemetry channels required by this role."""
        return []

    def get_sound_requirements(self) -> Dict[str, str]:
        """Declares phrase keys and text descriptions required by this role."""
        return {}

    def get_param_value(self, name: str) -> Optional[ParamScalarValue]:
        """Reads value of an attribute corresponding to param_name."""
        if name in self.__dict__:
            return self.__dict__[name]
        for p in self.get_parameters():
            if p.name == name:
                return p.default
        return None

    def set_param_value(self, name: str, value: ParamScalarValue) -> None:
        """Updates value of an attribute corresponding to param_name with validation."""
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
            "priority": self.priority,
        }
        for p in self.get_parameters():
            summary[p.name] = self.get_param_value(p.name)
        return summary

    def get_config(self) -> Dict[str, ParamScalarValue]:
        """Serializes current configuration."""
        cfg: Dict[str, ParamScalarValue] = {
            "priority": self.priority,
        }
        for p in self.get_parameters():
            val = self.get_param_value(p.name)
            if val is not None:
                cfg[p.name] = val
        return cfg

    def set_config(self, config: Dict[str, ParamScalarValue]) -> None:
        """Applies external configuration dictionary."""
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


# Aliases
BaseEngineerSubplugin = BaseRole
EngineerSubplugin = BaseRole
