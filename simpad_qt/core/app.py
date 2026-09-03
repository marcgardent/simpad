"""
SimPad Qt6 Application Orchestrator.
Initializes QApplication, Config, GamePluginManager, ProcessWatcher, OverlayStateMachine,
PluginManager, TelemetryBus, and MainWindow.
"""

from __future__ import annotations
import sys
import logging
from pathlib import Path
from typing import Optional, List

from PySide6.QtWidgets import QApplication

from simpad_qt.core.config import ConfigManager
from simpad_qt.core.game_plugin_manager import GamePluginManager
from simpad_qt.core.game_process_watcher import GameProcessWatcher
from simpad_qt.core.overlay_state_machine import OverlayStateMachine, OverlayDisplayMode
from simpad_qt.core.reference_lap import ReferenceLapManager
from simpad_qt.core.telemetry_bus import TelemetryBus
from simpad_qt.plugins.manager import PluginManager
from simpad_qt.ui.main_window import SimPadQtMainWindow

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s"
)
logger = logging.getLogger("simpad.app")


class SimPadQtApp:
    """
    Main Application Bootstrapper for SimPad Qt6.
    """

    def __init__(self, argv: Optional[List[str]] = None):
        self.qapp = QApplication.instance() or QApplication(argv or sys.argv)
        self.qapp.setApplicationName("SimPad")
        self.qapp.setOrganizationName("SimPadTeam")

        # 1. Configuration
        self.config_mgr = ConfigManager()

        # 2. Game Plugin & Channels Manager (LMU isiMotor_RawUDP.dll + JSON Rates)
        self.game_plugin_mgr = GamePluginManager()

        # 3. Game Process & Window Watcher (LMU Execution & Focus tracking)
        self.process_watcher = GameProcessWatcher()

        # 4. Overlay State Machine (Contextual In-Game vs Garage vs Menu vs Desktop detection)
        initial_mode = OverlayDisplayMode.AUTO if self.config_mgr.config.app.overlay_enabled else OverlayDisplayMode.FORCE_HIDDEN
        self.overlay_state_machine = OverlayStateMachine(display_mode=initial_mode)

        # Connect process watcher to state machine
        self.process_watcher.status_changed.connect(self.overlay_state_machine.update_game_status)
        self.process_watcher.start()

        # 5. Core Reference Lap & Delta Manager
        self.reference_lap_mgr = ReferenceLapManager(config_manager=self.config_mgr)

        # 6. SimPad Plugin Manager (with strongly-typed ConfigManager)
        self.plugin_manager = PluginManager(config_manager=self.config_mgr)

        # 7. Telemetry Bus (Ingestion pipeline)
        self.telemetry_bus = TelemetryBus(
            plugin_manager=self.plugin_manager,
            reference_lap_mgr=self.reference_lap_mgr,
        )
        self.telemetry_bus.telemetry_updated.connect(self.overlay_state_machine.update_telemetry)

        # 7. Start telemetry stream (Live UDP server by default, or Mock Feeder if enabled)
        if self.config_mgr.config.app.mock_telemetry:
            self.telemetry_bus.start_mock()
        else:
            self.telemetry_bus.start_udp_server()

        # 8. Discover & Load Plugins
        self._load_plugins()

        # 9. Main Window
        self.main_window = SimPadQtMainWindow(
            plugin_manager=self.plugin_manager,
            game_plugin_mgr=self.game_plugin_mgr,
            process_watcher=self.process_watcher,
            overlay_state_machine=self.overlay_state_machine,
            telemetry_bus=self.telemetry_bus,
            config_mgr=self.config_mgr,
        )

    def _load_plugins(self) -> None:
        """Discover and load both built-in and user external plugins."""
        search_paths = [
            Path(__file__).resolve().parent.parent / "builtin_plugins",
            Path.cwd() / "plugins",
        ]
        self.plugin_manager.discover_and_load(search_paths)

    def run(self) -> int:
        """Display the main window and start Qt event loop."""
        logger.info("Starting SimPad Qt6 Studio Application...")
        self.main_window.show()
        return self.qapp.exec()
