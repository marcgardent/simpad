"""
SimPad Qt6 Overlay State Machine & Contextual Visibility Engine.
Detects Game Scene (Desktop, Main Menu, Garage/Pause, On-Track Driving)
and dynamically manages HUD overlay visibility, always-on-top positioning, and focus transitions.
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from PySide6.QtCore import QObject, Signal, QTimer

from simpad_qt.core.game_process_watcher import GameStatus, GameFocusState
from simpad_qt.core.telemetry import VehicleSensors

logger = logging.getLogger("simpad.overlay_state_machine")


class GameSceneState(Enum):
    """Contextual simulator scene state."""
    DESKTOP = "desktop"                # Game is not running or not focused in foreground
    MAIN_MENU = "main_menu"            # Game is foreground, but in launcher/main menu (no session)
    GARAGE_PAUSE = "garage_pause"      # Game is foreground, session loaded, but in Garage/Pits/Setup/Pause/Replay
    ON_TRACK_DRIVING = "on_track"      # Game is foreground, vehicle is actively driving on track (in_realtime=True)


class OverlayDisplayMode(Enum):
    """User-configured overlay display policy."""
    AUTO = "auto"                      # Auto-show on track, auto-hide in garage/menu/desktop
    FORCE_VISIBLE = "force_visible"    # Always visible (for preview, debugging, setup)
    FORCE_HIDDEN = "force_hidden"      # Always hidden


@dataclass(frozen=True)
class OverlayStateSnapshot:
    """Strongly-typed snapshot of current game scene and overlay status."""
    scene: GameSceneState
    display_mode: OverlayDisplayMode
    is_overlay_visible: bool
    is_lmu_foreground: bool
    is_in_realtime: bool
    last_state_change_time: float = field(default_factory=time.time)


class OverlayStateMachine(QObject):
    """
    Contextual engine that evaluates game window focus and real-time telemetry flags
    to automatically determine whether the HUD Overlay should be visible.
    """

    scene_changed = Signal(object)              # GameSceneState
    overlay_visibility_changed = Signal(bool)  # is_visible
    snapshot_updated = Signal(object)          # OverlayStateSnapshot

    def __init__(
        self,
        display_mode: OverlayDisplayMode = OverlayDisplayMode.AUTO,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._display_mode: OverlayDisplayMode = display_mode
        self._current_scene: GameSceneState = GameSceneState.DESKTOP
        self._is_overlay_visible: bool = False

        self._latest_game_status = GameStatus(
            state=GameFocusState.NOT_RUNNING,
            is_running=False,
            is_foreground=False,
        )
        self._latest_sensors = VehicleSensors()
        self._last_telemetry_timestamp: float = 0.0

        # Watchdog monitor timer to detect telemetry stream stop (e.g. exit to main menu) (200ms / 5 Hz)
        self._monitor_timer = QTimer(self)
        self._monitor_timer.setInterval(200)
        self._monitor_timer.timeout.connect(self._evaluate_state)
        self._monitor_timer.start()

    @property
    def current_scene(self) -> GameSceneState:
        return self._current_scene

    @property
    def display_mode(self) -> OverlayDisplayMode:
        return self._display_mode

    @property
    def is_overlay_visible(self) -> bool:
        return self._is_overlay_visible

    def get_snapshot(self) -> OverlayStateSnapshot:
        return OverlayStateSnapshot(
            scene=self._current_scene,
            display_mode=self._display_mode,
            is_overlay_visible=self._is_overlay_visible,
            is_lmu_foreground=self._latest_game_status.is_foreground,
            is_in_realtime=self._latest_sensors.in_realtime,
        )

    def set_display_mode(self, mode: OverlayDisplayMode) -> None:
        """Set overlay policy (AUTO, FORCE_VISIBLE, FORCE_HIDDEN)."""
        if self._display_mode != mode:
            logger.info(f"Overlay display policy changed: {self._display_mode.value} -> {mode.value}")
            self._display_mode = mode
            self._evaluate_state()

    def update_game_status(self, status: GameStatus) -> None:
        """Handle game process / window focus updates."""
        self._latest_game_status = status
        self._evaluate_state()

    def update_telemetry(self, sensors: VehicleSensors) -> None:
        """Handle telemetry frame updates."""
        self._latest_sensors = sensors
        self._last_telemetry_timestamp = time.time()
        self._evaluate_state()

    def _evaluate_state(self) -> None:
        """Compute target GameSceneState and resulting overlay visibility."""
        is_fg = self._latest_game_status.is_foreground
        is_running = self._latest_game_status.is_running
        now = time.time()
        has_fresh_telemetry = (now - self._last_telemetry_timestamp) < 0.35 if self._last_telemetry_timestamp > 0 else False
        in_realtime = bool(self._latest_sensors.in_realtime) if has_fresh_telemetry else False

        # Determine Game Scene
        if not is_running or not is_fg:
            new_scene = GameSceneState.DESKTOP
        elif not has_fresh_telemetry:
            # Game is in foreground, but no physics datagrams are streaming -> Main Menu
            new_scene = GameSceneState.MAIN_MENU
        elif in_realtime:
            # Game is in foreground, telemetry is streaming, and vehicle is driving on track
            new_scene = GameSceneState.ON_TRACK_DRIVING
        else:
            # Game is in foreground, session is active, but vehicle is in garage/setup/pause/replay
            new_scene = GameSceneState.GARAGE_PAUSE

        # Determine Target Overlay Visibility based on policy
        if self._display_mode == OverlayDisplayMode.FORCE_VISIBLE:
            target_visible = True
        elif self._display_mode == OverlayDisplayMode.FORCE_HIDDEN:
            target_visible = False
        else:  # AUTO
            target_visible = (new_scene == GameSceneState.ON_TRACK_DRIVING)

        scene_changed = (new_scene != self._current_scene)
        visibility_changed = (target_visible != self._is_overlay_visible)

        if scene_changed:
            logger.info(f"Game Scene Transition: {self._current_scene.value} -> {new_scene.value}")
            self._current_scene = new_scene
            self.scene_changed.emit(new_scene)

        if visibility_changed:
            logger.info(f"HUD Overlay Visibility: {'VISIBLE' if target_visible else 'HIDDEN'} (Scene: {new_scene.value}, Mode: {self._display_mode.value})")
            self._is_overlay_visible = target_visible
            self.overlay_visibility_changed.emit(target_visible)

        if scene_changed or visibility_changed:
            self.snapshot_updated.emit(self.get_snapshot())
