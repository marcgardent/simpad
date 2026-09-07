"""
Unit and Integration Tests for the XInput Haptic Feedback Plugin and Subplugins in Qt6.
"""

import pytest
from PySide6.QtWidgets import QApplication

from simpulse_sdk import PluginState
from simpulse.plugins.manager import PluginManager
from simpulse.core.config import ConfigManager
from simpulse.builtin_plugins.haptic_feedback import HapticFeedbackPlugin
from simpulse.builtin_plugins.haptic_feedback.plugin import (
    HapticFeedbackWidget,
)
from simpulse.core.telemetry.sensors import VehicleSensors
from simpulse_sdk.models import VehicleECU, AntiLockECU


@pytest.fixture(scope="session")
def qapp():
    """Ensure QApplication instance exists for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_haptic_plugin_lifecycle_and_registration(qapp, tmp_path):
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)

    plugin = HapticFeedbackPlugin()
    assert plugin.metadata.id == "simpulse.builtin.haptic_feedback"
    assert plugin.metadata.icon == "🎮"

    assert pm.register_plugin(plugin) is True
    assert plugin.state == PluginState.ENABLED
    assert plugin.config.master_enabled is True
    assert plugin.haptic_controller is not None

    # Check tab provider
    tabs = pm.get_tab_providers()
    assert any(t.metadata.id == "simpulse.builtin.haptic_feedback" for t in tabs)
    assert plugin.get_tab_title() == "XInput Haptics"


def test_haptic_plugin_telemetry_dispatch(qapp, tmp_path):
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)

    plugin = HapticFeedbackPlugin()
    pm.register_plugin(plugin)

    # Telemetry frame with ABS active
    sensors = VehicleSensors(
        vehicle_speed=30.0,
        in_realtime=True,
        gear=3,
        ecu=VehicleECU(abs=AntiLockECU(active_raw=True)),
    )

    plugin.on_telemetry_frame(sensors)

    # Controller should have received vibration
    controller = plugin.haptic_controller
    assert controller is not None
    assert controller.left_low > 0.0


def test_haptic_widget_interactions(qapp, tmp_path):
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)

    plugin = HapticFeedbackPlugin()
    pm.register_plugin(plugin)

    widget = plugin.create_tab_widget()
    assert isinstance(widget, HapticFeedbackWidget)

    # Test master toggle
    widget.chk_master.setChecked(False)
    assert plugin.config.master_enabled is False

    widget.chk_master.setChecked(True)
    assert plugin.config.master_enabled is True

    # Test subplugin checkbox toggle
    widget._on_subplugin_toggled("marc_abs", False)
    assert plugin.manager.is_subplugin_enabled("marc_abs") is False

    widget._on_subplugin_toggled("marc_abs", True)
    assert plugin.manager.is_subplugin_enabled("marc_abs") is True

    # Test test vibration buttons
    widget.plugin.test_rumble(low=0.8, high=0.8, duration_ms=200)
    assert plugin.haptic_controller.left_low > 0.5
    assert plugin.haptic_controller.right_high > 0.5

    widget.plugin.stop_rumble()
    assert plugin.haptic_controller.left_low == 0.0
    assert plugin.haptic_controller.right_high == 0.0
