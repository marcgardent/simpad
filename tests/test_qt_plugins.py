"""
Unit and Integration Tests for the SimPad Qt6 Strongly-Typed Plugin Architecture.
"""

from dataclasses import dataclass
from pathlib import Path
import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from simpad_qt.plugins.contracts import (
    SimPadPlugin, PluginMetadata, PluginContext, PluginState,
    HudSlot, HudLayoutSpec, PluginErrorReport,
    ITabProvider, ITelemetrySubscriber, IPacketSubscriber, IHudWidgetProvider
)
from simpad_qt.plugins.manager import PluginManager
from simpad_qt.core.config import ConfigManager, AppSettings
from simpad_qt.core.telemetry_channels import (
    TelemetryChannel, ChannelRequirement, TelemetryRawPacket
)
from simpad_qt.core.game_plugin_manager import GamePluginManager
from simpad_qt.core.game_process_watcher import GameProcessWatcher, GameStatus, GameFocusState
from simpad_qt.core.overlay_state_machine import (
    OverlayStateMachine, GameSceneState, OverlayDisplayMode, OverlayStateSnapshot
)
from simpad_qt.core.telemetry_bus import TelemetryBus, UdpStreamStatus
from simpad_qt.ui.slot_compositor import HudSlotCompositor
from simpad_qt.ui.status_bar import SimPadCoreStatusBar
from simpad_qt.builtin_plugins.gear_speed_hud import GearSpeedHudPlugin
from simpad_qt.builtin_plugins.gear_speed_hud.plugin import GearSpeedConfig
from simpad_qt.builtin_plugins.pedal_monitor import PedalTelemetryPlugin
from simpad_qt.builtin_plugins.pedal_monitor.plugin import PedalMonitorConfig
from simpad_qt.builtin_plugins.stream_diagnostics import TelemetryDiagnosticsPlugin
from src.telemetry.sensors import VehicleSensors


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


class DummyTestPlugin(SimPadPlugin, ITabProvider, ITelemetrySubscriber, IHudWidgetProvider):
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


class FaultyTestPlugin(SimPadPlugin, ITelemetrySubscriber):
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

    # Send 10 packets of Telemetry (640 bytes)
    for _ in range(10):
        packet = TelemetryRawPacket(
            channel=TelemetryChannel.TELEMETRY,
            data=VehicleSensors(),
            raw_bytes_len=640
        )
        diag_plugin.on_telemetry_packet(packet)

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
    ctx = PluginContext("simpad.builtin.gear_speed_hud", cfg_mgr)
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
    ctx = PluginContext("simpad.builtin.pedal_monitor", cfg_mgr)
    plugin.on_load(ctx)
    plugin.on_enable()

    assert isinstance(plugin.config, PedalMonitorConfig)
    assert plugin.config.slot == HudSlot.BOTTOM_LEFT

    sensors = VehicleSensors()
    sensors.unfiltered_throttle = 0.85
    sensors.unfiltered_brake = 0.60
    sensors.ecu_abs_active_raw = True
    sensors.ecu_tc_active_raw = True
    sensors.front_left_lock = 0.90
    sensors.rear_left_spin = 0.75

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

    bus = TelemetryBus(pm)
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
    """Test GameProcessWatcher and SimPadCoreStatusBar rendering and state transitions."""
    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)
    bus = TelemetryBus(pm)
    watcher = GameProcessWatcher()
    osm = OverlayStateMachine()

    status_bar = SimPadCoreStatusBar(
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
    from simpad_qt.builtin_plugins.stream_diagnostics import TelemetryDiagnosticsPlugin

    cfg_mgr = ConfigManager(config_file=tmp_path / "cfg.json")
    pm = PluginManager(cfg_mgr)
    diag_plugin = TelemetryDiagnosticsPlugin()
    pm.register_plugin(diag_plugin)

    bus = TelemetryBus(pm)

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
    bus = TelemetryBus(pm)
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
    """Verify that focusing the SimPad Studio parent console marks LMU as background, not in-game."""
    from src.utils.window_utils import get_window_manager

    wm = get_window_manager()

    # 1. SimPad Studio Console window focused -> MUST NOT be LMU foreground!
    wm._active_window_info = ("SimPad Studio Console (Qt6 Pure)", "simpad", 99999)
    assert wm.is_lmu_foreground() is False

    # 2. Third-party app (e.g. Chrome / Discord / Desktop) -> False
    wm._active_window_info = ("Google Chrome", "google-chrome", 88888)
    assert wm.is_lmu_foreground() is False

    # 3. Transparent HUD Overlay floating over game -> True
    wm._active_window_info = ("SimPad Qt6 HUD Overlay", "simpad", 99999)
    assert wm.is_lmu_foreground() is True

    # 4. Le Mans Ultimate game focused -> True
    wm._active_window_info = ("Le Mans Ultimate", "lemansultimate", 77777)
    assert wm.is_lmu_foreground() is True
