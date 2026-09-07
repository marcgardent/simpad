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
from simpulse_sdk.models.view import TelemetryView
from simpulse_sdk.contracts.config import IPluginConfigProvider

TConfig = TypeVar("TConfig")


class PluginContext:
    """
    Execution context provided by the SimPulse Host to each plugin instance.
    Offers strongly-typed configuration mapping, host logging, and read-only
    access to the consolidated telemetry View (same façade handed to the
    polymorphic on_* state hooks) for use outside of those hooks — e.g. from
    on_load() or from a Studio tab widget built on demand.
    """

    def __init__(
        self,
        plugin_id: str,
        config_provider: IPluginConfigProvider,
        state_store: Optional[TelemetryStateStore] = None,
    ):
        self.plugin_id = plugin_id
        self._config_provider = config_provider
        self._state_store = state_store
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

    def get_state_view(self) -> TelemetryView:
        """
        Return the consolidated, immutable telemetry View (timing/grid/delta and
        cross-channel properties) — same frozen snapshot type handed to on_scoring_
        update()/on_grid_update()/etc. and to Engines. Falls back to the process-wide
        singleton when this context was constructed without an explicit store (e.g.
        in tests).
        """
        store = self._state_store or TelemetryStateStore.get_instance()
        return store.snapshot()


class SimPulsePlugin(ABC):
    """
    Base class for all SimPulse plugins.
    Defines lifecycle hooks and channel requirements (desiderata).

    The polymorphic ``on_*`` state hooks below take a ``TelemetryView`` — the
    read-only per-tick snapshot PluginManager.dispatch_packet hands every
    plugin. This is a real type constraint, not decoration: overriding one
    with a ``TelemetryStateStore`` parameter is a Liskov violation mypy will
    flag (incompatible override), because the runtime object really is a
    View unless the plugin opts out. A plugin that genuinely needs the live,
    mutable Store (e.g. a method that mutates shared state, like
    ``consume_validity_transition()``) must declare
    ``_REQUIRE_RAW_INGEST = True`` — this makes the dispatcher hand it the
    real TelemetryStateStore instead, and any override widening the
    parameter back to TelemetryStateStore should carry a
    ``# type: ignore[override]`` documenting exactly why (see
    RaceEngineerPlugin).
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
    def on_physics_tick(self, state: TelemetryView) -> None:
        """Called directly on high-frequency player physics tick (100-120Hz)."""
        pass

    def on_opponents_tick(self, state: TelemetryView) -> None:
        """Called directly on opponent vehicle dynamics tick (10-20Hz)."""
        pass

    def on_scoring_update(self, state: TelemetryView) -> None:
        """Called directly on compact scoring and timing update (10Hz)."""
        pass

    def on_grid_update(self, state: TelemetryView) -> None:
        """Called directly on full grid positions and session update (2-5Hz)."""
        pass

    def on_weather_update(self, state: TelemetryView) -> None:
        """Called directly on ambient and track weather condition update (~1Hz)."""
        pass

    def on_extended_state_update(self, state: TelemetryView) -> None:
        """Called directly on vehicle electronics, cockpit switches and flags update (5Hz)."""
        pass

    def on_session_event(self, state: TelemetryView) -> None:
        """Called directly on session / system event (green flag, penalty, sector records)."""
        pass

    def on_ffb_update(self, state: TelemetryView) -> None:
        """Called directly on force feedback telemetry frame."""
        pass

    def on_graphics_update(self, state: TelemetryView) -> None:
        """Called directly on camera / graphics telemetry frame."""
        pass

    def on_track_rules_update(self, state: TelemetryView) -> None:
        """Called directly on track rules, local yellows and safety car state."""
        pass

    def on_pit_menu_update(self, state: TelemetryView) -> None:
        """Called directly on pit strategy menu selection and adjustments."""
        pass
