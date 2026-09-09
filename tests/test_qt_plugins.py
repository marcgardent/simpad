"""
Unit and Integration Tests for the SimPulse Qt6 Strongly-Typed Plugin Architecture.
"""

import time
from dataclasses import dataclass
import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from simpulse_sdk import (
    SimPulsePlugin, PluginMetadata, PluginContext, PluginState,
    HudSlot, HudLayoutSpec, PluginErrorReport,
    ITabProvider, ITelemetrySubscriber, ITelemetryStateSubscriber, IHudWidgetProvider,
    TelemetryChannel, ChannelRequirement, TelemetryRawPacket,
    VehicleSensors, WheelSet, TireCorner, VehicleECU, AntiLockECU, TractionControlECU,
)
from simpulse.plugins.manager import PluginManager
from simpulse.core.config import ConfigManager, AppSettings
from simpulse.core.game_plugin_manager import GamePluginManager
from simpulse.core.game_process_watcher import GameProcessWatcher, GameStatus, GameFocusState
from simpulse.core.overlay_state_machine import (
    OverlayStateMachine, GameSceneState, OverlayDisplayMode
)
from simpulse.core.telemetry_bus import TelemetryBus
from simpulse.ui.slot_compositor import HudSlotCompositor
from simpulse.ui.status_bar import SimPulseCoreStatusBar
from simpulse.builtin_plugins.gear_speed_hud import GearSpeedHudPlugin
from simpulse.builtin_plugins.gear_speed_hud.plugin import GearSpeedConfig
from simpulse.builtin_plugins.official_cockpit_hud import OfficialCockpitHudPlugin
from simpulse.builtin_plugins.official_cockpit_hud.plugin import OfficialCockpitHudConfig
from simpulse.builtin_plugins.pedal_monitor import PedalTelemetryPlugin
from simpulse.builtin_plugins.pedal_monitor.plugin import PedalMonitorConfig
from simpulse.builtin_plugins.stream_diagnostics import TelemetryDiagnosticsPlugin


@pytest.fixture(scope="session")
def qapp():
    """Ensure QApplication instance exists for offscreen Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@dataclass
class DummyConfig:
    """Strongly-typed config for dummy plugin."""
    threshold: int = 42
    enabled: bool = True


class DummyTestPlugin(SimPulsePlugin, ITabProvider, ITelemetrySubscriber, IHudWidgetProvider):
    """Test plugin implementing all capabilities with strongly-typed config."""

    def __init__(self):
        super().__init__(PluginMetadata(
            id="test.dummy",
            name="Dummy Plugin",
            version="0.1.0",
            description="Testing dummy"
        ))
        self.config: DummyConfig = DummyConfig()
        self.received_frames = []

    def get_channel_requirements(self):
        return [
            ChannelRequirement(channel=TelemetryChannel.TELEMETRY, preferred_hz=60),
            ChannelRequirement(channel=TelemetryChannel.WEATHER, preferred_hz=2),
        ]

    def on_load(self, context: PluginContext) -> None:
        super().on_load(context)
        self.config = context.get_typed_config(DummyConfig)

    def get_tab_title(self) -> str:
        return "Dummy Tab"

    def get_tab_icon(self) -> str:
        return "🧪"

    def create_tab_widget(self, parent=None):
        from PySide6.QtWidgets import QLabel
        return QLabel("Dummy Content", parent)

    def on_telemetry_frame(self, sensors: VehicleSensors) -> None:
        self.received_frames.append(sensors)

    @property
    def preferred_slot(self) -> HudSlot:
        return HudSlot.TOP_CENTER

    def get_hud_size(self) -> QSize:
        return QSize(100, 50)

    def is_hud_visible(self) -> bool:
        return self.config.enabled

    def paint_hud(self, painter: QPainter, width: float, height: float, sensors: VehicleSensors) -> None:
        painter.drawText(0, 10, "Dummy HUD")


class FaultyTestPlugin(SimPulsePlugin, ITelemetrySubscriber):
    """Plugin designed to test circuit breaker tripping."""

    def __init__(self):
        super().__init__(PluginMetadata(
            id="test.faulty",
            name="Faulty Plugin",
            version="1.0.0"
        ))

    def on_telemetry_frame(self, sensors: VehicleSensors) -> None:
        raise RuntimeError("Simulated crash inside telemetry callback!")


def test_typed_config_manager(tmp_path):
    """Test strongly-typed AppSettings and plugin dataclass persistence."""
    cfg_file = tmp_path / "test_config.json"
    cfg_mgr = ConfigManager(config_file=cfg_file)

    assert isinstance(cfg_mgr.config.app, AppSettings)
    assert cfg_mgr.config.app.dark_theme is True

    # Test plugin typed config
    cfg_mgr.set_plugin_config_from("test.dummy", DummyConfig(threshold=99, enabled=False))
    cfg_mgr.save()

    # Reload in new instance
    cfg_mgr2 = ConfigManager(config_file=cfg_file)
    restored_config = cfg_mgr2.get_plugin_config_as("test.dummy", DummyConfig)
    assert isinstance(restored_config, DummyConfig)
    assert restored_config.threshold == 99
    assert restored_config.enabled is False


def test_plugin_context_typed_config(tmp_path):
    """Test plugin context with generic dataclass mapping."""
    cfg_file = tmp_path / "test_config_ctx.json"
    cfg_mgr = ConfigManager(config_file=cfg_file)
    ctx = PluginContext("test.dummy", cfg_mgr)

    config = ctx.get_typed_config(DummyConfig)
    assert isinstance(config, DummyConfig)
    assert config.threshold == 42  # default

    config.threshold = 128
    ctx.save_typed_config(config)

    # Verify directly from manager
    reloaded = cfg_mgr.get_plugin_config_as("test.dummy", DummyConfig)
    assert reloaded.threshold == 128


def test_plugin_context_state_view_hides_raw_ingest(tmp_path):
    """PluginContext.get_state_view() must expose the consolidated, immutable View,
    never raw slots."""
    from simpulse_sdk import TelemetryStateStore, TelemetryView

    cfg_file = tmp_path / "test_config_ctx_view.json"
    cfg_mgr = ConfigManager(config_file=cfg_file)
    store = TelemetryStateStore()
    ctx = PluginContext("test.dummy", cfg_mgr, state_store=store)

    view = ctx.get_state_view()
    assert isinstance(view, TelemetryView)
    # Raw ingest slots simply don't exist on the frozen View at all (structurally
    # unreachable, not merely access-denied).
    with pytest.raises(AttributeError):
        _ = view.compact_scoring
    with pytest.raises(AttributeError):
        _ = view.telemetry

    # Consolidated fields still match the backing store's state at snapshot time.
    assert view.current_sector == store.current_sector

    # Falls back to the process-wide singleton when constructed without a store.
    ctx_no_store = PluginContext("test.dummy2", cfg_mgr)
    assert isinstance(ctx_no_store.get_state_view(), TelemetryView)


def test_plugin_manager_lifecycle(qapp, tmp_path):
    """Test plugin registration, capabilities and state transitions."""
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)

    plugin = DummyTestPlugin()
    assert pm.register_plugin(plugin) is True
    assert plugin.state == PluginState.ENABLED
    assert "test.dummy" in pm.plugins

    # Capabilities
    tabs = pm.get_tab_providers()
    assert len(tabs) == 1
    assert tabs[0].get_tab_title() == "Dummy Tab"

    hud_widgets = pm.get_hud_providers()
    assert len(hud_widgets) == 1

    # Disable / Enable
    pm.disable_plugin("test.dummy")
    assert plugin.state == PluginState.DISABLED
    assert len(pm.get_tab_providers()) == 0

    pm.enable_plugin("test.dummy")
    assert plugin.state == PluginState.ENABLED
    assert len(pm.get_tab_providers()) == 1


def test_circuit_breaker_typed_report(qapp, tmp_path):
    """Test that faulty plugins trip the circuit breaker and emit a strongly-typed PluginErrorReport."""
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)

    faulty = FaultyTestPlugin()
    pm.register_plugin(faulty)
    assert faulty.state == PluginState.ENABLED

    received_reports = []
    pm.plugin_faulted.connect(lambda report: received_reports.append(report))

    sensors = VehicleSensors()

    # Trigger errors up to threshold
    for _ in range(PluginManager.CIRCUIT_BREAKER_THRESHOLD):
        pm.dispatch_telemetry(sensors)

    # After threshold, plugin must be in FAULTED state
    assert faulty.state == PluginState.FAULTED
    assert len(received_reports) == 1

    report: PluginErrorReport = received_reports[0]
    assert isinstance(report, PluginErrorReport)
    assert report.plugin_id == "test.faulty"
    assert report.action_name == "on_telemetry_frame"
    assert "Simulated crash" in report.error_message


def test_game_plugin_manager_rate_computation():
    """Test synthesis of optimal channel rates from plugin requirements."""
    gpm = GamePluginManager()
    dummy = DummyTestPlugin()
    gear_hud = GearSpeedHudPlugin()

    reqs = {
        "dummy": dummy.get_channel_requirements(),
        "gear_hud": gear_hud.get_channel_requirements(),
    }

    recom = gpm.compute_recommended_rates(reqs)
    assert recom[TelemetryChannel.TELEMETRY] == "unlimited"
    assert recom[TelemetryChannel.COMPACT_SCORING] == "10Hz"
    assert recom[TelemetryChannel.WEATHER] == "2Hz"
    assert recom[TelemetryChannel.SYSTEM_EVENTS] == "Enabled"


def test_official_stream_diagnostics_plugin(qapp, tmp_path):
    """Test the official TelemetryDiagnosticsPlugin packet ingestion, Hz & Kb/s calculation."""
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    diag_plugin = TelemetryDiagnosticsPlugin()
    ctx = PluginContext(diag_plugin.metadata.id, cfg_mgr)
    diag_plugin.on_load(ctx)
    diag_plugin.on_enable()

    # Verify requirements
    reqs = diag_plugin.get_channel_requirements()
    assert len(reqs) >= 4
    assert any(r.channel == TelemetryChannel.TELEMETRY for r in reqs)

    pm = PluginManager(cfg_mgr)
    pm.register_plugin(diag_plugin)

    # Send 10 packets of Telemetry (640 bytes) via dispatch_packet -> on_physics_tick
    for _ in range(10):
        packet = TelemetryRawPacket(
            channel=TelemetryChannel.TELEMETRY,
            data=VehicleSensors(),
            raw_bytes_len=640
        )
        pm.dispatch_packet(packet)

    stats = diag_plugin.get_channel_statistics()
    telem_stat = stats[TelemetryChannel.TELEMETRY]
    assert telem_stat.packet_count == 10
    assert telem_stat.total_bytes == 6400
    assert telem_stat.hz_estimate > 0.0
    assert telem_stat.kbs_estimate > 0.0

    # Test tab creation
    tab = diag_plugin.create_tab_widget()
    assert tab is not None


def test_hud_slot_compositor_typed_spec():
    """Test HudLayoutSpec dataclass bounding box calculations."""
    sw, sh = 1920.0, 1080.0
    size = QSize(200, 100)

    # Top-Left
    spec_tl = HudSlotCompositor.calculate_slot_layout(HudSlot.TOP_LEFT, sw, sh, size, margin=20.0)
    assert isinstance(spec_tl, HudLayoutSpec)
    assert spec_tl.allocated_rect.x() == 20.0
    assert spec_tl.allocated_rect.y() == 20.0
    assert spec_tl.allocated_rect.width() == 200.0
    assert spec_tl.allocated_rect.height() == 100.0

    # Top-Center
    spec_tc = HudSlotCompositor.calculate_slot_layout(HudSlot.TOP_CENTER, sw, sh, size)
    assert spec_tc.allocated_rect.x() == (1920.0 - 200.0) / 2.0
    assert spec_tc.allocated_rect.y() == 24.0


def test_gear_speed_hud_plugin_typed(qapp, tmp_path):
    """Test GearSpeedHudPlugin with GearSpeedConfig dataclass."""
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    plugin = GearSpeedHudPlugin()
    ctx = PluginContext("simpulse.builtin.gear_speed_hud", cfg_mgr)
    plugin.on_load(ctx)
    plugin.on_enable()

    assert isinstance(plugin.config, GearSpeedConfig)
    assert plugin.config.slot == HudSlot.COCKPIT_CENTER

    sensors = VehicleSensors()
    sensors.vehicle_speed = 50.0  # 180 km/h
    sensors.gear = 4
    sensors.engine_rpm = 7200.0
    sensors.engine_max_rpm = 8500.0
    sensors.has_delta_reference = True
    sensors.lap_flag = 2
    sensors.in_realtime = True
    sensors.delta_time = -0.450

    plugin.on_telemetry_frame(sensors)

    # Offscreen image rendering test
    img = QImage(300, 200, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    painter = QPainter(img)
    try:
        plugin.paint_hud(painter, 260, 120, sensors)
    finally:
        painter.end()

    # Create Tab widget
    tab = plugin.create_tab_widget()
    assert tab is not None


def test_pedal_telemetry_plugin_typed(qapp, tmp_path):
    """Test PedalTelemetryPlugin with PedalMonitorConfig dataclass."""
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    plugin = PedalTelemetryPlugin()
    ctx = PluginContext("simpulse.builtin.pedal_monitor", cfg_mgr)
    plugin.on_load(ctx)
    plugin.on_enable()

    assert isinstance(plugin.config, PedalMonitorConfig)
    assert plugin.config.slot == HudSlot.BOTTOM_LEFT

    sensors = VehicleSensors()
    sensors.unfiltered_throttle = 0.85
    sensors.unfiltered_brake = 0.60
    sensors.update_ecu_domain("abs", active_raw=True)
    sensors.update_ecu_domain("tc", active_raw=True)
    sensors.update_wheel_corner("front_left", lock=0.90)
    sensors.update_wheel_corner("rear_left", spin=0.75)

    plugin.on_telemetry_frame(sensors)

    # Offscreen image rendering test
    img = QImage(120, 180, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    painter = QPainter(img)
    try:
        plugin.paint_hud(painter, 90, 140, sensors)
    finally:
        painter.end()

    # Create Tab widget
    tab = plugin.create_tab_widget()
    assert tab is not None


def test_telemetry_bus_integration(qapp, tmp_path):
    """Test TelemetryBus dispatching frames and raw packets to PluginManager."""
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)
    plugin = DummyTestPlugin()
    pm.register_plugin(plugin)

    bus = TelemetryBus()
    pm.connect_telemetry_bus(bus)
    sensors = VehicleSensors()
    sensors.vehicle_speed = 33.3

    bus.process_frame(sensors)

    assert len(plugin.received_frames) == 1
    assert plugin.received_frames[0].vehicle_speed == 33.3
    assert bus.latest_sensors.vehicle_speed == 33.3


def test_overlay_state_machine_contextual_transitions(qapp):
    """Test game scene transitions: Desktop -> Menu -> Garage/Pause -> On-Track Driving."""
    osm = OverlayStateMachine(display_mode=OverlayDisplayMode.AUTO)

    # 1. Initially Desktop (Game not running)
    osm._evaluate_state()
    assert osm.current_scene == GameSceneState.DESKTOP
    assert osm.is_overlay_visible is False

    # 2. Game running in Foreground, but no telemetry yet -> MAIN_MENU
    osm._latest_game_status = GameStatus(state=GameFocusState.FOREGROUND, is_running=True, is_foreground=True)
    osm._evaluate_state()
    assert osm.current_scene == GameSceneState.MAIN_MENU
    assert osm.is_overlay_visible is False

    # 3. Telemetry received with in_realtime=False -> GARAGE_PAUSE
    garage_sensors = VehicleSensors(in_realtime=False)
    osm.update_telemetry(garage_sensors)
    osm._evaluate_state()
    assert osm.current_scene == GameSceneState.GARAGE_PAUSE
    assert osm.is_overlay_visible is False  # HUD recessed so setup screen is visible

    # 4. Telemetry received with in_realtime=True -> ON_TRACK_DRIVING
    track_sensors = VehicleSensors(in_realtime=True, vehicle_speed=45.0)
    osm.update_telemetry(track_sensors)
    osm._evaluate_state()
    assert osm.current_scene == GameSceneState.ON_TRACK_DRIVING
    assert osm.is_overlay_visible is True  # HUD automatically displayed on track!

    # 5. Alt-Tab to desktop (Game backgrounded) -> DESKTOP
    osm.update_game_status(GameStatus(state=GameFocusState.BACKGROUND, is_running=True, is_foreground=False))
    osm._evaluate_state()
    assert osm.current_scene == GameSceneState.DESKTOP
    assert osm.is_overlay_visible is False

    # 6. Force Visible override
    osm.set_display_mode(OverlayDisplayMode.FORCE_VISIBLE)
    assert osm.is_overlay_visible is True


def test_game_process_watcher_and_status_bar(qapp, tmp_path):
    """Test GameProcessWatcher and SimPulseCoreStatusBar rendering and state transitions."""
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)
    bus = TelemetryBus()
    watcher = GameProcessWatcher()
    osm = OverlayStateMachine()

    status_bar = SimPulseCoreStatusBar(
        process_watcher=watcher,
        overlay_state_machine=osm,
        telemetry_bus=bus,
        plugin_manager=pm
    )

    assert "Waiting for game" in status_bar.lbl_host_msg.text()
    assert "LMU:" in status_bar.badge_game.text()
    assert "UDP:" in status_bar.badge_udp.text()

    # Simulate game foreground on track
    osm._latest_game_status = GameStatus(state=GameFocusState.FOREGROUND, is_running=True, is_foreground=True)
    osm.update_telemetry(VehicleSensors(in_realtime=True))
    osm._evaluate_state()

    assert "ON TRACK" in status_bar.badge_game.text()
    assert "VISIBLE" in status_bar.badge_overlay.text()

    # Simulate garage pause
    osm.update_telemetry(VehicleSensors(in_realtime=False))
    osm._evaluate_state()
    assert "GARAGE" in status_bar.badge_game.text()
    assert "HIDDEN" in status_bar.badge_overlay.text()


def test_udp_server_to_telemetry_bus_integration(qapp, tmp_path):
    """Test UDPServer packet dispatching into TelemetryBus and PluginManager."""
    from isimotor_rawudp_client import TelemInfo, TelemVect3, CompactScoring
    from simpulse.builtin_plugins.stream_diagnostics import TelemetryDiagnosticsPlugin

    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)
    diag_plugin = TelemetryDiagnosticsPlugin()
    pm.register_plugin(diag_plugin)

    bus = TelemetryBus()
    pm.connect_telemetry_bus(bus)

    # 1. Simulate datagram callback from UDPServer for TelemInfo
    telem = TelemInfo(local_vel=TelemVect3(0.0, 0.0, 62.5), gear=3, engine_rpm=6500.0)

    bus._on_udp_packet_received("Telemetry", telem, 640)

    # Verify metrics updated
    stats = diag_plugin.get_channel_statistics()
    assert stats[TelemetryChannel.TELEMETRY].packet_count == 1
    assert stats[TelemetryChannel.TELEMETRY].total_bytes == 640
    assert bus.latest_sensors.vehicle_speed == 62.5
    assert bus.latest_sensors.gear == 3
    assert bus.latest_sensors.engine_rpm == 6500.0

    # 2. Simulate CompactScoring packet
    scoring = CompactScoring(cur_sector1=24.120, count_lap_flag=2, total_laps=5)
    bus._on_udp_packet_received("CompactScoring", scoring, 184)

    stats = diag_plugin.get_channel_statistics()
    assert stats[TelemetryChannel.COMPACT_SCORING].packet_count == 1
    assert stats[TelemetryChannel.COMPACT_SCORING].total_bytes == 184
    assert bus.latest_sensors.lap_flag == 2


def test_overlay_state_machine_automatic_signal_transitions(qapp):
    """Verify that update_game_status and update_telemetry trigger signals immediately without manual evaluate."""
    osm = OverlayStateMachine(display_mode=OverlayDisplayMode.AUTO)

    scene_history = []
    visibility_history = []
    osm.scene_changed.connect(lambda sc: scene_history.append(sc))
    osm.overlay_visibility_changed.connect(lambda vis: visibility_history.append(vis))

    # 1. Game focused in foreground with no telemetry -> MAIN_MENU
    osm.update_game_status(GameStatus(state=GameFocusState.FOREGROUND, is_running=True, is_foreground=True))
    assert osm.current_scene == GameSceneState.MAIN_MENU
    assert osm.is_overlay_visible is False
    assert scene_history[-1] == GameSceneState.MAIN_MENU

    # 2. Telemetry starts in garage -> GARAGE_PAUSE
    osm.update_telemetry(VehicleSensors(in_realtime=False))
    assert osm.current_scene == GameSceneState.GARAGE_PAUSE
    assert osm.is_overlay_visible is False
    assert scene_history[-1] == GameSceneState.GARAGE_PAUSE

    # 3. Car drives onto track -> ON_TRACK_DRIVING (Overlay visible!)
    osm.update_telemetry(VehicleSensors(in_realtime=True, vehicle_speed=35.0))
    assert osm.current_scene == GameSceneState.ON_TRACK_DRIVING
    assert osm.is_overlay_visible is True
    assert scene_history[-1] == GameSceneState.ON_TRACK_DRIVING
    assert visibility_history[-1] is True

    # 4. Alt-Tab to desktop -> DESKTOP (Overlay hidden!)
    osm.update_game_status(GameStatus(state=GameFocusState.BACKGROUND, is_running=True, is_foreground=False))
    assert osm.current_scene == GameSceneState.DESKTOP
    assert osm.is_overlay_visible is False
    assert scene_history[-1] == GameSceneState.DESKTOP
    assert visibility_history[-1] is False


def test_telemetry_bus_full_scoring_garage_integration(qapp, tmp_path):
    """Test that FullScoringSession in garage stall updates TelemetryBus and OverlayStateMachine."""
    from isimotor_rawudp_client import FullScoringSession, VehicleScoring, TelemInfo, TelemVect3

    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)
    bus = TelemetryBus()
    # Wire the Store: in_realtime is now fused by TelemetryStateStore's
    # PresenceTracker, fed by TelemetryBus.process_raw_packet's merge step —
    # without this connection the Store never sees these packets. Every sibling
    # test in this file that needs correct in_realtime already wires this.
    pm.connect_telemetry_bus(bus)
    osm = OverlayStateMachine(display_mode=OverlayDisplayMode.AUTO)
    bus.telemetry_updated.connect(osm.update_telemetry)

    # Game is in foreground
    osm.update_game_status(GameStatus(state=GameFocusState.FOREGROUND, is_running=True, is_foreground=True))

    # 1. Driving telemetry on track
    telem = TelemInfo(local_vel=TelemVect3(0.0, 0.0, 45.0), gear=3)
    bus._on_udp_packet_received("Telemetry", telem, 640)
    assert bus.latest_sensors.in_realtime is True
    assert osm.current_scene == GameSceneState.ON_TRACK_DRIVING
    assert osm.is_overlay_visible is True

    # 2. Car returns to garage stall in FullScoring
    player = VehicleScoring(id=1, is_player=True, in_garage_stall=True, in_pits=True)
    session = FullScoringSession(in_realtime=True, game_phase=0, vehicles=[player])
    bus._on_udp_packet_received("FullScoring", session, 2480)

    assert bus.latest_sensors.in_realtime is False
    assert osm.current_scene == GameSceneState.GARAGE_PAUSE
    assert osm.is_overlay_visible is False


def test_window_focus_studio_parent_vs_lmu_and_hud():
    """Verify that focusing the SimPulse Studio parent console marks LMU as background, not in-game."""
    from simpulse.core.utils.window_utils import get_window_manager

    wm = get_window_manager()
    orig_get_pids = wm.get_lmu_pids
    try:
        wm.get_lmu_pids = lambda: {77777}

        # 1. SimPulse Studio Console window focused -> MUST NOT be LMU foreground!
        wm._active_window_info = ("SimPulse Studio Console (Qt6 Pure)", "simpulse", 99999)
        assert wm.is_lmu_foreground() is False

        # 2. Third-party app (e.g. Chrome / Discord / Desktop) -> False
        wm._active_window_info = ("Google Chrome", "google-chrome", 88888)
        assert wm.is_lmu_foreground() is False

        # 3. Transparent HUD Overlay floating over game -> True
        wm._active_window_info = ("SimPulse Qt6 HUD Overlay", "simpulse", 99999)
        assert wm.is_lmu_foreground() is True

        # 4. Le Mans Ultimate game focused -> True
        wm._active_window_info = ("Le Mans Ultimate", "lemansultimate", 77777)
        assert wm.is_lmu_foreground() is True
    finally:
        wm.get_lmu_pids = orig_get_pids


def test_official_cockpit_hud_plugin_lifecycle_and_typed_config(qapp, tmp_path):
    """Test OfficialCockpitHudPlugin lifecycle, typed configuration, and scaling."""
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    plugin = OfficialCockpitHudPlugin()
    ctx = PluginContext("simpulse.builtin.official_cockpit_hud", cfg_mgr)
    plugin.on_load(ctx)
    plugin.on_enable()

    assert isinstance(plugin.config, OfficialCockpitHudConfig)
    assert plugin.config.slot == HudSlot.COCKPIT_CENTER
    assert plugin.config.hud_enabled is True
    assert plugin.config.speed_unit == "kmh"
    assert plugin.config.scale == 1.0
    assert plugin.preferred_slot == HudSlot.COCKPIT_CENTER
    assert plugin.get_hud_size() == QSize(640, 300)

    # Test scaling
    plugin.config.scale = 1.2
    assert plugin.get_hud_size() == QSize(768, 360)

    # Test channel requirements
    reqs = plugin.get_channel_requirements()
    assert len(reqs) >= 2
    assert any(r.channel == TelemetryChannel.TELEMETRY for r in reqs)
    assert any(r.channel == TelemetryChannel.COMPACT_SCORING for r in reqs)


def test_official_cockpit_hud_rendering_and_telemetry_flow(qapp, tmp_path):
    """Test telemetry ingestion and full offscreen vector rendering for all 11 modular HUD widgets."""
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    plugin = OfficialCockpitHudPlugin()
    ctx = PluginContext("simpulse.builtin.official_cockpit_hud", cfg_mgr)
    plugin.on_load(ctx)
    plugin.on_enable()

    sensors = VehicleSensors(
        vehicle_speed=55.0,  # ~198 km/h
        gear=3,
        engine_rpm=6800.0,
        engine_max_rpm=8500.0,
        unfiltered_throttle=0.90,
        unfiltered_brake=0.45,
        ecu=VehicleECU(
            abs=AntiLockECU(active_raw=True, level=4),
            tc=TractionControlECU(active_raw=True, level=3),
        ),
        delta_time=-0.320,
        has_delta_reference=True,
        wheels=WheelSet(
            front_left=TireCorner(lock=0.35, lat_slip=0.25, lat_signed=-0.50),
            rear_left=TireCorner(spin=0.40),
        ),
        explicit_aero_load=0.75,
        lap_flag=2,
        _fuel_level=42.5,
        remaining_laps=18,
        _sector1_time="32.105",
        _sector1_status="purple",
        _sector2_time="44.230",
        _sector2_status="green",
        _sector3_time="31.890",
        _sector3_status="default",
    )

    plugin.on_telemetry_frame(sensors)

    # 1. Full vector render (Metric KM/H)
    img = QImage(640, 300, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    painter = QPainter(img)
    try:
        plugin.paint_hud(painter, 640.0, 300.0, sensors)
    finally:
        painter.end()

    assert not img.isNull()

    # 2. MPH Mode
    plugin.config.speed_unit = "mph"
    img_mph = QImage(640, 300, QImage.Format.Format_ARGB32_Premultiplied)
    img_mph.fill(0)
    painter_mph = QPainter(img_mph)
    try:
        plugin.paint_hud(painter_mph, 640.0, 300.0, sensors)
    finally:
        painter_mph.end()

    assert not img_mph.isNull()

    # 3. Lap Freeze Mode (Finish line crossing)
    sensors_freeze = VehicleSensors(
        vehicle_speed=50.0,
        gear=4,
        last_lap_time=92.45,
        last_lap_time_str="01:32.450",
        _last_lap_status="purple",
        is_lap_freeze_active=True,
        lap_flag=2,
    )
    img_freeze = QImage(640, 300, QImage.Format.Format_ARGB32_Premultiplied)
    img_freeze.fill(0)
    painter_freeze = QPainter(img_freeze)
    try:
        plugin.paint_hud(painter_freeze, 640.0, 300.0, sensors_freeze)
    finally:
        painter_freeze.end()

    assert not img_freeze.isNull()


def test_official_cockpit_hud_tab_and_preview(qapp, tmp_path):
    """Test Studio Tab instantiation, interactive UI controls and live preview update."""
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    plugin = OfficialCockpitHudPlugin()
    ctx = PluginContext("simpulse.builtin.official_cockpit_hud", cfg_mgr)
    plugin.on_load(ctx)
    plugin.on_enable()

    assert plugin.get_tab_title() == "Cockpit HUD"
    assert plugin.get_tab_icon() == "🏎️"

    tab = plugin.create_tab_widget()
    assert tab is not None

    sensors = VehicleSensors(
        vehicle_speed=40.0,
        gear=2,
        engine_rpm=5500.0,
        unfiltered_throttle=0.75,
        unfiltered_brake=0.20,
    )
    plugin.on_telemetry_frame(sensors)
    tab.update_telemetry_ui(sensors)

    assert "KM/H" in tab.lbl_speed_gear.text()
    assert "THR: 75%" in tab.lbl_pedals.text()


def test_plugin_activation_persistence(qapp, tmp_path):
    """Test that plugin activation/disablement is saved to configuration and restored on reload."""
    cfg_file = tmp_path / "config_persistence.json"
    cfg_mgr = ConfigManager(config_file=cfg_file)

    # 1. By default, unconfigured plugin is enabled
    assert cfg_mgr.is_plugin_enabled("test.dummy") is True

    # 2. Register plugin in PluginManager -> starts ENABLED by default
    pm = PluginManager(cfg_mgr)
    plugin = DummyTestPlugin()
    pm.register_plugin(plugin)
    assert plugin.state == PluginState.ENABLED

    # 3. Disable plugin via PluginManager -> updates state and persists in config file
    pm.disable_plugin("test.dummy")
    assert plugin.state == PluginState.DISABLED
    assert cfg_mgr.is_plugin_enabled("test.dummy") is False

    # 4. Create fresh ConfigManager from saved JSON file and verify persisted state
    cfg_mgr_reloaded = ConfigManager(config_file=cfg_file)
    assert cfg_mgr_reloaded.is_plugin_enabled("test.dummy") is False

    # 5. Create fresh PluginManager with reloaded config and register plugin -> must load as DISABLED
    pm2 = PluginManager(cfg_mgr_reloaded)
    plugin2 = DummyTestPlugin()
    pm2.register_plugin(plugin2)
    assert plugin2.state == PluginState.DISABLED
    assert len(pm2.get_tab_providers()) == 0

    # 6. Re-enable plugin via PluginManager -> persists True
    pm2.enable_plugin("test.dummy")
    assert plugin2.state == PluginState.ENABLED
    assert cfg_mgr_reloaded.is_plugin_enabled("test.dummy") is True
    assert len(pm2.get_tab_providers()) == 1

    # 7. Reload again to verify re-enabled persistence
    cfg_mgr_reloaded2 = ConfigManager(config_file=cfg_file)
    assert cfg_mgr_reloaded2.is_plugin_enabled("test.dummy") is True


def test_plugin_activation_config(tmp_path):
    """Test CoreConfigProvider is_plugin_enabled and set_plugin_enabled methods."""
    cfg_file = tmp_path / "config_ctx.json"
    cfg_mgr = ConfigManager(config_file=cfg_file)

    assert cfg_mgr.is_plugin_enabled("test.my_plugin") is True
    cfg_mgr.set_plugin_enabled("test.my_plugin", False)
    assert cfg_mgr.is_plugin_enabled("test.my_plugin") is False

    cfg_mgr.set_plugin_enabled("test.my_plugin", True)
    assert cfg_mgr.is_plugin_enabled("test.my_plugin") is True


def test_plugin_manager_widget_toggle_persists_config(qapp, tmp_path):
    """Test that toggling plugin in PluginManagerWidget persists state to config file."""
    from simpulse.ui.plugin_manager_widget import PluginManagerWidget

    cfg_file = tmp_path / "config_ui.json"
    cfg_mgr = ConfigManager(config_file=cfg_file)
    pm = PluginManager(cfg_mgr)
    plugin = DummyTestPlugin()
    pm.register_plugin(plugin)

    widget = PluginManagerWidget(pm)
    assert plugin.state == PluginState.ENABLED

    # Trigger toggle in UI
    widget._toggle_plugin("test.dummy")
    assert plugin.state == PluginState.DISABLED
    assert cfg_mgr.is_plugin_enabled("test.dummy") is False

    # Toggle back
    widget._toggle_plugin("test.dummy")
    assert plugin.state == PluginState.ENABLED
    assert cfg_mgr.is_plugin_enabled("test.dummy") is True


class EventHookSpyPlugin(SimPulsePlugin):
    """Plugin spy that captures all polymorphic event hook calls."""

    def __init__(self):
        super().__init__(PluginMetadata(
            id="test.event_spy",
            name="Event Spy Plugin",
            version="1.0.0",
        ))
        self.physics_ticks = []
        self.scoring_updates = []
        self.grid_updates = []
        self.weather_updates = []
        self.session_events = []
        self.raw_slot_blocked = None

    def on_physics_tick(self, state: TelemetryStateStore) -> None:
        self.physics_ticks.append((state.speed_kmh, state.gear))
        if self.raw_slot_blocked is None:
            try:
                _ = state.compact_scoring
                self.raw_slot_blocked = False
            except AttributeError:
                self.raw_slot_blocked = True

    def on_scoring_update(self, state: TelemetryStateStore) -> None:
        self.scoring_updates.append((state.lap_flag, state.total_laps))

    def on_grid_update(self, state: TelemetryStateStore) -> None:
        # Consolidated grid state is populated when the frame embeds a player slot;
        # this spy only asserts the hook fired through the safe view.
        self.grid_updates.append(True)

    def on_weather_update(self, state: TelemetryStateStore) -> None:
        self.weather_updates.append(True)

    def on_session_event(self, state: TelemetryStateStore) -> None:
        self.session_events.append(True)


def test_plugin_manager_polymorphic_event_dispatch(qapp, tmp_path):
    """Test that PluginManager dispatches typed polymorphic event hooks to plugins reading from TelemetryStateStore."""
    from isimotor_rawudp_client import TelemInfo, TelemVect3, CompactScoring, FullScoringSession, WeatherControl
    from simpulse.core.telemetry.state_store import TelemetryStateStore


    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)
    spy = EventHookSpyPlugin()
    pm.register_plugin(spy)

    store = TelemetryStateStore.get_instance()
    store.reset()

    # dispatch_packet() no longer merges the raw packet into the Store itself —
    # TelemetryBus.process_raw_packet() does that exactly once, before emitting
    # packet_received (see telemetry_bus.py's _STORE_MERGE_METHODS). Tests driving
    # dispatch_packet() directly (bypassing TelemetryBus/Qt) must merge first, same
    # as TelemetryBus would.

    # 1. Physics Tick / Telemetry packet
    telem = TelemInfo(local_vel=TelemVect3(0.0, 0.0, 50.0), gear=4)
    store.update_telemetry(telem, timestamp=time.time())
    pm.dispatch_packet(TelemetryRawPacket(channel=TelemetryChannel.TELEMETRY, data=telem))

    assert len(spy.physics_ticks) == 1
    assert spy.physics_ticks[0][0] == pytest.approx(180.0, 0.1)
    assert spy.physics_ticks[0][1] == 4
    assert store.telemetry.is_fresh()
    # Raw UDP ingress must be structurally unreachable from plugin hooks.
    assert spy.raw_slot_blocked is True

    # 2. Compact Scoring packet
    compact = CompactScoring(count_lap_flag=2, total_laps=8)
    store.update_compact_scoring(compact, timestamp=time.time())
    pm.dispatch_packet(TelemetryRawPacket(channel=TelemetryChannel.COMPACT_SCORING, data=compact))

    assert len(spy.scoring_updates) == 1
    assert spy.scoring_updates[0] == (2, 8)
    assert store.compact_scoring.is_fresh()

    # 3. Full Scoring packet
    full_session = FullScoringSession(in_realtime=True, vehicles=[])
    store.update_full_scoring(full_session, timestamp=time.time())
    pm.dispatch_packet(TelemetryRawPacket(channel=TelemetryChannel.FULL_SCORING, data=full_session))

    assert len(spy.grid_updates) == 1
    assert spy.grid_updates[0] is True

    # 4. Weather packet
    weather = WeatherControl(ambient_temp_k=298.15)
    store.update_weather(weather, timestamp=time.time())
    pm.dispatch_packet(TelemetryRawPacket(channel=TelemetryChannel.WEATHER, data=weather))


    assert len(spy.weather_updates) == 1
    assert spy.weather_updates[0] is True


class RawIngestSpyPlugin(SimPulsePlugin, ITelemetrySubscriber):
    """Declares _REQUIRE_RAW_INGEST: the dispatcher must hand it the live
    TelemetryStateStore itself, not the read-only TelemetryView snapshot."""

    _REQUIRE_RAW_INGEST = True

    def __init__(self):
        super().__init__(PluginMetadata(
            id="test.raw_ingest_spy", name="Raw Ingest Spy Plugin", version="1.0.0",
        ))
        self.received_real_store = None

    def on_physics_tick(self, state) -> None:
        from simpulse.core.telemetry.state_store import TelemetryStateStore
        self.received_real_store = isinstance(state, TelemetryStateStore)


def test_plugin_manager_raw_ingest_hands_real_store(qapp, tmp_path):
    """_REQUIRE_RAW_INGEST plugins (race_engineer's whole EngineerContext plumbing:
    consume_validity_transition()/is_dirty_lap/wheels_on_track/... need the full
    mutable Store, not a frozen per-tick View) must receive the actual
    TelemetryStateStore singleton from dispatch_packet, not view=store.snapshot()."""
    from isimotor_rawudp_client import TelemInfo, TelemVect3
    from simpulse.core.telemetry.state_store import TelemetryStateStore
    from simpulse.builtin_plugins.race_engineer.plugin import RaceEngineerPlugin

    assert RaceEngineerPlugin._REQUIRE_RAW_INGEST is True

    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)
    spy = RawIngestSpyPlugin()
    pm.register_plugin(spy)

    store = TelemetryStateStore.get_instance()
    store.reset()
    telem = TelemInfo(local_vel=TelemVect3(0.0, 0.0, 10.0), gear=2)
    store.update_telemetry(telem, timestamp=time.time())
    pm.dispatch_packet(TelemetryRawPacket(channel=TelemetryChannel.TELEMETRY, data=telem))

    assert spy.received_real_store is True


def test_plugin_manager_widget_inspector_on_right(qapp, tmp_path):
    """Test that Plugin Inspector is placed in a horizontal layout to the right of the plugins table."""
    from PySide6.QtWidgets import QHBoxLayout, QGroupBox
    from simpulse.ui.plugin_manager_widget import PluginManagerWidget

    cfg_file = tmp_path / "config_ui.json"
    cfg_mgr = ConfigManager(config_file=cfg_file)
    pm = PluginManager(cfg_mgr)
    widget = PluginManagerWidget(pm)

    # Find the horizontal content layout
    h_layouts = widget.findChildren(QHBoxLayout)
    content_layout = next(
        (hl for hl in h_layouts if hl.indexOf(widget.table) != -1),
        None
    )
    assert content_layout is not None, "Plugins table must be in a QHBoxLayout"

    table_idx = content_layout.indexOf(widget.table)
    # The inspector QGroupBox must be after the table in the horizontal layout (i.e. to the right)
    assert table_idx == 0
    inspector_item = content_layout.itemAt(1)
    assert inspector_item is not None
    inspector_widget = inspector_item.widget()
    assert isinstance(inspector_widget, QGroupBox)
    assert inspector_widget.title() == "Plugin Inspector"


def test_simpulse_window_title(qapp, tmp_path):
    """Test that the main studio console window title is set to 'SimPulse'."""
    from simpulse.ui.main_window import SimPulseMainWindow
    from simpulse.core.game_plugin_manager import GamePluginManager
    from simpulse.core.game_process_watcher import GameProcessWatcher
    from simpulse.core.overlay_state_machine import OverlayStateMachine
    from simpulse.core.telemetry_bus import TelemetryBus

    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)
    gpm = GamePluginManager(config_manager=cfg_mgr)
    gw = GameProcessWatcher()
    osm = OverlayStateMachine()
    tb = TelemetryBus()

    window = SimPulseMainWindow(
        plugin_manager=pm,
        game_plugin_mgr=gpm,
        process_watcher=gw,
        overlay_state_machine=osm,
        telemetry_bus=tb,
        config_mgr=cfg_mgr,
    )
    assert window.windowTitle() == "SimPulse"


def test_game_plugin_config_widget_compact_layout(qapp, tmp_path):
    """Test that GamePluginConfigWidget uses compact QSizePolicy.Policy.Maximum and layout stretch."""
    from PySide6.QtWidgets import QSizePolicy
    from simpulse.ui.game_plugin_config_widget import GamePluginConfigWidget
    from simpulse.core.game_plugin_manager import GamePluginManager

    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)
    gpm = GamePluginManager(config_manager=cfg_mgr)

    widget = GamePluginConfigWidget(game_plugin_mgr=gpm, plugin_mgr=pm)
    assert widget.desiderata_table.height() <= 160
    assert widget.inst_group.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Maximum


def test_all_eleven_channels_have_on_hooks_and_zero_none(qapp, tmp_path):
    """Test that all 11 TelemetryChannel entries have a dedicated on_* hook and no None in routing."""
    from simpulse_sdk import (
        SimPulsePlugin, PluginMetadata, PluginContext,
        TelemetryChannel, TelemetryRawPacket, TelemetryStateStore,
    )
    from isimotor_rawudp_client import TelemInfo, CompactScoring, FullScoringSession, WeatherControl, SystemEvent, ExtendedState, ForceFeedback, Graphics

    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)

    # 1. Assert all 11 channels are in CHANNEL_ROUTING and none are None
    assert len(pm.CHANNEL_ROUTING) == 11
    for ch in TelemetryChannel:
        assert ch in pm.CHANNEL_ROUTING
        hook_name = pm.CHANNEL_ROUTING[ch]
        assert hook_name is not None
        assert hook_name.startswith("on_")

    # 2. Create a test plugin implementing all 11 on_* hooks
    received_hooks = set()

    class AllChannelsObserverPlugin(SimPulsePlugin, ITelemetryStateSubscriber):
        def __init__(self):
            super().__init__(PluginMetadata(id="test.all_channels", name="All Channels Observer", version="1.0.0"))

        def on_physics_tick(self, state: TelemetryStateStore) -> None:
            received_hooks.add("on_physics_tick")

        def on_opponents_tick(self, state: TelemetryStateStore) -> None:
            received_hooks.add("on_opponents_tick")

        def on_scoring_update(self, state: TelemetryStateStore) -> None:
            received_hooks.add("on_scoring_update")

        def on_grid_update(self, state: TelemetryStateStore) -> None:
            received_hooks.add("on_grid_update")

        def on_weather_update(self, state: TelemetryStateStore) -> None:
            received_hooks.add("on_weather_update")

        def on_extended_state_update(self, state: TelemetryStateStore) -> None:
            received_hooks.add("on_extended_state_update")

        def on_session_event(self, state: TelemetryStateStore) -> None:
            received_hooks.add("on_session_event")

        def on_ffb_update(self, state: TelemetryStateStore) -> None:
            received_hooks.add("on_ffb_update")

        def on_graphics_update(self, state: TelemetryStateStore) -> None:
            received_hooks.add("on_graphics_update")

        def on_track_rules_update(self, state: TelemetryStateStore) -> None:
            received_hooks.add("on_track_rules_update")

        def on_pit_menu_update(self, state: TelemetryStateStore) -> None:
            received_hooks.add("on_pit_menu_update")

    plugin = AllChannelsObserverPlugin()
    pm.register_plugin(plugin)
    plugin.on_load(PluginContext(plugin.metadata.id, cfg_mgr))
    plugin.on_enable()

    # 3. Dispatch one packet for each channel
    packets = [
        TelemetryRawPacket(channel=TelemetryChannel.TELEMETRY, data=TelemInfo(), raw_bytes_len=640),
        TelemetryRawPacket(channel=TelemetryChannel.OPPONENT_TELEMETRY, data=TelemInfo(), raw_bytes_len=640),
        TelemetryRawPacket(channel=TelemetryChannel.COMPACT_SCORING, data=CompactScoring(), raw_bytes_len=184),
        TelemetryRawPacket(channel=TelemetryChannel.FULL_SCORING, data=FullScoringSession(), raw_bytes_len=2480),
        TelemetryRawPacket(channel=TelemetryChannel.WEATHER, data=WeatherControl(), raw_bytes_len=120),
        TelemetryRawPacket(channel=TelemetryChannel.EXTENDED_STATE, data=ExtendedState(), raw_bytes_len=80),
        TelemetryRawPacket(channel=TelemetryChannel.SYSTEM_EVENTS, data=SystemEvent(), raw_bytes_len=64),
        TelemetryRawPacket(channel=TelemetryChannel.FORCE_FEEDBACK, data=ForceFeedback(), raw_bytes_len=48),
        TelemetryRawPacket(channel=TelemetryChannel.GRAPHICS, data=Graphics(), raw_bytes_len=96),
        TelemetryRawPacket(channel=TelemetryChannel.TRACK_RULES, data={"rules": "ok"}, raw_bytes_len=32),
        TelemetryRawPacket(channel=TelemetryChannel.PIT_MENU, data={"menu": 1}, raw_bytes_len=32),
    ]

    for pkt in packets:
        pm.dispatch_packet(pkt)

    # 4. Verify all 11 hooks fired
    assert len(received_hooks) == 11
    assert "on_physics_tick" in received_hooks
    assert "on_opponents_tick" in received_hooks
    assert "on_scoring_update" in received_hooks
    assert "on_grid_update" in received_hooks
    assert "on_weather_update" in received_hooks
    assert "on_extended_state_update" in received_hooks
    assert "on_session_event" in received_hooks
    assert "on_ffb_update" in received_hooks
    assert "on_graphics_update" in received_hooks
    assert "on_track_rules_update" in received_hooks
    assert "on_pit_menu_update" in received_hooks




