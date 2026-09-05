"""
SimPad Configuration Service & Strongly-Typed Architecture.
Provides the IConfigManager contract interface and concrete unified ConfigManager.
"""

from __future__ import annotations
import json
import logging
import typing
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict, is_dataclass, fields
from enum import Enum
from pathlib import Path
from typing import Dict, Type, TypeVar, Union

logger = logging.getLogger("simpad.config")

T = TypeVar("T")
PluginScalar = Union[str, int, float, bool, list, dict]


from simpulse_sdk import IPluginConfigProvider


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


@dataclass
class SimPadConfig:
    """Root unified configuration model."""
    app: AppSettings = field(default_factory=AppSettings)
    game_plugin: GamePluginConfig = field(default_factory=GamePluginConfig)
    loggers: LoggerSettings = field(default_factory=LoggerSettings)
    plugins_enabled: Dict[str, bool] = field(default_factory=dict)
    plugins: Dict[str, Dict[str, PluginScalar]] = field(default_factory=dict)

    def is_plugin_enabled(self, plugin_id: str, default: bool = True) -> bool:
        return self.plugins_enabled.get(plugin_id, default)

    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> None:
        self.plugins_enabled[plugin_id] = enabled

    def get_plugin_data(self, plugin_id: str) -> Dict[str, PluginScalar]:
        return self.plugins.get(plugin_id, {})

    def set_plugin_data(self, plugin_id: str, data: Dict[str, PluginScalar]) -> None:
        self.plugins[plugin_id] = data


def sync_config(target: SimPadConfig, source: SimPadConfig) -> None:
    """Synchronize source configuration state into target in-place."""
    target.app = source.app
    target.game_plugin = source.game_plugin
    target.loggers = source.loggers
    target.plugins_enabled.clear()
    target.plugins_enabled.update(source.plugins_enabled)
    target.plugins.clear()
    target.plugins.update(source.plugins)





class ConfigFactory:
    """Factory creating, serializing, and deserializing SimPad configuration data structures."""

    @classmethod
    def create_default_config(cls) -> SimPadConfig:
        """Build a default configuration tree."""
        return SimPadConfig()

    @classmethod
    def create_from_dict(cls, raw_data: dict) -> SimPadConfig:
        """Parse raw dictionary data into strongly-typed SimPadConfig."""
        if not isinstance(raw_data, dict):
            return cls.create_default_config()

        # Parse AppSettings
        app_dict = raw_data.get("app", {})
        if not isinstance(app_dict, dict):
            app_dict = {}
        app_kwargs = {k: v for k, v in app_dict.items() if k in AppSettings.__dataclass_fields__}
        app_settings = AppSettings(**app_kwargs)

        # Parse GamePluginConfig
        game_plugin_dict = raw_data.get("game_plugin", {})
        if not isinstance(game_plugin_dict, dict):
            game_plugin_dict = {}
        gp_kwargs = {k: v for k, v in game_plugin_dict.items() if k in GamePluginConfig.__dataclass_fields__}
        game_plugin = GamePluginConfig(**gp_kwargs)

        # Parse LoggerSettings
        loggers_dict = raw_data.get("loggers", {})
        if not isinstance(loggers_dict, dict):
            loggers_dict = {}
        log_kwargs = {k: v for k, v in loggers_dict.items() if k in LoggerSettings.__dataclass_fields__}
        loggers = LoggerSettings(**log_kwargs)

        # Parse plugins_enabled
        plugins_enabled_dict = raw_data.get("plugins_enabled", {})
        if not isinstance(plugins_enabled_dict, dict):
            plugins_enabled_dict = {}

        # Parse plugins
        plugins_dict = raw_data.get("plugins", {})
        if not isinstance(plugins_dict, dict):
            plugins_dict = {}

        return SimPadConfig(
            app=app_settings,
            game_plugin=game_plugin,
            loggers=loggers,
            plugins_enabled=plugins_enabled_dict,
            plugins=plugins_dict,
        )

    @classmethod
    def create_from_file(cls, file_path: Path) -> SimPadConfig:
        """Read JSON file from path and construct strongly-typed SimPadConfig."""
        if not file_path.exists():
            return cls.create_default_config()

        try:
            content = file_path.read_text(encoding="utf-8")
            raw_data = json.loads(content)
            return cls.create_from_dict(raw_data)
        except Exception as e:
            logger.error(f"Error parsing config file '{file_path}': {e}")
            return cls.create_default_config()

    @classmethod
    def _sanitize_primitive(cls, obj: object) -> object:
        """Recursively ensure enums, dicts, lists, etc. are converted to JSON-serializable primitives."""
        if isinstance(obj, Enum):
            return obj.value
        elif isinstance(obj, dict):
            return {k: cls._sanitize_primitive(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple, set)):
            return [cls._sanitize_primitive(v) for v in obj]
        return obj

    @classmethod
    def serialize_to_dict(cls, config: SimPadConfig) -> dict:
        """Convert SimPadConfig tree into primitive dictionary for serialization."""
        return cls._sanitize_primitive(asdict(config))

    @classmethod
    def serialize_plugin_data(cls, dataclass_obj: object) -> Dict[str, PluginScalar]:
        """Convert plugin object (dataclass or dict) into dictionary format."""
        if is_dataclass(dataclass_obj):
            data = asdict(dataclass_obj)
        elif isinstance(dataclass_obj, dict):
            data = dict(dataclass_obj)
        else:
            raise TypeError(f"Expected dataclass or dict, got {type(dataclass_obj)}")
        return cls._sanitize_primitive(data)


class ConfigManager(IConfigManager):
    """
    Concrete implementation of IConfigManager.
    Binds configuration persistence to config.json.
    """

    DEFAULT_CONFIG_PATH = Path("config.json")

    def __init__(self, config_file: Path = DEFAULT_CONFIG_PATH):
        self.config_file = config_file
        self.config = ConfigFactory.create_from_file(config_file)

    def load(self) -> None:
        """Reload configuration from file storage into current config instance."""
        loaded = ConfigFactory.create_from_file(self.config_file)
        sync_config(self.config, loaded)
        logger.info(f"Loaded config from '{self.config_file}'")

    def save(self) -> None:
        """Serialize and persist configuration tree to config.json."""
        try:
            data = ConfigFactory.serialize_to_dict(self.config)
            parent_dir = self.config_file.parent
            parent_dir.mkdir(parents=True, exist_ok=True)
            text = json.dumps(
                data,
                indent=2,
                default=lambda o: o.value if isinstance(o, Enum) else str(o),
            )
            self.config_file.write_text(text, encoding="utf-8")
            logger.debug(f"Saved config to '{self.config_file}'")
        except Exception as e:
            logger.error(f"Error saving config to '{self.config_file}': {e}")

    def get_app_settings(self) -> AppSettings:
        return self.config.app

    def set_app_settings(self, settings: AppSettings, auto_save: bool = True) -> None:
        self.config.app = settings
        if auto_save:
            self.save()

    def get_game_plugin_settings(self) -> GamePluginConfig:
        return self.config.game_plugin

    def set_game_plugin_settings(self, settings: GamePluginConfig, auto_save: bool = True) -> None:
        self.config.game_plugin = settings
        if auto_save:
            self.save()

    def get_logger_settings(self) -> LoggerSettings:
        return self.config.loggers

    def set_logger_settings(self, settings: LoggerSettings, auto_save: bool = True) -> None:
        self.config.loggers = settings
        if auto_save:
            self.save()

    def is_plugin_enabled(self, plugin_id: str, default: bool = True) -> bool:
        return self.config.is_plugin_enabled(plugin_id, default)

    def set_plugin_enabled(self, plugin_id: str, enabled: bool, auto_save: bool = True) -> None:
        self.config.set_plugin_enabled(plugin_id, bool(enabled))
        if auto_save:
            self.save()

    def get_plugin_config_as(self, plugin_id: str, dataclass_cls: Type[T]) -> T:
        raw_plugin_data = self.config.get_plugin_data(plugin_id)
        if not is_dataclass(dataclass_cls):
            return dataclass_cls()
        try:
            type_hints = typing.get_type_hints(dataclass_cls)
        except Exception:
            type_hints = {}
        valid_kwargs = {}
        for f in fields(dataclass_cls):
            if f.name in raw_plugin_data:
                val = raw_plugin_data[f.name]
                field_type = type_hints.get(f.name, f.type)
                if isinstance(field_type, type) and issubclass(field_type, Enum) and not isinstance(val, field_type):
                    try:
                        val = field_type(val)
                    except (ValueError, KeyError):
                        pass
                valid_kwargs[f.name] = val
        return dataclass_cls(**valid_kwargs)

    def set_plugin_config_from(self, plugin_id: str, dataclass_obj: object, auto_save: bool = True) -> None:
        serialized = ConfigFactory.serialize_plugin_data(dataclass_obj)
        self.config.set_plugin_data(plugin_id, serialized)
        if auto_save:
            self.save()
