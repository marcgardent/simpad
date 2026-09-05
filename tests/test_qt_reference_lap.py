"""
Unit and Integration Tests for the Core Reference Lap & Delta Management Subsystem (Qt6 Pure).
Verifies:
- Strongly-typed LapDeltaPacket serialization and immutability.
- ReferenceLapManager service lifecycle, multi-reference hierarchy, and Qt signals.
- Spatial 1m query interpolation and Track Annotations CRUD.
- IDeltaSubscriber capability protocol and dispatching via PluginManager.
- Integration between TelemetryBus, ReferenceLapManager, and OfficialCockpitHudPlugin.
"""

import tempfile
import time
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication

from simpad_qt.core.config import ConfigManager, AppSettings
from simpulse_sdk import (
    SimPulsePlugin,
    PluginMetadata,
    PluginContext,
    IDeltaSubscriber,
    ITelemetrySubscriber,
    LapDeltaPacket,
    DeltaReferenceMode,
    VehicleSensors,
)
from simpad_qt.core.reference_lap import (
    ReferenceLapManager,
    ReferenceLapProfile,
    TrackAnnotation,
    AnnotationType,
)
from simpad_qt.plugins.manager import PluginManager
from simpad_qt.core.telemetry_bus import TelemetryBus
from simpad_qt.builtin_plugins.official_cockpit_hud import OfficialCockpitHudPlugin


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class DummyDeltaSubscriberPlugin(SimPulsePlugin, IDeltaSubscriber, ITelemetrySubscriber):
    """Plugin implementing IDeltaSubscriber to verify delta stream ingestion."""

    def __init__(self):
        super().__init__(PluginMetadata(
            id="test.delta_sub",
            name="Delta Subscriber Test",
            version="1.0.0"
        ))
        self.received_deltas = []
        self.received_telemetry = []

    def on_delta_frame(self, delta_packet: LapDeltaPacket) -> None:
        self.received_deltas.append(delta_packet)

    def on_telemetry_frame(self, sensors: VehicleSensors) -> None:
        self.received_telemetry.append(sensors)


def test_lap_delta_packet_immutability_and_dict(qapp):
    """Verify LapDeltaPacket defaults, immutability, and dictionary export."""
    pkt = LapDeltaPacket(
        live_delta=-0.342,
        display_delta=-0.342,
        delta_str="-0.342",
        has_reference=True,
        ref_lap_time=90.0,
        ref_lap_time_str="01:30.000",
        current_sector=2,
        sector1_delta=-0.150,
        sector1_time="29.850",
        sector1_status="purple",
        last_lap_time=90.450,
        last_lap_time_str="01:30.450",
        last_lap_status="green",
        track_name="Spa-Francorchamps",
        track_length=7004.0,
    )

    assert pkt.live_delta == -0.342
    assert pkt.has_reference is True
    assert pkt.current_sector == 2
    assert pkt.sector1_status == "purple"
    assert pkt.track_name == "Spa-Francorchamps"

    # Verify immutability
    with pytest.raises(Exception):
        pkt.live_delta = 1.0  # type: ignore

    # Verify dictionary serialization
    d = pkt.to_dict()
    assert isinstance(d, dict)
    assert d["live_delta"] == -0.342
    assert d["track_name"] == "Spa-Francorchamps"
    assert d["has_reference"] is True


def test_reference_lap_manager_lifecycle_and_config(qapp, tmp_path):
    """Verify ReferenceLapManager initialization with ConfigManager and persistence."""
    cfg_file = tmp_path / "config_qt.json"
    cfg_mgr = ConfigManager(config_file=cfg_file)
    cfg_mgr.config.app.delta_reference_mode = "session_best"
    cfg_mgr.config.app.delta_freeze_duration = 4.5
    cfg_mgr.config.app.delta_ema_samples = 3
    cfg_mgr.save()

    mgr = ReferenceLapManager(config_manager=cfg_mgr)
    assert mgr.reference_mode == DeltaReferenceMode.SESSION_BEST
    assert mgr.delta_engine.freeze_duration == 4.5
    assert mgr.delta_engine.ema_samples == 3

    # Switch reference mode
    mgr.set_reference_mode("all_time_best")
    assert mgr.reference_mode == DeltaReferenceMode.ALL_TIME_BEST
    assert cfg_mgr.config.app.delta_reference_mode == "all_time_best"

    # Switch freeze duration
    mgr.set_freeze_duration(5.0)
    assert mgr.delta_engine.freeze_duration == 5.0
    assert cfg_mgr.config.app.delta_freeze_duration == 5.0


def test_reference_lap_manager_annotations_crud(qapp, tmp_path):
    """Verify adding, moving, and removing track annotations via ReferenceLapManager."""
    cfg_mgr = ConfigManager(config_file=tmp_path / "config_qt.json")
    mgr = ReferenceLapManager(config_manager=cfg_mgr)

    # Setup fake active reference profile
    prof = ReferenceLapProfile(
        track_name="TestCircuit",
        vehicle_name="TestCar",
        lap_time=60.0,
        track_length=2000.0,
        spatial_step=1.0,
        num_points=2001,
        t_grid=[(d / 2000.0) * 60.0 for d in range(2001)],
    )
    prof.set_marks_filepath(tmp_path / "ref_testcircuit_testcar.marks.json")
    mgr.delta_engine._all_time_best_profile = prof
    mgr.delta_engine._apply_active_profile()

    signals_caught = []
    mgr.annotations_changed.connect(lambda anns: signals_caught.append(len(anns)))

    # 1. Add Brake annotation at 500m
    ann1 = mgr.add_annotation(AnnotationType.BRAKE, distance=500.0, label="Heavy Brake")
    assert ann1 is not None
    assert ann1.distance == 500.0
    assert ann1.type == AnnotationType.BRAKE
    assert len(mgr.get_annotations()) == 1
    assert len(signals_caught) == 1

    # 2. Add Turn annotation at 600m
    ann2 = mgr.add_annotation(AnnotationType.TURN, distance=600.0)
    assert ann2 is not None
    assert len(mgr.get_annotations()) == 2
    assert len(signals_caught) == 2

    # 3. Move Brake annotation to 480m
    ok_move = mgr.move_annotation(ann1.id, new_distance=480.0)
    assert ok_move is True
    anns = mgr.get_annotations()
    assert anns[0].distance == 480.0
    assert len(signals_caught) == 3

    # 4. Remove Turn annotation
    ok_remove = mgr.remove_annotation(ann2.id)
    assert ok_remove is True
    assert len(mgr.get_annotations()) == 1
    assert len(signals_caught) == 4


def test_reference_lap_manager_delta_calc_and_signals(qapp, tmp_path):
    """Verify live delta updates and Qt signals on scoring and physics updates."""
    cfg_mgr = ConfigManager(config_file=tmp_path / "config_qt.json")
    mgr = ReferenceLapManager(config_manager=cfg_mgr)

    # Establish reference lap: 1000m track, 50s lap time
    prof = ReferenceLapProfile(
        track_name="Monza",
        vehicle_name="Hypercar",
        lap_time=50.0,
        track_length=1000.0,
        spatial_step=1.0,
        num_points=1001,
        t_grid=[(d / 1000.0) * 50.0 for d in range(1001)],  # 20 m/s
    )
    mgr.delta_engine._track_name = "Monza"
    mgr.delta_engine._vehicle_name = "Hypercar"
    mgr.delta_engine._track_length = 1000.0
    mgr.delta_engine._all_time_best_profile = prof
    mgr.delta_engine._all_time_best_lap_time = 50.0
    mgr.delta_engine._apply_active_profile()

    deltas_caught = []
    mgr.delta_updated.connect(lambda pkt: deltas_caught.append(pkt))

    # Car at 400m (ref is 20.0s), current time into lap is 19.5s -> delta = -0.5s
    scoring_data = {
        "mTrackName": "Monza",
        "mLapDist": 1000.0,
        "mVehicles": [{
            "mIsPlayer": True,
            "mVehicleName": "Hypercar",
            "mLapDist": 400.0,
            "mTimeIntoLap": 19.5,
            "mSector": 1,
            "mCountLapFlag": 2,
        }]
    }
    pkt = mgr.update_scoring(scoring_data)
    assert len(deltas_caught) == 1
    assert pkt.has_reference is True
    assert pytest.approx(pkt.live_delta, 0.05) == -0.5
    assert pkt.delta_str.startswith("-0.5")


def test_telemetry_bus_and_plugin_delta_subscription(qapp, tmp_path):
    """Verify TelemetryBus broadcasts LapDeltaPacket to IDeltaSubscriber plugins."""
    cfg_mgr = ConfigManager(config_file=tmp_path / "config_qt.json")
    ref_mgr = ReferenceLapManager(config_manager=cfg_mgr)
    plugin_mgr = PluginManager(config_manager=cfg_mgr)

    # Register delta subscriber plugin and OfficialCockpitHudPlugin
    dummy_plugin = DummyDeltaSubscriberPlugin()
    hud_plugin = OfficialCockpitHudPlugin()
    plugin_mgr.register_plugin(dummy_plugin)
    plugin_mgr.register_plugin(hud_plugin)

    bus = TelemetryBus(reference_lap_mgr=ref_mgr)
    plugin_mgr.connect_telemetry_bus(bus)

    # Setup reference profile
    prof = ReferenceLapProfile(
        track_name="LeMans",
        vehicle_name="Porsche",
        lap_time=60.0,
        track_length=3000.0,
        spatial_step=1.0,
        num_points=3001,
        t_grid=[(d / 3000.0) * 60.0 for d in range(3001)],
    )
    ref_mgr.delta_engine._track_name = "LeMans"
    ref_mgr.delta_engine._vehicle_name = "Porsche"
    ref_mgr.delta_engine._track_length = 3000.0
    ref_mgr.delta_engine._all_time_best_profile = prof
    ref_mgr.delta_engine._all_time_best_lap_time = 60.0
    ref_mgr.delta_engine._apply_active_profile()

    # Feed scoring packet to TelemetryBus
    from isimotor_rawudp_client import VehicleScoring, FullScoringSession
    player = VehicleScoring(
        id=1,
        is_player=True,
        vehicle_name="Porsche",
        lap_dist=1500.0,
        time_into_lap=28.5,  # ref is 30.0s -> delta = -1.5s
        sector=2,
        count_lap_flag=2,
    )
    scoring_data = FullScoringSession(
        track_name="LeMans",
        lap_dist=3000.0,
        vehicles=[player],
    )

    from simpad_qt.core.telemetry_channels import TelemetryChannel
    bus.process_raw_packet(TelemetryChannel.FULL_SCORING, scoring_data, 184)

    # Verify dummy plugin received authoritative LapDeltaPacket
    assert len(dummy_plugin.received_deltas) == 1
    d_pkt = dummy_plugin.received_deltas[0]
    assert d_pkt.has_reference is True
    assert pytest.approx(d_pkt.live_delta, 0.1) == -1.5

    # Verify official cockpit HUD plugin received delta frame
    assert hud_plugin.latest_delta.has_reference is True
    assert pytest.approx(hud_plugin.latest_delta.live_delta, 0.1) == -1.5
    assert bus.latest_sensors.has_delta_reference is True
    assert pytest.approx(bus.latest_sensors.delta_time, 0.1) == -1.5

from simpad_qt.builtin_plugins.reference_lap_studio import ReferenceLapStudioPlugin
from simpad_qt.builtin_plugins.reference_lap_studio.plugin import (
    ReferenceLapStudioConfig,
    ReferenceLapStudioTabWidget,
    SpatialTelemetryCanvas,
)


def test_reference_lap_studio_plugin_and_tab_lifecycle(qapp, tmp_path):
    """Verify ReferenceLapStudioPlugin registration, tab creation, and interactive controls."""
    cfg_mgr = ConfigManager(config_file=tmp_path / "config_qt.json")
    plugin_mgr = PluginManager(config_manager=cfg_mgr)
    ref_mgr = ReferenceLapManager(config_manager=cfg_mgr)

    plugin = ReferenceLapStudioPlugin()
    plugin.ref_manager = ref_mgr
    plugin_mgr.register_plugin(plugin)

    assert plugin.metadata.id == "simpad.builtin.reference_lap_studio"
    assert plugin.get_tab_title() == "Reference Lap Studio"
    assert plugin.get_tab_icon() == "🗺️"

    # Create tab widget
    tab = plugin.create_tab_widget()
    assert isinstance(tab, ReferenceLapStudioTabWidget)

    # Establish fake profile
    prof = ReferenceLapProfile(
        track_name="Silverstone",
        vehicle_name="AstonMartin",
        lap_time=75.0,
        track_length=4000.0,
        spatial_step=1.0,
        num_points=4001,
        t_grid=[(d / 4000.0) * 75.0 for d in range(4001)],
    )
    prof.set_marks_filepath(tmp_path / "ref_silverstone_aston.marks.json")
    ref_mgr.delta_engine._track_name = "Silverstone"
    ref_mgr.delta_engine._vehicle_name = "AstonMartin"
    ref_mgr.delta_engine._track_length = 4000.0
    ref_mgr.delta_engine._all_time_best_profile = prof
    ref_mgr.delta_engine._all_time_best_lap_time = 75.0
    ref_mgr.delta_engine._apply_active_profile()

    tab.refresh_ui()

    assert "75.0" in tab.lbl_lap_time.text() or "01:15.000" in tab.lbl_lap_time.text()
    assert "4000" in tab.lbl_track_len.text()

    # Move cursor to 1200m
    tab.canvas.cursor_dist = 1200.0
    assert tab.canvas.cursor_dist == 1200.0
    assert "1200.0" in tab.lbl_cur_dist.text()

    # Add Brake marker via Tab action
    tab.add_marker_at_cursor(AnnotationType.BRAKE)
    assert len(tab.ref_manager.get_annotations()) == 1
    assert tab.table_marks.rowCount() == 1

    # Add Turn marker via Tab action
    tab.canvas.cursor_dist = 1400.0
    tab.add_marker_at_cursor(AnnotationType.TURN)
    assert len(tab.ref_manager.get_annotations()) == 2
    assert tab.table_marks.rowCount() == 2

    # Add Gear marker
    tab.canvas.cursor_dist = 1420.0
    tab.add_gear_marker(3)
    assert len(tab.ref_manager.get_annotations()) == 3
    assert tab.table_marks.rowCount() == 3

    # Delete selected marker
    tab._cb_delete_selected()
    assert len(tab.ref_manager.get_annotations()) == 2
    assert tab.table_marks.rowCount() == 2


def test_spatial_telemetry_canvas_rendering(qapp, tmp_path):
    """Verify SpatialTelemetryCanvas offscreen vector rendering with curves, markers, and cursor."""
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtCore import QSize

    cfg_mgr = ConfigManager(config_file=tmp_path / "config_qt.json")
    ref_mgr = ReferenceLapManager(config_manager=cfg_mgr)
    plugin = ReferenceLapStudioPlugin()
    plugin.ref_manager = ref_mgr

    tab = plugin.create_tab_widget()

    # Establish full profile with curves
    n = 2001
    prof = ReferenceLapProfile(
        track_name="Nurburgring",
        vehicle_name="BMW",
        lap_time=60.0,
        track_length=2000.0,
        spatial_step=1.0,
        num_points=n,
        t_grid=[(d / 2000.0) * 60.0 for d in range(n)],
        speed_grid=[50.0 + 10.0 * (i % 10) for i in range(n)],
        throttle_grid=[1.0 if i < 1000 else 0.0 for i in range(n)],
        brake_grid=[0.0 if i < 1000 else 0.8 for i in range(n)],
        steering_grid=[0.2 if i < 1000 else -0.2 for i in range(n)],
        gear_grid=[4 for _ in range(n)],
        sector_1_dist=600.0,
        sector_2_dist=1300.0,
    )
    prof.set_marks_filepath(tmp_path / "ref_nurburgring_bmw.marks.json")
    prof.add_annotation(AnnotationType.BRAKE, distance=1000.0, auto_save=False)
    prof.add_annotation(AnnotationType.TURN, distance=1100.0, auto_save=False)
    ref_mgr.delta_engine._all_time_best_profile = prof
    ref_mgr.delta_engine._all_time_best_lap_time = 60.0
    ref_mgr.delta_engine._apply_active_profile()

    tab.canvas.cursor_dist = 500.0
    tab.canvas.set_live_car_distance(800.0)
    tab.canvas.resize(800, 400)

    # Render to QImage
    img = QImage(QSize(800, 400), QImage.Format.Format_ARGB32)
    img.fill(0)
    tab.canvas.render(img)

    assert not img.isNull()
    assert img.width() == 800
    assert img.height() == 400
