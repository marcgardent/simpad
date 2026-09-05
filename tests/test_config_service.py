"""
Unit and Integration tests for SimPad Configuration System & IConfigManager contract.
Verifies:
- IConfigManager contract interface conformance
- Single source of truth (config.json) loading and saving
- Flattened configuration schema (AppSettings, GamePluginConfig, LoggerSettings, SimPadConfig)
- GamePluginManager binding to unified config
- Exclusion of 'priority' key in subplugin configs (ordered array sorting)
"""

import json
from pathlib import Path
from dataclasses import dataclass
import pytest

from simpad_qt.core.config import (
    IConfigManager,
    ConfigManager,
    ConfigFactory,
    SimPadConfig,
    AppSettings,
    GamePluginConfig,
    LoggerSettings,
)
from simpad_qt.core.game_plugin_manager import GamePluginManager, ChannelSettings
from simpad_qt.core.telemetry_channels import TelemetryChannel


@dataclass
class CustomPluginTestConfig:
    custom_threshold: float = 88.5
    feature_active: bool = True


def test_config_manager_implements_iconfigmanager():
    """Verify that ConfigManager implements the IConfigManager contract."""
    assert issubclass(ConfigManager, IConfigManager)
    mgr = ConfigManager()
    assert isinstance(mgr, IConfigManager)


def test_default_config_file_path():
    """Verify default config file is config.json."""
    assert ConfigManager.DEFAULT_CONFIG_PATH == Path("config.json")


def test_config_json_root_binding(tmp_path):
    """Verify loading from config.json reads app, game_plugin, and loggers."""
    test_file = tmp_path / "config.json"
    data = {
        "app": {
            "dark_theme": False,
            "target_fps": 120,
            "abs_threshold": 0.25,
            "udp_port": 5005,
        },
        "game_plugin": {
            "target_ip": "192.168.1.100",
            "target_port": 6000,
            "inbound_port": 6001,
            "enable_logging": True,
            "rates": {
                "PlayerTelemetryRate": "100Hz",
            },
        },
        "loggers": {
            "telemetry": True,
            "engineer": True,
        },
        "plugins_enabled": {
            "test_plugin": True,
        },
        "plugins": {
            "test_plugin": {
                "custom_threshold": 45.0,
                "feature_active": False,
            }
        }
    }
    test_file.write_text(json.dumps(data), encoding="utf-8")

    mgr = ConfigManager(config_file=test_file)

    # App settings
    app = mgr.get_app_settings()
    assert app.dark_theme is False
    assert app.target_fps == 120
    assert app.abs_threshold == 0.25
    assert app.udp_port == 5005

    # Game plugin settings
    gp = mgr.get_game_plugin_settings()
    assert gp.target_ip == "192.168.1.100"
    assert gp.target_port == 6000
    assert gp.inbound_port == 6001
    assert gp.enable_logging is True
    assert gp.rates["PlayerTelemetryRate"] == "100Hz"

    # Logger settings
    loggers = mgr.get_logger_settings()
    assert loggers.telemetry is True
    assert loggers.engineer is True
    assert loggers.schedule is False

    # Plugin enabled & typed config
    assert mgr.is_plugin_enabled("test_plugin") is True
    plugin_cfg = mgr.get_plugin_config_as("test_plugin", CustomPluginTestConfig)
    assert plugin_cfg.custom_threshold == 45.0
    assert plugin_cfg.feature_active is False


def test_config_save_persists_to_json(tmp_path):
    """Verify modifications persist correctly to the target json file."""
    test_file = tmp_path / "config.json"
    mgr = ConfigManager(config_file=test_file)

    app = mgr.get_app_settings()
    app.target_fps = 90
    mgr.set_app_settings(app, auto_save=True)

    gp = mgr.get_game_plugin_settings()
    gp.target_port = 7777
    mgr.set_game_plugin_settings(gp, auto_save=True)

    mgr.set_plugin_enabled("sample_plugin", False, auto_save=True)
    mgr.set_plugin_config_from("sample_plugin", CustomPluginTestConfig(custom_threshold=12.5), auto_save=True)

    # Reload from disk
    mgr2 = ConfigManager(config_file=test_file)
    assert mgr2.get_app_settings().target_fps == 90
    assert mgr2.get_game_plugin_settings().target_port == 7777
    assert mgr2.is_plugin_enabled("sample_plugin") is False
    assert mgr2.get_plugin_config_as("sample_plugin", CustomPluginTestConfig).custom_threshold == 12.5


def test_game_plugin_manager_binding(tmp_path):
    """Verify GamePluginManager loads and saves through IConfigManager."""
    test_file = tmp_path / "config.json"
    cfg_mgr = ConfigManager(config_file=test_file)

    gp_cfg = cfg_mgr.get_game_plugin_settings()
    gp_cfg.target_port = 5555
    gp_cfg.rates["PlayerTelemetryRate"] = "60Hz"
    cfg_mgr.set_game_plugin_settings(gp_cfg, auto_save=True)

    # GamePluginManager initialized with cfg_mgr
    gpm = GamePluginManager(config_manager=cfg_mgr)
    assert gpm.settings.target_port == 5555
    assert gpm.settings.rates[TelemetryChannel.TELEMETRY] == "60Hz"

    # Modify settings through GamePluginManager and save
    gpm.settings.target_port = 9999
    gpm.settings.rates[TelemetryChannel.WEATHER] = "10Hz"
    gpm.save_local_settings()

    # Verify persisted in config manager with official plugin key
    saved_gp = cfg_mgr.get_game_plugin_settings()
    assert saved_gp.target_port == 9999
    assert saved_gp.rates["WeatherRate"] == "10Hz"


def test_race_engineer_subplugin_order_without_priority(tmp_path):
    """Verify RaceEngineer configuration uses sorted arrays without priority field in subplugins."""
    from simpad_qt.builtin_plugins.race_engineer.manager import RaceEngineer

    config_file = tmp_path / "config.json"
    engineer = RaceEngineer(auto_load_builtin_roles=True, config_path=config_file)
    exported = engineer.save_configuration()

    assert "order" in exported
    assert isinstance(exported["order"], list)
    assert len(exported["order"]) > 0

    # Ensure no subplugin config contains 'priority'
    roles_dict = exported["roles"]
    for role_id, role_cfg in roles_dict.items():
        assert "priority" not in role_cfg, f"Role '{role_id}' must NOT contain 'priority' in serialized config"


def test_plugin_config_with_hud_slot_serialization(tmp_path):
    """Verify plugins with HudSlot and Enums serialize cleanly to JSON and deserialize back."""
    from simpulse_sdk import HudSlot

    @dataclass
    class HudWidgetTestConfig:
        slot: HudSlot = HudSlot.COCKPIT_CENTER
        opacity: float = 0.85

    config_file = tmp_path / "config.json"
    mgr = ConfigManager(config_file=config_file)

    # Save a dataclass containing a HudSlot Enum
    widget_cfg = HudWidgetTestConfig(slot=HudSlot.TOP_RIGHT, opacity=0.9)
    mgr.set_plugin_config_from("hud_widget_test", widget_cfg, auto_save=True)

    # Verify JSON file on disk was written without errors and contains string value
    raw_text = config_file.read_text(encoding="utf-8")
    parsed = json.loads(raw_text)
    assert parsed["plugins"]["hud_widget_test"]["slot"] == "top_right"
    assert parsed["plugins"]["hud_widget_test"]["opacity"] == 0.9

    # Reload in a new manager instance and verify typed config restores HudSlot
    mgr2 = ConfigManager(config_file=config_file)
    restored = mgr2.get_plugin_config_as("hud_widget_test", HudWidgetTestConfig)
    assert isinstance(restored.slot, HudSlot)
    assert restored.slot == HudSlot.TOP_RIGHT
    assert restored.opacity == 0.9
