"""
SimPad Qt6 Plugin System — Contracts, Interfaces & Strongly-Typed Structures.

Defines the core protocols, lifecycle abstractions, data structures, and channel desiderata
used by all SimPad Qt6 plugins.
"""

from __future__ import annotations
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict, is_dataclass
from enum import Enum, auto
from typing import Dict, Any, Optional, Tuple, Protocol, TypeVar, Type, List, runtime_checkable

from PySide6.QtCore import QSize, QRectF
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget

# Import normalized telemetry domain model
from src.telemetry.sensors import VehicleSensors
from simpad_qt.core.telemetry_channels import (
    TelemetryChannel, ChannelRequirement, ChannelMetrics, TelemetryRawPacket
)

TConfig = TypeVar("TConfig")


class HudSlot(Enum):
    """Predefined screen layout slots for the HUD Overlay Compositor."""
    TOP_LEFT = "top_left"
    TOP_CENTER = "top_center"
    TOP_RIGHT = "top_right"
    CENTER = "center"
    COCKPIT_CENTER = "cockpit_center"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_CENTER = "bottom_center"
    BOTTOM_RIGHT = "bottom_right"
    CUSTOM = "custom"


class PluginState(Enum):
    """Lifecycle state of a plugin."""
    UNLOADED = auto()
    LOADED = auto()
    ENABLED = auto()
    DISABLED = auto()
    FAULTED = auto()  # Disabled by circuit breaker due to unhandled exceptions


@dataclass(frozen=True)
class PluginMetadata:
    """Immutable metadata identifying a plugin."""
    id: str
    name: str
    version: str = "1.0.0"
    author: str = "SimPad Developer"
    description: str = ""
    icon: str = "🏎️"
    tags: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class HudLayoutSpec:
    """Strongly-typed layout geometry allocated by the HUD Compositor."""
    slot: HudSlot
    target_size: QSize
    allocated_rect: QRectF
    z_index: int = 0


@dataclass(frozen=True)
class PluginErrorReport:
    """Structured report of a plugin execution error intercepted by the circuit breaker."""
    plugin_id: str
    action_name: str
    error_message: str
    consecutive_error_count: int
    timestamp: float = field(default_factory=time.time)


class PluginContext:
    """
    Execution context provided by SimPad Core to each plugin instance.
    Offers strongly-typed configuration mapping and host logging.
    """

    def __init__(self, plugin_id: str, config_manager: Any):
        self.plugin_id = plugin_id
        self._config_manager = config_manager
        self.logger = logging.getLogger(f"simpad.plugin.{plugin_id}")

    def get_typed_config(self, dataclass_cls: Type[TConfig]) -> TConfig:
        """
        Retrieve configuration deserialized directly into a strongly-typed dataclass.
        Falls back to dataclass default values if key is missing or not set.
        """
        return self._config_manager.get_plugin_config_as(self.plugin_id, dataclass_cls)

    def save_typed_config(self, config_obj: Any, auto_save: bool = True) -> None:
        """Persist a strongly-typed dataclass configuration."""
        self._config_manager.set_plugin_config_from(self.plugin_id, config_obj, auto_save=auto_save)


class SimPadPlugin(ABC):
    """
    Base class for all SimPad plugins.
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


# =====================================================================
# Plugin Capability Protocols
# =====================================================================

@runtime_checkable
class ITabProvider(Protocol):
    """
    Capability: The plugin contributes an interactive Tab in the main Qt6 Studio Console.
    """

    def get_tab_title(self) -> str:
        """Return the user-facing title displayed on the tab header."""
        ...

    def get_tab_icon(self) -> str:
        """Return an emoji or icon identifier."""
        ...

    def create_tab_widget(self, parent: Optional[QWidget] = None) -> QWidget:
        """Create and return the Qt6 QWidget to display inside the tab."""
        ...


@runtime_checkable
class ITelemetrySubscriber(Protocol):
    """
    Capability: The plugin receives live normalized VehicleSensors telemetry frames.
    """

    def on_telemetry_frame(self, sensors: VehicleSensors) -> None:
        """
        Called on every high-level telemetry frame (typically 20-60 Hz).
        Must execute quickly without blocking the main event loop.
        """
        ...


@runtime_checkable
class IPacketSubscriber(Protocol):
    """
    Capability: The plugin receives individual raw decoded packets for specific channels.
    """

    def on_telemetry_packet(self, packet: TelemetryRawPacket) -> None:
        """
        Called whenever a specific raw channel packet arrives (TelemInfo, CompactScoring, FullScoring, Weather, etc.).
        """
        ...


@runtime_checkable
class IHudWidgetProvider(Protocol):
    """
    Capability: The plugin renders a graphical widget on the transparent Qt HUD overlay.
    """

    @property
    def preferred_slot(self) -> HudSlot:
        """The preferred screen slot on the HUD canvas."""
        ...

    def get_hud_size(self) -> QSize:
        """Return the target rendering size (width, height) in logical pixels."""
        ...

    def is_hud_visible(self) -> bool:
        """Return whether the HUD overlay element is currently enabled and visible."""
        ...

    def paint_hud(
        self,
        painter: QPainter,
        width: float,
        height: float,
        sensors: VehicleSensors,
    ) -> None:
        """
        Vector rendering routine called by the HUD Compositor at 60/120 FPS.
        The painter is already translated to the assigned slot's local origin (0, 0).
        """
        ...
