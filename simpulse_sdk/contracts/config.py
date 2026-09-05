"""
SimPulse SDK — Configuration Contracts & Interfaces.
Defines interfaces for plugin configuration isolation and host configuration services.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Type, TypeVar, Union

T = TypeVar("T")
PluginScalar = Union[str, int, float, bool, None]


@dataclass
class AppSettings:
    """Core application settings."""
    dark_theme: bool = True
    target_fps: int = 60
    overlay_enabled: bool = True
    mock_telemetry: bool = False
    hud_debug_boxes: bool = False
    delta_reference_mode: str = "all_time_best"
    delta_freeze_duration: float = 3.5
    delta_ema_samples: int = 0
    abs_threshold: float = 0.15
    tc_threshold: float = 0.2
    lateral_slide_threshold: float = 0.1
    udp_host: str = "127.0.0.1"
    udp_port: int = 5000
    update_rate_hz: int = 100


@dataclass
class GamePluginConfig:
    """Game telemetry UDP plugin rates and network settings."""
    target_ip: str = "127.0.0.1"
    target_port: int = 5000
    inbound_port: int = 5001
    enable_logging: bool = False
    rates: Dict[str, str] = field(default_factory=lambda: {
        "PlayerTelemetryRate": "unlimited",
        "OpponentTelemetryRate": "off",
        "CompactScoringRate": "10Hz",
        "FullScoringRate": "5Hz",
        "WeatherRate": "1Hz",
        "ExtendedStateRate": "10Hz",
        "ForceFeedbackRate": "off",
        "GraphicsRate": "off",
        "TrackRulesRate": "off",
        "PitMenuRate": "off",
        "SystemEvents": "Enabled",
    })


@dataclass
class LoggerSettings:
    """Fine-grained subsystem logging activations."""
    telemetry: bool = False
    engineer: bool = False
    schedule: bool = False
    haptics: bool = False
    gui: bool = False
    utils: bool = False
    track_limits: bool = False
    overlay_anomaly: bool = False
    delta_debug: bool = False


class IPluginConfigProvider(ABC):
    """
    Contract interface providing isolated, strongly-typed configuration storage to plugins.
    Plugins only interact with their own namespace.
    """

    @abstractmethod
    def get_plugin_config_as(self, plugin_id: str, dataclass_cls: Type[T]) -> T:
        """Instantiate a strongly-typed dataclass from plugin configuration."""
        ...

    @abstractmethod
    def set_plugin_config_from(self, plugin_id: str, dataclass_obj: object, auto_save: bool = True) -> None:
        """Store a strongly-typed dataclass into plugin configuration."""
        ...


class ICoreConfigProvider(ABC):
    """
    Contract interface providing configuration services to SimPulse Core & Host.
    Manages core application settings, telemetry, loggers, and plugin activation orchestration.
    """

    @abstractmethod
    def load(self) -> None:
        """Load and deserialize configuration from persistent storage."""
        ...

    @abstractmethod
    def save(self) -> None:
        """Serialize and persist configuration to storage."""
        ...

    @abstractmethod
    def get_app_settings(self) -> AppSettings:
        """Return strongly-typed core application settings."""
        ...

    @abstractmethod
    def set_app_settings(self, settings: AppSettings, auto_save: bool = True) -> None:
        """Update core application settings."""
        ...

    @abstractmethod
    def get_game_plugin_settings(self) -> GamePluginConfig:
        """Return strongly-typed game telemetry plugin settings."""
        ...

    @abstractmethod
    def set_game_plugin_settings(self, settings: GamePluginConfig, auto_save: bool = True) -> None:
        """Update game telemetry plugin settings."""
        ...

    @abstractmethod
    def get_logger_settings(self) -> LoggerSettings:
        """Return fine-grained subsystem logging activations."""
        ...

    @abstractmethod
    def set_logger_settings(self, settings: LoggerSettings, auto_save: bool = True) -> None:
        """Update fine-grained subsystem logging activations."""
        ...

    @abstractmethod
    def is_plugin_enabled(self, plugin_id: str, default: bool = True) -> bool:
        """Host check whether a plugin is enabled in configuration."""
        ...

    @abstractmethod
    def set_plugin_enabled(self, plugin_id: str, enabled: bool, auto_save: bool = True) -> None:
        """Host activation or deactivation of a plugin in configuration."""
        ...


class IConfigManager(ICoreConfigProvider, IPluginConfigProvider, ABC):
    """
    Unified configuration manager interface.
    """
    pass
