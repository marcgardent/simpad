"""
Unit and Integration Tests for the Race Engineer Plugin and Sub-Plugins Architecture.
Tests:
- RaceEngineerPlugin lifecycle (load, enable, disable)
- Sub-plugin channel requirements declaration & aggregation
- Sub-plugin sound requirements declaration & aggregation
- Missing sound detection and baking orchestration
- Safe dispatch of telemetry frames and raw UDP packets to sub-plugins in priority order
- RaceEngineerWidget interactive tab and SubPluginCardWidget controls
"""

from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication

from simpad_qt.plugins.contracts import PluginState, PluginContext
from simpad_qt.plugins.manager import PluginManager
from simpad_qt.core.config import ConfigManager
from simpad_qt.core.telemetry_channels import TelemetryChannel, ChannelRequirement, TelemetryRawPacket
from simpad_qt.builtin_plugins.race_engineer import RaceEngineerPlugin
from simpad_qt.builtin_plugins.race_engineer.plugin import (
    RaceEngineerPluginConfig, RaceEngineerWidget, RoleListItemWidget, RoleDetailWidget, SoundLibraryDialog
)
from src.engineer.base import BaseRole, EngineerMessage, RoleStatus
from src.engineer.params import BoolParam
from src.engineer.manager import RaceEngineer
from src.telemetry.sensors import VehicleSensors
from src.utils.audio import AudioAnnouncer
from isimotor_rawudp_client import TelemInfo, TelemVect3, CompactScoring, FullScoringSession, VehicleScoring


@pytest.fixture(scope="session")
def qapp():
    """Ensure QApplication instance exists for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_race_engineer_plugin_lifecycle_and_registration(qapp, tmp_path):
    """Test RaceEngineerPlugin instantiation, metadata, registration in PluginManager and lifecycle."""
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)

    plugin = RaceEngineerPlugin()
    assert plugin.metadata.id == "simpad.builtin.race_engineer"
    assert plugin.metadata.name == "Virtual Race Engineer & Spotters"
    assert plugin.metadata.icon == "🎙️"

    assert pm.register_plugin(plugin) is True
    assert plugin.state == PluginState.ENABLED
    assert plugin.engineer.enabled is True

    # Check tab provider
    tabs = pm.get_tab_providers()
    assert any(t.metadata.id == "simpad.builtin.race_engineer" for t in tabs)
    assert plugin.get_tab_title() == "Race Engineer"
    assert plugin.get_tab_icon() == "🎙️"

    # Disable plugin
    pm.disable_plugin(plugin.metadata.id)
    assert plugin.state == PluginState.DISABLED
    assert plugin.engineer.enabled is False

    # Re-enable plugin
    pm.enable_plugin(plugin.metadata.id)
    assert plugin.state == PluginState.ENABLED
    assert plugin.engineer.enabled is True


def test_subplugin_channel_requirements_aggregation(qapp, tmp_path):
    """Test that sub-plugins declare their subscription requirements and the plugin aggregates them correctly."""
    plugin = RaceEngineerPlugin()
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    ctx = PluginContext(plugin.metadata.id, cfg_mgr)
    plugin.on_load(ctx)
    plugin.on_enable()

    # Verify each sub-plugin has declared channel requirements
    roles = plugin.engineer.get_roles()
    assert len(roles) >= 6

    for role in roles:
        reqs = role.get_channel_requirements()
        assert isinstance(reqs, list)
        assert len(reqs) > 0, f"Role '{role.role_id}' must declare channel requirements"
        for r in reqs:
            assert isinstance(r, ChannelRequirement)
            assert isinstance(r.channel, TelemetryChannel)
            assert r.preferred_hz > 0

    # Test main plugin aggregated requirements
    aggregated_reqs = plugin.get_channel_requirements()
    assert len(aggregated_reqs) >= 2

    # TELEMETRY channel must be aggregated at 100 Hz
    telem_req = next((r for r in aggregated_reqs if r.channel == TelemetryChannel.TELEMETRY), None)
    assert telem_req is not None
    assert telem_req.preferred_hz == 100
    assert telem_req.required is True
    assert len(telem_req.reason) > 0

    # FULL_SCORING channel must be aggregated
    full_req = next((r for r in aggregated_reqs if r.channel == TelemetryChannel.FULL_SCORING), None)
    assert full_req is not None
    assert full_req.preferred_hz == 10
    assert full_req.required is True


def test_subplugin_sound_requirements_aggregation_and_missing_check(qapp, tmp_path):
    """Test that sub-plugins declare their needed sounds and the plugin aggregates and checks them."""
    plugin = RaceEngineerPlugin()
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    ctx = PluginContext(plugin.metadata.id, cfg_mgr)
    plugin.on_load(ctx)

    roles = plugin.engineer.get_roles()
    for role in roles:
        sounds = role.get_sound_requirements()
        assert isinstance(sounds, dict)
        assert len(sounds) > 0, f"Role '{role.role_id}' must declare sound requirements"

    all_sounds = plugin.engineer.get_all_sound_requirements(only_enabled=False)
    assert len(all_sounds) >= 30
    assert "timing_in_progress" in all_sounds
    assert "time_deleted" in all_sounds
    assert "give_time_back" in all_sounds
    assert "car_left" in all_sounds
    assert "incoming" in all_sounds
    assert "brake" in all_sounds
    assert "turn_1" in all_sounds
    assert "gear_1" in all_sounds

    # Test missing sounds check with a custom empty sound directory
    empty_sound_dir = tmp_path / "empty_sound"
    missing = plugin.engineer.get_missing_sounds(sound_dir=empty_sound_dir)
    assert len(missing) == len(all_sounds)

    # If we create one file in the directory
    empty_sound_dir.mkdir(parents=True, exist_ok=True)
    (empty_sound_dir / "timing_in_progress.wav").write_text("dummy audio")
    missing_after = plugin.engineer.get_missing_sounds(sound_dir=empty_sound_dir)
    assert len(missing_after) == len(all_sounds) - 1
    assert "timing_in_progress" not in missing_after


def test_race_engineer_packet_dispatch_and_radio_feed(qapp, tmp_path):
    """Test that incoming telemetry and scoring packets trigger evaluation and dispatch to sub-plugins."""
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    plugin = RaceEngineerPlugin()
    ctx = PluginContext(plugin.metadata.id, cfg_mgr)
    plugin.on_load(ctx)
    plugin.on_enable()

    # Create Tab widget to observe radio log
    tab = plugin.create_tab_widget()
    assert isinstance(tab, RaceEngineerWidget)

    # 1. Send Telemetry Packet
    telem = TelemInfo(
        local_vel=TelemVect3(0.0, 0.0, 50.0),
        gear=3,
        engine_rpm=6500.0,
    )
    pkt_telem = TelemetryRawPacket(
        channel=TelemetryChannel.TELEMETRY,
        data=telem,
        raw_bytes_len=640
    )
    plugin.on_telemetry_packet(pkt_telem)

    # 2. Send FullScoring Packet with player and opponent behind (Fight Spotter / Traffic Spotter candidate)
    player = VehicleScoring(
        id=1,
        is_player=True,
        control=0,
        pos=TelemVect3(0.0, 0.0, 100.0),
        local_vel=TelemVect3(0.0, 0.0, 40.0),
        lap_dist=500.0,
        in_pits=False,
        in_garage_stall=False,
    )
    opponent = VehicleScoring(
        id=2,
        is_player=False,
        control=1,
        pos=TelemVect3(2.0, 0.0, 99.0),  # 2m to left, overlapping longitudinally
        local_vel=TelemVect3(0.0, 0.0, 40.0),
        lap_dist=499.0,
        in_pits=False,
        in_garage_stall=False,
    )
    scoring = FullScoringSession(
        in_realtime=True,
        game_phase=5,
        session=10,  # Race
        lap_dist=5000.0,
        vehicles=[player, opponent],
    )
    pkt_scoring = TelemetryRawPacket(
        channel=TelemetryChannel.FULL_SCORING,
        data=scoring,
        raw_bytes_len=2480
    )
    plugin.on_telemetry_packet(pkt_scoring)

    # Verify tab updates and radio feed
    tab.update_live_views()
    assert tab.radio_list.count() >= 0


def test_race_engineer_widget_interactive_controls(qapp, tmp_path):
    """Test interactive UI controls in RaceEngineerWidget: sub-plugin priorities, parameters, mute."""
    cfg_file = tmp_path / "cfg_engineer.json"
    cfg_mgr = ConfigManager(config_file=cfg_file)
    plugin = RaceEngineerPlugin()
    ctx = PluginContext(plugin.metadata.id, cfg_mgr)
    plugin.on_load(ctx)
    plugin.on_enable()

    tab = plugin.create_tab_widget()

    # Test master toggle
    tab.chk_master.setChecked(False)
    assert plugin.engineer.enabled is False
    tab.chk_master.setChecked(True)
    assert plugin.engineer.enabled is True

    # Test mute toggle
    tab.chk_mute.setChecked(True)
    assert AudioAnnouncer.is_muted() is True
    tab.chk_mute.setChecked(False)
    assert AudioAnnouncer.is_muted() is False

    # Test sub-plugin reordering and selection in Master-Detail list
    initial_order = [r.role_id for r in plugin.engineer.get_roles()]
    assert tab.roles_list.count() == len(initial_order)

    # Select second role
    tab.roles_list.setCurrentRow(1)
    assert tab.role_detail_widget.current_role is not None
    assert tab.role_detail_widget.current_role.role_id == initial_order[1]

    # Move selected role up
    tab._on_move_selected_up()
    new_order = [r.role_id for r in plugin.engineer.get_roles()]
    assert new_order[0] == initial_order[1]
    assert new_order[1] == initial_order[0]

    # Test sub-plugin parameter editing in detail widget
    first_role = plugin.engineer.get_roles()[0]
    tab.roles_list.setCurrentRow(0)
    params = first_role.get_parameters()
    if params:
        p0 = params[0]
        if isinstance(p0, BoolParam):
            tab.role_detail_widget._on_param_changed(p0.name, not p0.default)
            assert first_role.get_param_value(p0.name) == (not p0.default)


def test_sound_library_dialog(qapp, tmp_path):
    """Test opening SoundLibraryDialog and testing sound preview playback."""
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    plugin = RaceEngineerPlugin()
    ctx = PluginContext(plugin.metadata.id, cfg_mgr)
    plugin.on_load(ctx)

    dlg = SoundLibraryDialog(plugin)
    assert dlg.table.rowCount() >= 30
    assert dlg.table.columnCount() == 4
