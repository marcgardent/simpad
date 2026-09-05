"""
SimPulse SDK — Plugin Metadata, Lifecycle States & Layout Specifications.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Tuple, Any


# TODO MGT jai bien l'impression que nous sommes sur un cas d'ecole pour utiliser: typing.Protocol (introduit via la PEP 544).

try:
    from PySide6.QtCore import QSize, QRectF
except ImportError:
    @dataclass(frozen=True)
    class QSize:  # type: ignore[no-redef]
        width: int = 0
        height: int = 0

    @dataclass(frozen=True)
    class QRectF:  # type: ignore[no-redef]
        x: float = 0.0
        y: float = 0.0
        width: float = 0.0
        height: float = 0.0


class HudSlot(str, Enum):
    """Predefined screen layout slots for HUD Overlay Compositor."""
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
    FAULTED = auto()


@dataclass(frozen=True)
class PluginMetadata:
    """Immutable metadata identifying a plugin."""
    id: str
    name: str
    version: str = "1.0.0"
    author: str = "SimPulse Developer"
    description: str = ""
    icon: str = "🏎️"
    tags: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class HudLayoutSpec:
    """Strongly-typed layout geometry allocated by the HUD Compositor."""
    slot: HudSlot
    target_size: Any  # QSize
    allocated_rect: Any  # QRectF
    z_index: int = 0


@dataclass(frozen=True)
class PluginErrorReport:
    """Structured report of a plugin execution error intercepted by circuit breaker."""
    plugin_id: str
    action_name: str
    error_message: str
    consecutive_error_count: int
    timestamp: float = field(default_factory=time.time)
