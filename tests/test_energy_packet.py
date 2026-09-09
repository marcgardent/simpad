"""
Tests for EnergyPacket's build-push-emit pipeline — the same pattern
LapDeltaPacket uses (see simpulse_sdk/models/energy.py's docstring):
FuelEnergyEngine/session_energy_gauge -> TelemetryBus._apply_fuel_fields()
builds an EnergyPacket -> pushed into TelemetryStateStore (TelemetryView.energy)
-> emitted via TelemetryBus.energy_updated.
"""

import pytest
from PySide6.QtWidgets import QApplication
from isimotor_rawudp_client import CompactScoring, TelemInfo

from simpulse.core.telemetry_bus import TelemetryBus
from simpulse.core.telemetry.state_store import TelemetryStateStore
from simpulse_sdk.models.energy import EnergyPacket


@pytest.fixture
def qapp():
    """Ensure QApplication instance exists for offscreen Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_energy_packet_is_frozen_and_defaults():
    pkt = EnergyPacket(level=42.5, consumption_per_lap=4.9, session_energy_ratio=1.2)
    assert pkt.level == 42.5
    assert pkt.consumption_per_lap == 4.9
    assert pkt.session_energy_ratio == 1.2
    assert pkt.session_time_ratio is None
    try:
        pkt.level = 0.0  # frozen dataclass — must reject mutation
        assert False, "EnergyPacket should be immutable"
    except AttributeError:
        pass


def test_energy_packet_pushed_to_store_and_emitted_on_lap_completion(qapp):
    bus = TelemetryBus()
    received = []
    bus.energy_updated.connect(received.append)

    # Lap 1: fuel starts at 80L.
    bus._on_udp_packet_received("CompactScoring", CompactScoring(total_laps=0), 184)
    bus._on_udp_packet_received("Telemetry", TelemInfo(fuel=80.0), 640)

    # Lap 1 -> 2 transition: fuel drops to 75L (5L consumed), last_lap_time=100s.
    bus._on_udp_packet_received(
        "CompactScoring", CompactScoring(total_laps=1, last_lap_time=100.0), 184
    )
    bus._on_udp_packet_received("Telemetry", TelemInfo(fuel=75.0), 640)

    assert received, "energy_updated should have fired at least once"
    latest = bus.latest_energy
    assert isinstance(latest, EnergyPacket)
    assert latest.level == 75.0
    assert latest.consumption_per_lap == 5.0
    assert latest.lap_time_median == 100.0
    assert latest.projected_laps == 75.0 / 5.0

    # Single source of truth: TelemetryStateStore.snapshot().energy carries the
    # exact same packet TelemetryBus just emitted (see TelemetryView.energy).
    store = TelemetryStateStore.get_instance()
    snapshot_energy = store.snapshot().energy
    assert snapshot_energy is not None
    assert snapshot_energy.level == 75.0
    assert snapshot_energy.consumption_per_lap == 5.0


def test_energy_packet_reused_between_physics_ticks(qapp):
    """A non-TelemInfo tick (e.g. Weather) must not rebuild/reset the packet —
    it should reuse the last one, same as delta_updated does for LapDeltaPacket."""
    from isimotor_rawudp_client import WeatherControl

    bus = TelemetryBus()
    bus._on_udp_packet_received("CompactScoring", CompactScoring(total_laps=0), 184)
    bus._on_udp_packet_received("Telemetry", TelemInfo(fuel=50.0), 640)
    before = bus.latest_energy

    bus._on_udp_packet_received("Weather", WeatherControl(ambient_temp_k=295.0), 96)
    after = bus.latest_energy

    assert after is before
