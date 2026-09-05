"""
SimPulse Qt6 Application Orchestrator.
Initializes QApplication, Config, GamePluginManager, ProcessWatcher, OverlayStateMachine,
PluginManager, TelemetryBus, and MainWindow.
"""
from __future__ import annotations
import sys
import logging
from pathlib import Path
from typing import Optional, List

from PySide6.QtWidgets import QApplication

from simpulse.core.config import ConfigManager
from simpulse.core.game_plugin_manager import GamePluginManager
from simpulse.core.game_process_watcher import GameProcessWatcher
from simpulse.core.overlay_state_machine import OverlayStateMachine, OverlayDisplayMode
from simpulse.core.reference_lap import ReferenceLapManager
from simpulse.core.telemetry_bus import TelemetryBus
from simpulse.plugins.manager import PluginManager
from simpulse.ui.main_window import SimPulseMainWindow

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s"
)
logger = logging.getLogger("simpulse.app")


class SimPulseApp:
    """
    Main Application Bootstrapper for SimPulse Studio.
    """

    def __init__(self, argv: Optional[List[str]] = None):
        self.qapp = QApplication.instance() or QApplication(argv or sys.argv)
        self.qapp.setApplicationName("SimPulse")
        self.qapp.setOrganizationName("SimPulse")

        # 1. Configuration
        self.config_mgr = ConfigManager()

        # 2. Game Plugin & Channels Manager (LMU isiMotor_RawUDP.dll + JSON Rates)
        self.game_plugin_mgr = GamePluginManager(config_manager=self.config_mgr)

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

        # 6. SimPulse Plugin Manager (with strongly-typed ConfigManager)
        self.plugin_manager = PluginManager(config_manager=self.config_mgr)

        # 7. Telemetry Bus (Ingestion pipeline)
        self.telemetry_bus = TelemetryBus(
            reference_lap_mgr=self.reference_lap_mgr,
        )
        self.plugin_manager.connect_telemetry_bus(self.telemetry_bus)
        self.telemetry_bus.telemetry_updated.connect(self.overlay_state_machine.update_telemetry)

        # 8. Start telemetry stream (Live UDP server by default, or Mock Feeder if enabled)
        if self.config_mgr.config.app.mock_telemetry:
            self.telemetry_bus.start_mock()
        else:
            gp_cfg = self.config_mgr.get_game_plugin_settings()
            self.telemetry_bus.start_udp_server(
                port=gp_cfg.target_port,
                target_port=gp_cfg.inbound_port,
            )

        # 9. Discover & Load Plugins
        self._load_plugins()

        # 10. Main Window
        self.main_window = SimPulseMainWindow(
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
            Path(__file__).resolve().parent / "builtin_plugins",
            Path.cwd() / "plugins",
        ]
        self.plugin_manager.discover_and_load(search_paths)

    def run(self) -> int:
        """Display the main window and start Qt event loop."""
        logger.info("Starting SimPulse Studio Application...")
        self.main_window.show()
        return self.qapp.exec()


def main(argv: Optional[List[str]] = None) -> int:
    """CLI / GUI main entry point for SimPulse Studio."""
    if argv is None:
        argv = sys.argv
    try:
        app = SimPulseApp(argv)
        return app.run()
    except Exception as e:
        import traceback
        print(f"[FATAL] Error starting SimPulse: {e}", flush=True)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

