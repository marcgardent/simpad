"""
Unit and Integration Tests for LMU Paddock Agent Plugin & Persistent Filters.
"""

import pytest
import time
from pathlib import Path
from PySide6.QtWidgets import QApplication

from simpulse_sdk import PluginState
from simpulse.plugins.manager import PluginManager
from simpulse.core.config import ConfigManager
from simpulse.builtin_plugins.paddock_agent import PaddockAgentPlugin
from simpulse.builtin_plugins.paddock_agent.plugin import (
    PaddockAgentConfig,
    PaddockAgentWidget,
    SeriesSetupCardWidget,
)
from simpulse.builtin_plugins.paddock_agent.schedule.manager import RaceEvent, RaceSetupConfig


@pytest.fixture(scope="session")
def qapp():
    """Ensure QApplication instance exists for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_paddock_agent_plugin_lifecycle(qapp, tmp_path):
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)

    plugin = PaddockAgentPlugin()
    assert plugin.metadata.id == "simpulse.builtin.paddock_agent"
    assert plugin.metadata.icon == "🏁"

    assert pm.register_plugin(plugin) is True
    assert plugin.state == PluginState.ENABLED
    assert plugin.config.master_enabled is True

    # Check tab provider
    tabs = pm.get_tab_providers()
    assert any(t.metadata.id == "simpulse.builtin.paddock_agent" for t in tabs)
    assert plugin.get_tab_title() == "LMU Paddock"


def test_paddock_persistent_filters(qapp, tmp_path):
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)

    plugin = PaddockAgentPlugin()
    pm.register_plugin(plugin)

    widget = plugin.create_tab_widget()
    assert isinstance(widget, PaddockAgentWidget)

    # 1. Test setting and persisting filters
    idx_gt3 = widget.combo_car.findData("GT3")
    assert idx_gt3 != -1
    widget.combo_car.setCurrentIndex(idx_gt3)

    idx_adv = widget.combo_diff.findData("Advanced")
    assert idx_adv != -1
    widget.combo_diff.setCurrentIndex(idx_adv)

    widget.chk_active_only.setChecked(True)
    widget.search_box.setText("Le Mans")

    # Check that plugin.config has been updated and persisted
    assert plugin.config.filter_car_class == "GT3"
    assert plugin.config.filter_difficulty == "Advanced"
    assert plugin.config.filter_active_only is True
    assert plugin.config.search_query == "Le Mans"

    # 2. Test filter matching logic
    # Should match: GT3 + Advanced + Le Mans + Enabled
    assert widget._matches_filters(
        difficulty="Advanced",
        car_classes="HYP, GT3",
        race_type="Daily Races",
        setup_type="fixed",
        series_name="One Stint Sprint",
        circuit="Le Mans (WEC)",
        enabled=True,
    ) is True

    # Should not match (different class)
    assert widget._matches_filters(
        difficulty="Advanced",
        car_classes="LMP2",
        race_type="Daily Races",
        setup_type="fixed",
        series_name="Prototype Pro",
        circuit="Le Mans (WEC)",
        enabled=True,
    ) is False

    # Should not match (disabled when active_only is True)
    assert widget._matches_filters(
        difficulty="Advanced",
        car_classes="HYP, GT3",
        race_type="Daily Races",
        setup_type="fixed",
        series_name="One Stint Sprint",
        circuit="Le Mans (WEC)",
        enabled=False,
    ) is False


def test_paddock_setup_subscriptions_and_toggles(qapp, tmp_path):
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)

    plugin = PaddockAgentPlugin()
    pm.register_plugin(plugin)

    widget = plugin.create_tab_widget()

    # Toggle subscription on 'lmgt3_fixed'
    widget._toggle_subscription("lmgt3_fixed")
    setup = plugin.schedule_mgr.setups["lmgt3_fixed"]
    assert setup.enabled is True
    assert setup.notify_5m is True

    # Test quick enable all (5m)
    widget._enable_all_5m()
    for s in plugin.schedule_mgr.setups.values():
        assert s.enabled is True
        assert s.notify_5m is True

    # Test clear all
    widget._clear_all_setups()
    for s in plugin.schedule_mgr.setups.values():
        assert s.enabled is False
        assert s.notify_5m is False


def test_paddock_timer_notifications(qapp, tmp_path):
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)

    plugin = PaddockAgentPlugin()
    pm.register_plugin(plugin)

    widget = plugin.create_tab_widget()

    # Trigger periodic timer tick
    widget._on_timer_tick()
    # Should run smoothly without exception
    assert widget.table_events.rowCount() >= 0


def test_paddock_api_sync_worker(qapp, tmp_path):
    from unittest.mock import patch
    from simpulse.builtin_plugins.paddock_agent.plugin import ApiSyncWorker

    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)

    plugin = PaddockAgentPlugin()
    pm.register_plugin(plugin)

    widget = plugin.create_tab_widget()

    with patch.object(plugin.schedule_mgr, "sync_api", return_value=True):
        worker = ApiSyncWorker(plugin.schedule_mgr)
        results = []
        worker.sync_finished.connect(lambda ok, msg: results.append((ok, msg)))
        worker.run()

        assert len(results) == 1
        assert results[0][0] is True
        assert "Online" in results[0][1]

