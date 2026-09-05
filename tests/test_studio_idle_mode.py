"""
Tests for SimPulse Studio IDLE background mode and CPU power-saving orchestration.
"""

import pytest
from unittest.mock import MagicMock
from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import QApplication, QWidget

from simpulse.plugins.manager import PluginManager
from simpulse.core.config import ConfigManager
from simpulse.core.game_plugin_manager import GamePluginManager
from simpulse.core.game_process_watcher import GameProcessWatcher, GameStatus, GameFocusState
from simpulse.core.overlay_state_machine import OverlayStateMachine, OverlayDisplayMode
from simpulse.core.telemetry_bus import TelemetryBus
from simpulse.ui.main_window import SimPulseMainWindow
from simpulse.builtin_plugins.official_cockpit_hud import OfficialCockpitHudPlugin
from simpulse.builtin_plugins.pedal_monitor import PedalTelemetryPlugin
from simpulse.builtin_plugins.stream_diagnostics import TelemetryDiagnosticsPlugin
from simpulse_sdk import VehicleSensors, LapDeltaPacket


@pytest.fixture(scope="session")
def qapp():
    """Ensure QApplication exists."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def studio_environment(qapp, tmp_path):
    """Create a test environment with mock/real objects."""
    config_mgr = ConfigManager(config_file=tmp_path / "config.json")
    plugin_mgr = PluginManager(config_manager=config_mgr)
    game_plugin_mgr = GamePluginManager(config_manager=config_mgr)
    process_watcher = GameProcessWatcher()
    overlay_state_machine = OverlayStateMachine(display_mode=OverlayDisplayMode.FORCE_HIDDEN)
    telemetry_bus = TelemetryBus()

    main_win = SimPulseMainWindow(
        plugin_manager=plugin_mgr,
        game_plugin_mgr=game_plugin_mgr,
        process_watcher=process_watcher,
        overlay_state_machine=overlay_state_machine,
        telemetry_bus=telemetry_bus,
        config_mgr=config_mgr,
    )

    yield {
        "win": main_win,
        "config_mgr": config_mgr,
        "plugin_mgr": plugin_mgr,
        "watcher": process_watcher,
        "bus": telemetry_bus,
    }

    main_win.close()


def test_main_window_idle_transition(studio_environment):
    """Test explicit transition into and out of IDLE mode."""
    win = studio_environment["win"]
    assert not win.is_studio_idle

    idle_signals = []
    win.studio_idle_changed.connect(lambda idle: idle_signals.append(idle))

    # Enter IDLE
    win._set_studio_idle(True)
    assert win.is_studio_idle is True
    assert "IDLE" in win.status_bar.badge_studio_power.text()
    assert idle_signals == [True]

    # Exit IDLE
    win._set_studio_idle(False)
    assert win.is_studio_idle is False
    assert "ACTIVE" in win.status_bar.badge_studio_power.text()
    assert idle_signals == [True, False]


def test_evaluate_idle_game_foreground(studio_environment):
    """When game is in foreground and Studio window is not active, Studio should enter idle."""
    win = studio_environment["win"]
    watcher = studio_environment["watcher"]

    # Simulate game running in foreground
    game_status = GameStatus(
        state=GameFocusState.FOREGROUND,
        is_running=True,
        is_foreground=True,
        process_name="LMU.exe",
    )
    watcher._current_status = game_status

    win._evaluate_idle_state()
    assert win.is_studio_idle is True
    assert "IDLE" in win.status_bar.badge_studio_power.text()


def test_fps_and_bandwidth_throttled_when_idle(studio_environment):
    """Top bar badges should not reformat when Studio is idle."""
    win = studio_environment["win"]
    win._set_studio_idle(True)

    win.fps_badge.setText("Telem: 0.0 FPS")
    win._on_fps_changed(120.0)
    # Should remain unchanged because it's idle
    assert win.fps_badge.text() == "Telem: 0.0 FPS"

    # Wake up
    win._set_studio_idle(False)
    win._on_fps_changed(120.0)
    assert "120.0 FPS" in win.fps_badge.text()


def test_official_cockpit_hud_tab_idle_mode(qapp, tmp_path):
    """Test that OfficialCockpitHudTabWidget skips paint events and updates when idle."""
    plugin = OfficialCockpitHudPlugin()
    tab = plugin.create_tab_widget()

    assert getattr(tab, "_is_idle", False) is False

    sensors = VehicleSensors(vehicle_speed=50.0, gear=4, unfiltered_throttle=0.8)
    tab.update_telemetry_ui(sensors)
    assert "180.0 KM/H" in tab.lbl_speed_gear.text()

    # Enter idle
    tab.set_idle_mode(True)
    assert tab._is_idle is True

    # New sensors while idle
    new_sensors = VehicleSensors(vehicle_speed=10.0, gear=1, unfiltered_throttle=0.2)
    tab.update_telemetry_ui(new_sensors)
    # Should NOT have updated
    assert "180.0 KM/H" in tab.lbl_speed_gear.text()

    # Exit idle
    plugin.latest_sensors = new_sensors
    tab.set_idle_mode(False)
    # Should immediately catch up
    assert "36.0 KM/H" in tab.lbl_speed_gear.text()


def test_pedal_monitor_tab_idle_mode(qapp):
    """Test that PedalMonitorWidget freezes progress bar updates when idle."""
    plugin = PedalTelemetryPlugin()
    widget = plugin.create_tab_widget()

    widget.update_live_view(50.0, 30.0, 0.0, 0.0)
    assert widget.pbar_throttle.value() == 50
    assert widget.pbar_brake.value() == 30

    widget.set_idle_mode(True)
    widget.update_live_view(90.0, 80.0, 0.0, 0.0)
    # Should stay at previous values
    assert widget.pbar_throttle.value() == 50
    assert widget.pbar_brake.value() == 30

    # Wake up
    plugin._throttle_pct = 90.0
    plugin._brake_pct = 80.0
    widget.set_idle_mode(False)
    assert widget.pbar_throttle.value() == 90
    assert widget.pbar_brake.value() == 80


def test_stream_diagnostics_timer_stopped_when_idle(qapp):
    """Test that StreamDiagnosticsWidget stops its QTimer when idle."""
    plugin = TelemetryDiagnosticsPlugin()
    widget = plugin.create_tab_widget()

    assert widget._timer.isActive() is True

    widget.set_idle_mode(True)
    assert widget._timer.isActive() is False

    widget.set_idle_mode(False)
    assert widget._timer.isActive() is True


def test_overlay_telemetry_unaffected_by_studio_idle(studio_environment):
    """HUD overlay must continue to receive telemetry even when Studio is idle."""
    win = studio_environment["win"]
    win._set_studio_idle(True)
    assert win.is_studio_idle is True

    sensors = VehicleSensors(vehicle_speed=42.0)
    win.overlay_window.update_telemetry = MagicMock()

    win._on_telemetry_updated(sensors)
    win.overlay_window.update_telemetry.assert_called_once_with(sensors)
