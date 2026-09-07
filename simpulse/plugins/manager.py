"""
SimPulse Qt6 Plugin Manager — Lifecycle, Discovery, Registry & Circuit Breaker.
Uses strongly-typed structures, Python dataclasses, and channel requirements negotiation.
"""

from __future__ import annotations
import types
import importlib.util
import inspect
import logging
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Any

from PySide6.QtCore import QObject, Signal
from simpulse.core.config import IConfigManager

from simpulse_sdk import (
    SimPulsePlugin,
    PluginState,
    PluginContext,
    PluginErrorReport,
    ITabProvider,
    ITelemetrySubscriber,
    IDeltaSubscriber,
    ITelemetryStateSubscriber,
    IChannelSampleSubscriber,
    IHudWidgetProvider,
    ChannelRequirement,
    TelemetryRawPacket,
    ChannelSample,
    TelemetryChannel,
    LapDeltaPacket,
    VehicleSensors,
    TelemetryStateStore,
    TelemetryPluginView,
)


class PluginManager(QObject):
    """
    Central manager for discovering, loading, and managing the lifecycle of SimPulse plugins.
    Includes an integrated circuit breaker to isolate faulty plugins from crashing the host application.
    """

    # Qt Signals
    plugin_loaded = Signal(str)                  # plugin_id
    plugin_unloaded = Signal(str)                # plugin_id
    plugin_state_changed = Signal(str, object)   # plugin_id, PluginState
    plugin_faulted = Signal(object)              # PluginErrorReport

    CIRCUIT_BREAKER_THRESHOLD = 5  # Max consecutive errors before auto-faulting

    def __init__(self, config_manager: IConfigManager, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.logger = logging.getLogger("simpulse.plugin_manager")
        self.config_manager = config_manager

        self._plugins: Dict[str, SimPulsePlugin] = {}
        self._error_counts: Dict[str, int] = {}
        self._plugin_paths: Dict[str, Path] = {}
        self._load_errors: Dict[Path, str] = {}

    @property
    def plugins(self) -> Dict[str, SimPulsePlugin]:
        """Return all registered plugin instances indexed by ID."""
        return dict(self._plugins)

    @property
    def load_errors(self) -> Dict[Path, str]:
        """Return all recorded errors encountered when loading plugins."""
        return dict(self._load_errors)

    def discover_and_load(self, search_directories: List[Path]) -> None:
        """Scan specified directories for plugin modules and load them."""
        for dir_path in search_directories:
            if not dir_path.exists() or not dir_path.is_dir():
                continue

            self.logger.info(f"Scanning directory for plugins: {dir_path}")

            for path in dir_path.iterdir():
                target_file: Optional[Path] = None
                if path.is_dir():
                    candidate = path / "plugin.py"
                    if candidate.exists():
                        target_file = candidate
                elif path.is_file() and path.suffix == ".py" and not path.name.startswith("__"):
                    target_file = path

                if target_file:
                    self._load_plugin_from_file(target_file)

    def _load_plugin_from_file(self, file_path: Path) -> Optional[SimPulsePlugin]:
        """Dynamically import a Python file and instantiate any SimPulsePlugin subclass found."""
        resolved_path = file_path.resolve()
        module = None

        try:
            # 1. Attempt to import via sys.path if module resides in an existing package hierarchy
            for p in sys.path:
                try:
                    base_path = Path(p).resolve()
                    if resolved_path.is_relative_to(base_path):
                        rel_parts = resolved_path.relative_to(base_path).with_suffix("").parts
                        if all(part.isidentifier() for part in rel_parts):
                            full_mod_name = ".".join(rel_parts)
                            module = importlib.import_module(full_mod_name)
                            break
                except Exception:
                    continue

            # 2. If not in sys.path or standard import failed, load dynamically with package support
            if module is None:
                parent_dir = resolved_path.parent
                is_package_member = (
                    resolved_path.name == "plugin.py"
                    or (parent_dir / "__init__.py").exists()
                )

                if is_package_member:
                    pkg_name = f"simpulse_dyn_pkg_{parent_dir.name}_{abs(hash(str(parent_dir))) % 10000}"
                    if pkg_name not in sys.modules:
                        pkg_mod = types.ModuleType(pkg_name)
                        pkg_mod.__path__ = [str(parent_dir)]
                        init_file = parent_dir / "__init__.py"
                        pkg_mod.__file__ = str(init_file) if init_file.exists() else None
                        pkg_mod.__package__ = pkg_name
                        sys.modules[pkg_name] = pkg_mod

                    mod_name = f"{pkg_name}.{resolved_path.stem}"
                    spec = importlib.util.spec_from_file_location(mod_name, str(resolved_path))
                    if not spec or not spec.loader:
                        self.logger.warning(f"Cannot create module spec for {file_path}")
                        return None
                    module = importlib.util.module_from_spec(spec)
                    module.__package__ = pkg_name
                    sys.modules[mod_name] = module
                    spec.loader.exec_module(module)
                else:
                    mod_name = f"simpulse_dyn_plugin_{resolved_path.stem}_{abs(hash(str(resolved_path))) % 10000}"
                    spec = importlib.util.spec_from_file_location(mod_name, str(resolved_path))
                    if not spec or not spec.loader:
                        self.logger.warning(f"Cannot create module spec for {file_path}")
                        return None
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[mod_name] = module
                    spec.loader.exec_module(module)

            # Find subclasses of SimPulsePlugin
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, SimPulsePlugin) and obj is not SimPulsePlugin:
                    plugin_instance: SimPulsePlugin = obj()
                    self.register_plugin(plugin_instance, file_path)
                    self._load_errors.pop(file_path, None)
                    return plugin_instance

        except Exception as e:
            tb = traceback.format_exc()
            self._load_errors[file_path] = f"{e}\n{tb}"
            self.logger.error(f"Failed to load plugin from {file_path}: {e}\n{tb}")
            return None

        return None

    def register_plugin(self, plugin: SimPulsePlugin, file_path: Optional[Path] = None) -> bool:
        """Register, initialize, and activate/deactivate a plugin instance based on saved config."""
        pid = plugin.metadata.id
        if pid in self._plugins:
            self.logger.warning(f"Plugin with ID '{pid}' is already registered. Overwriting.")

        self._plugins[pid] = plugin
        self._error_counts[pid] = 0
        if file_path:
            self._plugin_paths[pid] = file_path

        # Create execution context with strongly-typed config manager and the
        # consolidated telemetry View (ctx.get_state_view()) for use outside the
        # polymorphic on_* state hooks.
        ctx = PluginContext(pid, self.config_manager, state_store=TelemetryStateStore.get_instance())

        try:
            plugin.on_load(ctx)

            # Check if plugin is enabled in saved configuration (defaults to True)
            is_enabled = True
            if self.config_manager:
                is_enabled = self.config_manager.is_plugin_enabled(pid, default=True)

            if is_enabled:
                plugin.on_enable()
                self.logger.info(f"Loaded and enabled plugin: '{plugin.metadata.name}' (v{plugin.metadata.version}) [{pid}]")
                self.plugin_loaded.emit(pid)
                self.plugin_state_changed.emit(pid, PluginState.ENABLED)
            else:
                plugin.state = PluginState.DISABLED
                self.logger.info(f"Loaded plugin (disabled in configuration): '{plugin.metadata.name}' (v{plugin.metadata.version}) [{pid}]")
                self.plugin_loaded.emit(pid)
                self.plugin_state_changed.emit(pid, PluginState.DISABLED)
            return True
        except Exception as e:
            self.logger.error(f"Error during on_load for plugin '{pid}': {e}\n{traceback.format_exc()}")
            plugin.state = PluginState.FAULTED
            report = PluginErrorReport(
                plugin_id=pid,
                action_name="on_load",
                error_message=str(e),
                consecutive_error_count=1
            )
            self.plugin_faulted.emit(report)
            return False

    def enable_plugin(self, plugin_id: str, save_config: bool = True) -> bool:
        """Enable a loaded or disabled plugin and persist state to configuration."""
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            return False

        if save_config and self.config_manager:
            self.config_manager.set_plugin_enabled(plugin_id, True)

        if plugin.state == PluginState.ENABLED:
            return True

        try:
            self._error_counts[plugin_id] = 0
            plugin.on_enable()
            self.logger.info(f"Enabled plugin '{plugin_id}'")
            self.plugin_state_changed.emit(plugin_id, PluginState.ENABLED)
            return True
        except Exception as e:
            self.logger.error(f"Error enabling plugin '{plugin_id}': {e}")
            plugin.state = PluginState.FAULTED
            report = PluginErrorReport(
                plugin_id=plugin_id,
                action_name="on_enable",
                error_message=str(e),
                consecutive_error_count=1
            )
            self.plugin_faulted.emit(report)
            return False

    def disable_plugin(self, plugin_id: str, save_config: bool = True) -> bool:
        """Disable an enabled plugin and persist state to configuration."""
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            return False

        if save_config and self.config_manager:
            self.config_manager.set_plugin_enabled(plugin_id, False)

        if plugin.state == PluginState.DISABLED:
            return True

        try:
            plugin.on_disable()
            self.logger.info(f"Disabled plugin '{plugin_id}'")
            self.plugin_state_changed.emit(plugin_id, PluginState.DISABLED)
            return True
        except Exception as e:
            self.logger.error(f"Error disabling plugin '{plugin_id}': {e}")
            return False

    def unload_all(self) -> None:
        """Unload all registered plugins."""
        for pid, plugin in list(self._plugins.items()):
            try:
                if plugin.state == PluginState.ENABLED:
                    plugin.on_disable()
                plugin.on_unload()
                self.plugin_unloaded.emit(pid)
            except Exception as e:
                self.logger.error(f"Error unloading plugin '{pid}': {e}")
        self._plugins.clear()

    # =========================================================================
    # Channel Requirements (Desiderata)
    # =========================================================================

    def get_all_channel_requirements(self) -> Dict[str, List[ChannelRequirement]]:
        """Collect all declared telemetry channel requirements from active plugins."""
        reqs: Dict[str, List[ChannelRequirement]] = {}
        for pid, p in self._plugins.items():
            if p.state == PluginState.ENABLED:
                plugin_reqs = p.get_channel_requirements()
                if plugin_reqs:
                    reqs[pid] = plugin_reqs
        return reqs

    # =========================================================================
    # Capability Filtering & Safe Dispatch
    # =========================================================================

    def get_tab_providers(self) -> List[ITabProvider]:
        """Return all active plugins implementing ITabProvider."""
        providers = []
        for p in self._plugins.values():
            if p.state == PluginState.ENABLED and isinstance(p, ITabProvider):
                providers.append(p)
        return providers

    def get_hud_providers(self) -> List[IHudWidgetProvider]:
        """Return all active plugins implementing IHudWidgetProvider."""
        providers = []
        for p in self._plugins.values():
            if p.state == PluginState.ENABLED and isinstance(p, IHudWidgetProvider):
                if p.is_hud_visible():
                    providers.append(p)
        return providers

    def get_delta_subscribers(self) -> List[IDeltaSubscriber]:
        """Return all active plugins implementing IDeltaSubscriber."""
        return [
            p for p in self._plugins.values()
            if p.state == PluginState.ENABLED and isinstance(p, IDeltaSubscriber)
        ]

    def connect_telemetry_bus(self, telemetry_bus: Any) -> None:
        """Connect this PluginManager's dispatch handlers to TelemetryBus signals."""
        telemetry_bus.packet_received.connect(self.dispatch_packet)
        telemetry_bus.telemetry_updated.connect(self.dispatch_telemetry)
        telemetry_bus.delta_updated.connect(self.dispatch_delta)

    def disconnect_telemetry_bus(self, telemetry_bus: Any) -> None:
        """Disconnect this PluginManager's dispatch handlers from TelemetryBus signals."""
        for sig, slot in [
            (telemetry_bus.packet_received, self.dispatch_packet),
            (telemetry_bus.telemetry_updated, self.dispatch_telemetry),
            (telemetry_bus.delta_updated, self.dispatch_delta),
        ]:
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def dispatch_telemetry(self, sensors: VehicleSensors) -> None:
        """Dispatch a telemetry frame safely to all active subscribers."""
        for pid, p in list(self._plugins.items()):
            if p.state != PluginState.ENABLED or not isinstance(p, ITelemetrySubscriber):
                continue

            try:
                p.on_telemetry_frame(sensors)
                self._error_counts[pid] = 0  # Reset error count on success
            except Exception as e:
                self._handle_plugin_error(pid, "on_telemetry_frame", e)

    def dispatch_delta(self, delta_packet: LapDeltaPacket) -> None:
        """Dispatch an authoritative LapDeltaPacket safely to all active IDeltaSubscriber plugins."""
        for pid, p in list(self._plugins.items()):
            if p.state != PluginState.ENABLED or not isinstance(p, IDeltaSubscriber):
                continue

            try:
                p.on_delta_frame(delta_packet)
                self._error_counts[pid] = 0
            except Exception as e:
                self._handle_plugin_error(pid, "on_delta_frame", e)

    # Declarative channel dispatch routing: (store_update_method, plugin_hook_name)
    CHANNEL_ROUTING: Dict[TelemetryChannel, Tuple[str, str]] = {
        TelemetryChannel.TELEMETRY: ("update_telemetry", "on_physics_tick"),
        TelemetryChannel.OPPONENT_TELEMETRY: ("update_opponent_telemetry", "on_opponents_tick"),
        TelemetryChannel.COMPACT_SCORING: ("update_compact_scoring", "on_scoring_update"),
        TelemetryChannel.FULL_SCORING: ("update_full_scoring", "on_grid_update"),
        TelemetryChannel.WEATHER: ("update_weather", "on_weather_update"),
        TelemetryChannel.EXTENDED_STATE: ("update_extended_state", "on_extended_state_update"),
        TelemetryChannel.SYSTEM_EVENTS: ("update_system_events", "on_session_event"),
        TelemetryChannel.FORCE_FEEDBACK: ("update_force_feedback", "on_ffb_update"),
        TelemetryChannel.GRAPHICS: ("update_graphics", "on_graphics_update"),
        TelemetryChannel.TRACK_RULES: ("update_track_rules", "on_track_rules_update"),
        TelemetryChannel.PIT_MENU: ("update_pit_menu", "on_pit_menu_update"),
    }

    def dispatch_packet(self, packet: TelemetryRawPacket) -> None:
        """
        Ingests a specific channel raw packet into the central TelemetryStateStore
        and dispatches polymorphic typed on_* event hooks.
        Pure O(1) table-driven dispatch: zero if/elif ladder.
        """
        if packet.data is None:
            return

        route = self.CHANNEL_ROUTING.get(packet.channel)
        if route is None:
            return

        store = TelemetryStateStore.get_instance()
        store_method_name, plugin_hook_name = route

        # 1. Update State Store via direct method lookup
        store_method = getattr(store, store_method_name, None)
        if store_method is not None:
            store_method(packet.data, packet.timestamp, packet.raw_bytes_len)

        # 1b. Metadata-only channel sample to IChannelSampleSubscriber plugins.
        # Deliberately carries NO decoded payload: diagnostics plugins measure Hz/bytes
        # without ever receiving consolidated or raw UDP data.
        sample = ChannelSample(
            channel=packet.channel,
            raw_bytes_len=packet.raw_bytes_len,
            timestamp=packet.timestamp,
        )
        for pid, p in list(self._plugins.items()):
            if p.state != PluginState.ENABLED or not isinstance(p, IChannelSampleSubscriber):
                continue
            try:
                p.on_channel_sample(sample)
                self._error_counts[pid] = 0
            except Exception as e:
                self._handle_plugin_error(pid, "on_channel_sample", e)

        # 2. Dispatch polymorphic on_* hook to enabled plugins.
        # Plugins see the consolidated view; raw-UDP ingress is granted only to the
        # handful of ingest-layer plugins that declare _REQUIRE_RAW_INGEST explicitly.
        for pid, p in list(self._plugins.items()):
            if p.state != PluginState.ENABLED:
                continue

            hook = getattr(p, plugin_hook_name, None)
            if hook is not None:
                try:
                    if getattr(p, "_REQUIRE_RAW_INGEST", False):
                        hook(store)
                    else:
                        hook(TelemetryPluginView(store))
                    self._error_counts[pid] = 0
                except Exception as e:
                    self._handle_plugin_error(pid, plugin_hook_name, e)

    def _handle_plugin_error(self, plugin_id: str, action: str, error: Exception) -> None:
        """Record error and trip the circuit breaker if threshold is exceeded."""
        self._error_counts[plugin_id] = self._error_counts.get(plugin_id, 0) + 1
        count = self._error_counts[plugin_id]
        err_msg = f"Plugin '{plugin_id}' raised exception in {action}: {error}"
        self.logger.warning(f"{err_msg} (error {count}/{self.CIRCUIT_BREAKER_THRESHOLD})")

        if count >= self.CIRCUIT_BREAKER_THRESHOLD:
            self.logger.critical(f"Circuit Breaker TRIPPED for plugin '{plugin_id}'. Auto-disabling.")
            plugin = self._plugins.get(plugin_id)
            if plugin:
                try:
                    plugin.on_disable()
                except Exception:
                    pass
                plugin.state = PluginState.FAULTED
                report = PluginErrorReport(
                    plugin_id=plugin_id,
                    action_name=action,
                    error_message=str(error),
                    consecutive_error_count=count
                )
                self.plugin_faulted.emit(report)
                self.plugin_state_changed.emit(plugin_id, PluginState.FAULTED)
