"""
SimPad Qt6 Strongly-Typed Configuration Model.
Uses Python dataclasses for robust schema validation and serialization.
"""

from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field, asdict, is_dataclass
from pathlib import Path
from typing import Dict, Any, Type, TypeVar

logger = logging.getLogger("simpad.config")

T = TypeVar("T")


@dataclass
class AppSettings:
    """Core application settings."""
    dark_theme: bool = True
    target_fps: int = 60
    overlay_enabled: bool = True
    mock_telemetry: bool = False
    hud_debug_boxes: bool = False


@dataclass
class SimPadQtConfig:
    """Root configuration data structure."""
    app: AppSettings = field(default_factory=AppSettings)
    plugins: Dict[str, Dict[str, Any]] = field(default_factory=dict)


class ConfigManager:
    """Manages strongly-typed configuration persistence to JSON."""

    DEFAULT_CONFIG_PATH = Path("config_qt.json")

    def __init__(self, config_file: Path = DEFAULT_CONFIG_PATH):
        self.config_file = config_file
        self.config: SimPadQtConfig = SimPadQtConfig()
        self.load()

    def load(self) -> None:
        """Load and deserialize configuration from JSON."""
        if not self.config_file.exists():
            logger.info(f"Config file '{self.config_file}' not found. Initialized defaults.")
            return

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
                if isinstance(raw_data, dict):
                    app_dict = raw_data.get("app", {})
                    app_settings = AppSettings(**{
                        k: v for k, v in app_dict.items() if k in AppSettings.__dataclass_fields__
                    })
                    plugins_dict = raw_data.get("plugins", {})
                    self.config = SimPadQtConfig(app=app_settings, plugins=plugins_dict)
            logger.info(f"Successfully loaded strongly-typed config from '{self.config_file}'")
        except Exception as e:
            logger.error(f"Error loading config file '{self.config_file}': {e}")
            self.config = SimPadQtConfig()

    def save(self) -> None:
        """Serialize strongly-typed config to JSON."""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(asdict(self.config), f, indent=2)
            logger.debug(f"Saved config to '{self.config_file}'")
        except Exception as e:
            logger.error(f"Error saving config to '{self.config_file}': {e}")

    def get_plugin_config_as(self, plugin_id: str, dataclass_cls: Type[T]) -> T:
        """Instantiate a strongly-typed dataclass from persisted plugin configuration."""
        raw_plugin_data = self.config.plugins.get(plugin_id, {})
        fields = getattr(dataclass_cls, "__dataclass_fields__", {})
        valid_kwargs = {k: v for k, v in raw_plugin_data.items() if k in fields}
        return dataclass_cls(**valid_kwargs)

    def set_plugin_config_from(self, plugin_id: str, dataclass_obj: Any, auto_save: bool = True) -> None:
        """Store a strongly-typed dataclass into plugin configuration and optionally persist."""
        if is_dataclass(dataclass_obj):
            serialized = asdict(dataclass_obj)
        elif isinstance(dataclass_obj, dict):
            serialized = dataclass_obj
        else:
            raise TypeError(f"Expected dataclass or dict, got {type(dataclass_obj)}")

        self.config.plugins[plugin_id] = serialized
        if auto_save:
            self.save()
