"""
SimPulse SDK — Plugin Base Class & Execution Context.
"""

from __future__ import annotations
import logging
from abc import ABC
from typing import Optional, List, Type, TypeVar

from simpulse_sdk.models.plugin_metadata import PluginMetadata, PluginState
from simpulse_sdk.models.telemetry import ChannelRequirement
from simpulse_sdk.models.state_store import TelemetryStateStore
from simpulse_sdk.contracts.config import IPluginConfigProvider

TConfig = TypeVar("TConfig")


class PluginContext:
    """
    Execution context provided by the SimPulse Host to each plugin instance.
    Offers strongly-typed configuration mapping and host logging.
    """

    def __init__(self, plugin_id: str, config_provider: IPluginConfigProvider):
        self.plugin_id = plugin_id
        self._config_provider = config_provider
        self.logger = logging.getLogger(f"simpulse.plugin.{plugin_id}")

    def get_typed_config(self, dataclass_cls: Type[TConfig]) -> TConfig:
        """
        Retrieve configuration deserialized directly into a strongly-typed dataclass.
        Falls back to dataclass default values if key is missing or not set.
        """
        return self._config_provider.get_plugin_config_as(self.plugin_id, dataclass_cls)

    def save_typed_config(self, config_obj: object, auto_save: bool = True) -> None:
        """Persist a strongly-typed dataclass configuration."""
        self._config_provider.set_plugin_config_from(self.plugin_id, config_obj, auto_save=auto_save)


class SimPulsePlugin(ABC):
    """
    Base class for all SimPulse plugins.
    Defines lifecycle hooks and channel requirements (desiderata).
    """

    def __init__(self, metadata: PluginMetadata):
        self.metadata = metadata
        self.context: Optional[PluginContext] = None
        self.state: PluginState = PluginState.UNLOADED

    def get_channel_requirements(self) -> List[ChannelRequirement]:
        """
        Declare the telemetry channels and preferred frequencies (Hz) required by this plugin.
        The host aggregates requirements from all plugins to configure the game telemetry plugin.
        """
        return []

    def on_load(self, context: PluginContext) -> None:
        """Called when the plugin is loaded into the host."""
        self.context = context
        self.state = PluginState.LOADED

    def on_unload(self) -> None:
        """Called before the plugin is unloaded. Cleanup any resources here."""
        self.state = PluginState.UNLOADED

    def on_enable(self) -> None:
        """Called when the plugin is activated by the user or host."""
        self.state = PluginState.ENABLED

    def on_disable(self) -> None:
        """Called when the plugin is deactivated."""
        self.state = PluginState.DISABLED

    # Polymorphic Telemetry State Event Hooks
    def on_physics_tick(self, state: TelemetryStateStore) -> None:
        pass

    def on_scoring_update(self, state: TelemetryStateStore) -> None:
        pass

    def on_grid_update(self, state: TelemetryStateStore) -> None:
        pass

    def on_weather_update(self, state: TelemetryStateStore) -> None:
        pass

    def on_session_event(self, state: TelemetryStateStore) -> None:
        pass
