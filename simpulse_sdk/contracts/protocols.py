"""
SimPulse SDK — Plugin Capability Protocols.
Plugins implement only the protocols they require.
"""

from __future__ import annotations
from typing import Optional, Protocol, runtime_checkable, Any

from simpulse_sdk.models.telemetry import VehicleSensors, ChannelSample
from simpulse_sdk.models.delta import LapDeltaPacket
from simpulse_sdk.models.view import TelemetryView
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
class ITelemetryStateSubscriber(Protocol):
    """
    Capability: The plugin receives unified, immutable TelemetryView updates via polymorphic event hooks.
    Every telemetry channel has a 1-to-1 dedicated strongly-typed on_* hook.
    """

    def on_physics_tick(self, view: TelemetryView) -> None:
        """Called directly on high-frequency player physics tick (100-120Hz)."""
        ...

    def on_opponents_tick(self, view: TelemetryView) -> None:
        """Called directly on opponent vehicle dynamics tick (10-20Hz)."""
        ...

    def on_scoring_update(self, view: TelemetryView) -> None:
        """Called directly on compact scoring and timing update (10Hz)."""
        ...

    def on_grid_update(self, view: TelemetryView) -> None:
        """Called directly on full grid positions and session update (2-5Hz)."""
        ...

    def on_weather_update(self, view: TelemetryView) -> None:
        """Called directly on ambient and track weather condition update (~1Hz)."""
        ...

    def on_extended_state_update(self, view: TelemetryView) -> None:
        """Called directly on vehicle electronics, cockpit switches and flags update (5Hz)."""
        ...

    def on_session_event(self, view: TelemetryView) -> None:
        """Called directly on session / system event (green flag, penalty, sector records)."""
        ...

    def on_ffb_update(self, view: TelemetryView) -> None:
        """Called directly on force feedback telemetry frame."""
        ...

    def on_graphics_update(self, view: TelemetryView) -> None:
        """Called directly on camera / graphics telemetry frame."""
        ...

    def on_track_rules_update(self, view: TelemetryView) -> None:
        """Called directly on track rules, local yellows and safety car state."""
        ...

    def on_pit_menu_update(self, view: TelemetryView) -> None:
        """Called directly on pit strategy menu selection and adjustments."""
        ...


@runtime_checkable
class IChannelSampleSubscriber(Protocol):
    """
    Low-level monitoring capability: receives a metadata-only sample per raw frame.

    This is the ONLY sanctioned way for diagnostics/monitor plugins to observe raw
    UDP flow (channel, byte length, timestamp) without any access to decoded packets.
    """

    def on_channel_sample(self, sample: "ChannelSample") -> None:
        """Called once per decoded UDP frame with metadata only (no payload)."""
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
