"""
SimPad Qt6 Game Process & Window Focus Watcher.
Monitors Le Mans Ultimate execution and foreground/background window state.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from PySide6.QtCore import QObject, Signal, QTimer

from src.utils.window_utils import (
    get_lmu_window_status,
    is_lmu_running,
    is_lmu_foreground,
    get_foreground_window_title,
    get_foreground_process_name,
)

logger = logging.getLogger("simpad.process_watcher")


class GameFocusState(Enum):
    """Execution and window focus status of the target game (LMU)."""
    NOT_RUNNING = "not_running"
    BACKGROUND = "background"
    FOREGROUND = "foreground"


@dataclass(frozen=True)
class GameStatus:
    """Strongly-typed status snapshot of the game process and window."""
    state: GameFocusState
    is_running: bool
    is_foreground: bool
    process_name: str = ""
    window_title: str = ""


class GameProcessWatcher(QObject):
    """
    Background timer-based watcher for game process and window focus transitions.
    Emits signals on state changes for the host status bar and overlay manager.
    """

    status_changed = Signal(object)  # GameStatus

    def __init__(self, poll_interval_ms: int = 500, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._current_status = GameStatus(
            state=GameFocusState.NOT_RUNNING,
            is_running=False,
            is_foreground=False,
        )

        try:
            from src.utils.window_utils import get_window_manager
            self._wm = get_window_manager()
            self._wm.add_focus_listener(self._on_wm_focus_event)
        except Exception:
            self._wm = None

        self._timer = QTimer(self)
        self._timer.setInterval(poll_interval_ms)
        self._timer.timeout.connect(self._poll_status)

    @property
    def current_status(self) -> GameStatus:
        return self._current_status

    def _on_wm_focus_event(self) -> None:
        """Reactive 0ms callback triggered by native window manager focus events."""
        self._poll_status()

    def start(self) -> None:
        """Start polling and monitoring window state."""
        self._poll_status()
        self._timer.start()

    def stop(self) -> None:
        """Stop polling and detach focus listener."""
        self._timer.stop()
        if self._wm:
            try:
                self._wm.remove_focus_listener(self._on_wm_focus_event)
            except Exception:
                pass

    def _poll_status(self) -> None:
        raw_status = get_lmu_window_status()
        running = raw_status != "not_running"
        foreground = raw_status == "foreground"

        state = GameFocusState.NOT_RUNNING
        if raw_status == "foreground":
            state = GameFocusState.FOREGROUND
        elif raw_status == "background":
            state = GameFocusState.BACKGROUND

        proc_name = get_foreground_process_name() if foreground else ("LeMansUltimate.exe" if running else "")
        win_title = get_foreground_window_title() if foreground else ""

        new_status = GameStatus(
            state=state,
            is_running=running,
            is_foreground=foreground,
            process_name=proc_name,
            window_title=win_title,
        )

        if new_status != self._current_status:
            self._current_status = new_status
            self.status_changed.emit(new_status)
