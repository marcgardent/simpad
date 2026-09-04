"""
SimPad Qt6 Game Process & Window Focus Watcher.
Monitors Le Mans Ultimate execution and foreground/background window state.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import threading
from PySide6.QtCore import QObject, Signal

from simpad_qt.core.utils.window_utils import (
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
    Background worker thread-based watcher for game process and window focus transitions.
    Executes all /proc and subprocess inspections off the main GUI thread to eliminate UI stutter.
    """

    status_changed = Signal(object)  # GameStatus

    def __init__(self, poll_interval_ms: int = 500, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._poll_interval = max(0.1, poll_interval_ms / 1000.0)
        self._current_status = GameStatus(
            state=GameFocusState.NOT_RUNNING,
            is_running=False,
            is_foreground=False,
        )
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._wake_event = threading.Event()

        try:
            from simpad_qt.core.utils.window_utils import get_window_manager
            self._wm = get_window_manager()
            self._wm.add_focus_listener(self._on_wm_focus_event)
        except Exception:
            self._wm = None

    @property
    def current_status(self) -> GameStatus:
        return self._current_status

    def _on_wm_focus_event(self) -> None:
        """Reactive 0ms callback triggered by native window manager focus events."""
        self._wake_event.set()

    def start(self) -> None:
        """Start asynchronous background polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="GameProcessWatcherThread"
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop polling thread and detach focus listener."""
        self._running = False
        self._wake_event.set()
        if self._wm:
            try:
                self._wm.remove_focus_listener(self._on_wm_focus_event)
            except Exception:
                pass

    def _worker_loop(self) -> None:
        """Background thread executing all process inspection without blocking the Qt event loop."""
        while self._running:
            try:
                self._poll_status()
            except Exception as e:
                logger.debug(f"Error in background process watcher: {e}")
            self._wake_event.wait(timeout=self._poll_interval)
            self._wake_event.clear()

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
