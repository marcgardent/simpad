"""
Automated validation and discovery tests for SimPulse plugins.
Ensures that all built-in plugins (and dynamically discovered external plugins)
can be loaded, initialized, and satisfy all SimPulsePlugin contracts without runtime errors.
"""

import pytest
from pathlib import Path
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QSize

from simpulse_sdk import (
    SimPulsePlugin,
    PluginState,
    ITabProvider,
    ITelemetrySubscriber,
    IHudWidgetProvider,
    IDeltaSubscriber,
    ITelemetryStateSubscriber,
    HudSlot,
    ChannelRequirement,
)
from simpulse.plugins.manager import PluginManager
from simpulse.core.config import ConfigManager
from simpulse.core.reference_lap import ReferenceLapManager


@pytest.fixture(scope="session")
def qapp():
    """Ensure QApplication instance exists for Qt-based plugin widgets."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def builtin_plugins_dir() -> Path:
    """Return path to simpulse/builtin_plugins."""
    project_root = Path(__file__).resolve().parent.parent
    builtin_dir = project_root / "simpulse" / "builtin_plugins"
    assert builtin_dir.is_dir(), f"Builtin plugins directory not found: {builtin_dir}"
    return builtin_dir


def test_all_builtin_plugins_discover_and_load_without_errors(qapp, tmp_path, builtin_plugins_dir):
    """
    Ensure every plugin in simpulse/builtin_plugins:
    1. Has a valid plugin.py file.
    2. Is discovered and loaded by PluginManager.
    3. Produces zero load errors (load_errors is empty).
    4. Has unique and valid plugin IDs.
    """
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)

    # Discover all expected plugin directories
    expected_plugin_dirs = [
        d for d in builtin_plugins_dir.iterdir()
        if d.is_dir() and not d.name.startswith("__") and (d / "plugin.py").exists()
    ]
    assert len(expected_plugin_dirs) > 0, "No builtin plugin directories found!"

    # Execute discovery
    pm.discover_and_load([builtin_plugins_dir])

    # Assert zero load errors
    if pm.load_errors:
        error_details = "\n".join(
            f"  - {path.name}: {err}" for path, err in pm.load_errors.items()
        )
        pytest.fail(f"Failed to load {len(pm.load_errors)} plugin(s):\n{error_details}")

    # Assert all expected plugins are loaded
    assert len(pm.plugins) == len(expected_plugin_dirs), (
        f"Expected {len(expected_plugin_dirs)} plugins, but loaded {len(pm.plugins)}: {list(pm.plugins.keys())}"
    )


def test_builtin_plugins_contract_and_lifecycle_compliance(qapp, tmp_path, builtin_plugins_dir):
    """
    Verify each loaded plugin conforms strictly to SimPulsePlugin contracts:
    - Valid metadata (id, name, version)
    - State is ENABLED
    - ITabProvider: valid tab title and widget instantiation
    - ITelemetrySubscriber: valid ChannelRequirement list
    - IHudWidgetProvider: valid HudSlot and non-empty QSize
    """
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)
    # Wire the reference-lap SDK the same way TelemetryBus.reference_lap_mgr
    # normally would via connect_telemetry_bus() — reference_lap_studio's tab
    # needs it (context.get_reference_lap_api()) to construct without crashing.
    from simpulse.core.reference_lap_api import ReferenceLapApi
    pm._reference_lap_api = ReferenceLapApi(ReferenceLapManager(config_manager=cfg_mgr))
    pm.discover_and_load([builtin_plugins_dir])

    assert len(pm.load_errors) == 0

    for pid, plugin in pm.plugins.items():
        meta = plugin.metadata
        assert meta.id == pid, f"Plugin ID mismatch: {meta.id} vs {pid}"
        assert meta.name and len(meta.name.strip()) > 0, f"Plugin {pid} has empty name"
        assert meta.version and len(meta.version.strip()) > 0, f"Plugin {pid} has empty version"
        assert plugin.state == PluginState.ENABLED, f"Plugin {pid} not enabled: {plugin.state}"

        # If plugin provides a UI tab, verify widget creation does not crash
        if isinstance(plugin, ITabProvider):
            title = plugin.get_tab_title()
            assert isinstance(title, str) and len(title.strip()) > 0, f"Plugin {pid} has invalid tab title"
            widget = plugin.create_tab_widget()
            assert isinstance(widget, QWidget), f"Plugin {pid} create_tab_widget did not return a QWidget"

        # If plugin subscribes to telemetry, verify channel requirements
        if isinstance(plugin, ITelemetrySubscriber):
            reqs = plugin.get_channel_requirements()
            assert isinstance(reqs, list), f"Plugin {pid} channel requirements must be a list"
            for req in reqs:
                assert isinstance(req, ChannelRequirement), f"Invalid requirement in {pid}: {req}"

        # If plugin provides a HUD widget, verify layout properties
        if isinstance(plugin, IHudWidgetProvider):
            slot = plugin.preferred_slot
            assert isinstance(slot, HudSlot), f"Plugin {pid} preferred_slot is not a HudSlot"
            size = plugin.get_hud_size()
            assert isinstance(size, QSize), f"Plugin {pid} get_hud_size must return QSize"
            assert size.width() > 0 and size.height() > 0, f"Plugin {pid} has invalid HUD size {size}"


def test_dynamic_package_relative_imports(qapp, tmp_path):
    """
    Test that external plugins located in directories outside sys.path
    with relative imports (e.g. `from .helper import ...`) are loaded properly
    by PluginManager without 'attempted relative import with no known parent package'.
    """
    ext_dir = tmp_path / "external_plugins"
    ext_dir.mkdir()
    my_plugin_dir = ext_dir / "custom_test_plugin"
    my_plugin_dir.mkdir()

    (my_plugin_dir / "__init__.py").write_text('\"\"\"Custom package.\"\"\"\n')
    (my_plugin_dir / "helper.py").write_text('GREETING = "Hello from helper"\n')
    plugin_code = '''
from simpulse_sdk import SimPulsePlugin, PluginMetadata
from .helper import GREETING

class CustomRelativePlugin(SimPulsePlugin):
    def __init__(self):
        super().__init__(PluginMetadata(
            id="test.custom.relative",
            name="Custom Relative Plugin",
            version="1.0.0",
            description=GREETING,
        ))
'''
    (my_plugin_dir / "plugin.py").write_text(plugin_code)

    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)
    pm.discover_and_load([ext_dir])

    assert len(pm.load_errors) == 0, f"Failed with errors: {pm.load_errors}"
    assert "test.custom.relative" in pm.plugins
    loaded_plugin = pm.plugins["test.custom.relative"]
    assert loaded_plugin.metadata.description == "Hello from helper"


def test_plugin_load_error_recorded_properly(qapp, tmp_path):
    """
    Verify that if a plugin contains a syntax or runtime import error,
    PluginManager records the failure in pm.load_errors with the full traceback
    and does not crash the host application.
    """
    bad_dir = tmp_path / "bad_plugins"
    bad_dir.mkdir()
    bad_plugin = bad_dir / "broken_plugin.py"
    bad_plugin.write_text("this is not valid python code syntax !!!")

    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)
    pm.discover_and_load([bad_dir])

    assert bad_plugin in pm.load_errors
    assert "SyntaxError" in pm.load_errors[bad_plugin]


def test_all_builtin_plugins_live_telemetry_and_mock_execution(qapp, tmp_path, builtin_plugins_dir):
    """
    End-to-end integration test:
    1. Discovers and loads all built-in plugins.
    2. Activates all RaceEngineer roles (traffic spotter, pitlane, pace notes, etc.).
    3. Runs TelemetryBus in mock mode across multiple cycles.
    4. Asserts 100% clean execution without any AttributeError or uncaught exception.
    """
    from simpulse.core.telemetry_bus import TelemetryBus

    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)
    pm.discover_and_load([builtin_plugins_dir])

    assert len(pm.load_errors) == 0, f"Plugins failed to load: {pm.load_errors}"

    # Enable all race engineer roles if available
    re_plugin = pm.plugins.get("simpulse.builtin.race_engineer")
    if re_plugin and hasattr(re_plugin, "engineer"):
        for r in re_plugin.engineer._roles:
            r.enabled = True

    bus = TelemetryBus()
    pm.connect_telemetry_bus(bus)

    # Step through 60 frames (1 second of 60Hz telemetry covering all channels)
    for _ in range(60):
        bus.mock_generator._step()

    # Verify latest state
    assert bus.latest_sensors is not None
    assert bus.latest_sensors.vehicle_speed >= 0.0
