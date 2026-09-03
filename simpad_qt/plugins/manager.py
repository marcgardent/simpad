"""
SimPad Qt6 Plugin Manager — Lifecycle, Discovery, Registry & Circuit Breaker.
Uses strongly-typed structures, Python dataclasses, and channel requirements negotiation.
"""

from __future__ import annotations
import importlib.util
import inspect
import logging
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, Signal

from simpad_qt.plugins.contracts import (
    SimPadPlugin,
    PluginState,
    PluginContext,
    PluginErrorReport,
    ITabProvider,
    ITelemetrySubscriber,
    IPacketSubscriber,
    IHudWidgetProvider,
)
from simpad_qt.core.config import ConfigManager
from simpad_qt.core.telemetry_channels import ChannelRequirement, TelemetryRawPacket
from src.telemetry.sensors import VehicleSensors


class PluginManager(QObject):
    """
    Central manager for discovering, loading, and managing the lifecycle of SimPad plugins.
    Includes an integrated circuit breaker to isolate faulty plugins from crashing the host application.
    """

    # Qt Signals
    plugin_loaded = Signal(str)                  # plugin_id
    plugin_unloaded = Signal(str)                # plugin_id
    plugin_state_changed = Signal(str, object)   # plugin_id, PluginState
    plugin_faulted = Signal(object)              # PluginErrorReport

    CIRCUIT_BREAKER_THRESHOLD = 5  # Max consecutive errors before auto-faulting

    def __init__(self, config_manager: ConfigManager, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.logger = logging.getLogger("simpad.plugin_manager")
        self.config_manager = config_manager

        self._plugins: Dict[str, SimPadPlugin] = {}
        self._error_counts: Dict[str, int] = {}
        self._plugin_paths: Dict[str, Path] = {}

    @property
    def plugins(self) -> Dict[str, SimPadPlugin]:
        """Return all registered plugin instances indexed by ID."""
        return dict(self._plugins)

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

    def _load_plugin_from_file(self, file_path: Path) -> Optional[SimPadPlugin]:
        """Dynamically import a Python file and instantiate any SimPadPlugin subclass found."""
        module_name = f"simpad_dyn_plugin_{file_path.stem}_{hash(str(file_path)) % 10000}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, str(file_path))
            if not spec or not spec.loader:
                self.logger.warning(f"Cannot create module spec for {file_path}")
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # Find subclasses of SimPadPlugin
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, SimPadPlugin) and obj is not SimPadPlugin:
                    plugin_instance: SimPadPlugin = obj()
                    self.register_plugin(plugin_instance, file_path)
                    return plugin_instance

        except Exception as e:
            self.logger.error(f"Failed to load plugin from {file_path}: {e}\n{traceback.format_exc()}")
            return None

        return None

    def register_plugin(self, plugin: SimPadPlugin, file_path: Optional[Path] = None) -> bool:
        """Register, initialize, and enable a plugin instance."""
        pid = plugin.metadata.id
        if pid in self._plugins:
            self.logger.warning(f"Plugin with ID '{pid}' is already registered. Overwriting.")

        self._plugins[pid] = plugin
        self._error_counts[pid] = 0
        if file_path:
            self._plugin_paths[pid] = file_path

        # Create execution context with strongly-typed config manager
        ctx = PluginContext(pid, self.config_manager)

        try:
            plugin.on_load(ctx)
            plugin.on_enable()
            self.logger.info(f"Loaded and enabled plugin: '{plugin.metadata.name}' (v{plugin.metadata.version}) [{pid}]")
            self.plugin_loaded.emit(pid)
            self.plugin_state_changed.emit(pid, PluginState.ENABLED)
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

    def enable_plugin(self, plugin_id: str) -> bool:
        """Enable a loaded or disabled plugin."""
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            return False

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

    def disable_plugin(self, plugin_id: str) -> bool:
        """Disable an enabled plugin."""
        plugin = self._plugins.get(plugin_id)
        if not plugin or plugin.state == PluginState.DISABLED:
            return False

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

    def dispatch_packet(self, packet: TelemetryRawPacket) -> None:
        """Dispatch a specific channel raw packet safely to all active IPacketSubscriber plugins."""
        for pid, p in list(self._plugins.items()):
            if p.state != PluginState.ENABLED or not isinstance(p, IPacketSubscriber):
                continue

            try:
                p.on_telemetry_packet(packet)
                self._error_counts[pid] = 0
            except Exception as e:
                self._handle_plugin_error(pid, "on_telemetry_packet", e)

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
