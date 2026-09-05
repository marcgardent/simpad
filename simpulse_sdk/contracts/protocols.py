"""
SimPulse SDK — Plugin Capability Protocols.
Plugins implement only the protocols they require.
"""

from __future__ import annotations
from typing import Optional, Protocol, runtime_checkable, Any

from simpulse_sdk.models.telemetry import VehicleSensors, TelemetryRawPacket
from simpulse_sdk.models.delta import LapDeltaPacket
from simpulse_sdk.models.state_store import TelemetryStateStore
from simpulse_sdk.models.plugin_metadata import HudSlot


@runtime_checkable
class ITelemetrySubscriber(Protocol):
    """
    Capability: The plugin receives live normalized VehicleSensors telemetry frames.
    """

    def on_telemetry_frame(self, sensors: VehicleSensors) -> None:
        """
        Called on every high-level telemetry frame (typically 20-60 Hz).
        """
        ...


@runtime_checkable
class IDeltaSubscriber(Protocol):
    """
    Capability: The plugin receives authoritative lap delta and timing data packets.
    """

    def on_delta_frame(self, delta_packet: LapDeltaPacket) -> None:
        """
        Called on every lap delta & timing evaluation (typically 20-100 Hz).
        """
        ...


@runtime_checkable
class IPacketSubscriber(Protocol):
    """
    Capability: The plugin receives individual raw decoded packets for specific channels.
    """

    def on_telemetry_packet(self, packet: TelemetryRawPacket) -> None:
        """
        Called whenever a specific raw channel packet arrives.
        """
        ...


@runtime_checkable
class ITelemetryStateSubscriber(Protocol):
    """
    Capability: The plugin receives unified TelemetryStateStore updates via polymorphic event hooks.
    """

    def on_physics_tick(self, state: TelemetryStateStore) -> None:
        ...

    def on_scoring_update(self, state: TelemetryStateStore) -> None:
        ...

    def on_grid_update(self, state: TelemetryStateStore) -> None:
        ...

    def on_weather_update(self, state: TelemetryStateStore) -> None:
        ...

    def on_session_event(self, state: TelemetryStateStore) -> None:
        ...


@runtime_checkable
class ITabProvider(Protocol):
    """
    Capability: The plugin contributes an interactive Tab in the main Studio Console.
    """

    def get_tab_title(self) -> str:
        """Return user-facing title displayed on tab header."""
        ...

    def get_tab_icon(self) -> str:
        """Return an emoji or icon identifier."""
        ...

    def create_tab_widget(self, parent: Optional[Any] = None) -> Any:
        """Create and return the widget (e.g. QWidget) to display inside tab."""
        ...


@runtime_checkable
class IHudWidgetProvider(Protocol):
    """
    Capability: The plugin renders a graphical widget on the HUD overlay.
    """

    @property
    def preferred_slot(self) -> HudSlot:
        """The preferred screen slot on the HUD canvas."""
        ...

    def get_hud_size(self) -> Any:
        """Return target rendering size (width, height) in logical pixels (e.g. QSize)."""
        ...

    def is_hud_visible(self) -> bool:
        """Return whether HUD overlay element is currently enabled and visible."""
        ...

    def paint_hud(
        self,
        painter: Any,
        width: float,
        height: float,
        sensors: VehicleSensors,
    ) -> None:
        """
        Vector rendering routine called by HUD Compositor.
        """
        ...
