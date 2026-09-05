"""
SimPulse SDK — Plugin Metadata, Lifecycle States & Layout Specifications.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Tuple, Any, Protocol, runtime_checkable, Union


@runtime_checkable
class ISize(Protocol):
    """Protocol for 2D size specifications (PEP 544). Compatible with QSize."""
    def width(self) -> float: ...
    def height(self) -> float: ...


@runtime_checkable
class IRect(Protocol):
    """Protocol for 2D rectangle geometry specifications (PEP 544). Compatible with QRectF."""
    def x(self) -> float: ...
    def y(self) -> float: ...
    def width(self) -> float: ...
    def height(self) -> float: ...


@dataclass(frozen=True)
class Size2D:
    """Pure Python fallback implementing ISize protocol."""
    _width: float = 0.0
    _height: float = 0.0

    def width(self) -> float:
        return self._width

    def height(self) -> float:
        return self._height


@dataclass(frozen=True)
class Rect2D:
    """Pure Python fallback implementing IRect protocol."""
    _x: float = 0.0
    _y: float = 0.0
    _width: float = 0.0
    _height: float = 0.0

    def x(self) -> float:
        return self._x

    def y(self) -> float:
        return self._y

    def width(self) -> float:
        return self._width

    def height(self) -> float:
        return self._height



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
    target_size: Union[ISize, Any]
    allocated_rect: Union[IRect, Any]
    z_index: int = 0


@dataclass(frozen=True)
class PluginErrorReport:
    """Structured report of a plugin execution error intercepted by circuit breaker."""
    plugin_id: str
    action_name: str
    error_message: str
    consecutive_error_count: int
    timestamp: float = field(default_factory=time.time)
