"""
SimPulse Qt6 Telemetry Bus & Ingestion Pipeline.
Tracks real-time bandwidth (Kb/s), measured frequencies (Hz), per-channel statistics,
connects live UDP socket datagrams directly to plugins and coordinates authoritative delta & reference lap calculations.
"""

from __future__ import annotations
import time
import logging
from collections import deque
from enum import Enum
from typing import Optional, Dict, Union
from PySide6.QtCore import QObject, Signal, QTimer

from simpulse.core.telemetry import (
    VehicleSensors,
    UDPServer,
)
from simpulse.core.telemetry_channels import (
    TelemetryChannel, ChannelMetrics, TelemetryRawPacket, TelemetryPayload
)
from simpulse.core.reference_lap import ReferenceLapManager, LapDeltaPacket
from simpulse.core.mock_telemetry import MockTelemetryGenerator
from simpulse.core.telemetry.state_store import TelemetryStateStore
from isimotor_rawudp_client import (
    TelemInfo,
    CompactScoring,
    FullScoringSession,
    VehicleScoring,
    WeatherControl,
    ExtendedState,
    SystemEvent,
)

logger = logging.getLogger("simpulse.telemetry_bus")


# Channel -> TelemetryStateStore merge-handler name. This is the ONE place a raw
# packet is merged into the Store — PluginManager.dispatch_packet() (triggered by
# packet_received, emitted below AFTER this merge and the Engine update) no longer
# touches the Store itself, so each packet is merged exactly once.
_STORE_MERGE_METHODS: Dict[TelemetryChannel, str] = {
    TelemetryChannel.TELEMETRY: "update_telemetry",
    TelemetryChannel.OPPONENT_TELEMETRY: "update_opponent_telemetry",
    TelemetryChannel.COMPACT_SCORING: "update_compact_scoring",
    TelemetryChannel.FULL_SCORING: "update_full_scoring",
    TelemetryChannel.WEATHER: "update_weather",
    TelemetryChannel.EXTENDED_STATE: "update_extended_state",
    TelemetryChannel.SYSTEM_EVENTS: "update_system_events",
    TelemetryChannel.FORCE_FEEDBACK: "update_force_feedback",
    TelemetryChannel.GRAPHICS: "update_graphics",
    TelemetryChannel.TRACK_RULES: "update_track_rules",
    TelemetryChannel.PIT_MENU: "update_pit_menu",
}


class UdpStreamStatus(Enum):
    """Lifecycle state of the UDP telemetry ingestion pipeline."""
    STOPPED = "stopped"
    LISTENING = "listening"        # Socket open, waiting for game datagrams
    RECEIVING = "receiving"        # Live packets actively streaming
    SIMULATION = "simulation"      # Mock Feeder active


class TelemetryBus(QObject):
    """
    Central telemetry hub. Tracks bandwidth, frequencies, socket lifecycle, and dispatches packets.
    """

    telemetry_updated = Signal(object)      # VehicleSensors
    delta_updated = Signal(object)          # LapDeltaPacket
    packet_received = Signal(object)        # TelemetryRawPacket
    metrics_updated = Signal()              # Triggered periodically for UI refresh
    telemetry_fps_changed = Signal(float)
    stream_status_changed = Signal(object)  # UdpStreamStatus

    def __init__(
        self,
        reference_lap_mgr: Optional[ReferenceLapManager] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.reference_lap_mgr = reference_lap_mgr or ReferenceLapManager.get_instance()
        self.mock_generator = MockTelemetryGenerator(fps=60, parent=self)
        self.mock_generator.frame_ready.connect(self._on_mock_frame)

        self.udp_host: str = "0.0.0.0"
        self.udp_port: int = 5000
        self._udp_server: Optional[UDPServer] = None
        self._latest_sensors = VehicleSensors()
        self._latest_delta = LapDeltaPacket()
        self._last_status: UdpStreamStatus = UdpStreamStatus.STOPPED

        # Per-channel metrics tracking
        self.channel_metrics: Dict[TelemetryChannel, ChannelMetrics] = {
            ch: ChannelMetrics(channel=ch) for ch in TelemetryChannel
        }

        # Sliding window timestamps for accurate Hz / Kbps measurement (last 2 seconds)
        self._window_sec = 2.0
        self._channel_timestamps: Dict[TelemetryChannel, deque] = {
            ch: deque() for ch in TelemetryChannel
        }
        self._channel_bytes: Dict[TelemetryChannel, deque] = {
            ch: deque() for ch in TelemetryChannel
        }

        # Metrics calculation timer (2 Hz / 500ms)
        self._metrics_timer = QTimer(self)
        self._metrics_timer.setInterval(500)
        self._metrics_timer.timeout.connect(self._recalculate_metrics)
        self._metrics_timer.start()

    @property
    def latest_sensors(self) -> VehicleSensors:
        return self._latest_sensors

    @property
    def latest_delta(self) -> LapDeltaPacket:
        return self._latest_delta

    @property
    def total_measured_kbs(self) -> float:
        return sum(m.measured_kbs for m in self.channel_metrics.values())

    @property
    def total_measured_hz(self) -> float:
        return sum(m.measured_hz for m in self.channel_metrics.values())

    @property
    def active_channels_count(self) -> int:
        return sum(1 for m in self.channel_metrics.values() if m.is_active)

    @property
    def total_packets_count(self) -> int:
        return sum(m.packet_count for m in self.channel_metrics.values())

    @property
    def is_mock_running(self) -> bool:
        return self.mock_generator.is_running

    @property
    def is_udp_running(self) -> bool:
        return self._udp_server is not None and self._udp_server.client is not None and self._udp_server.client.is_running

    @property
    def stream_status(self) -> UdpStreamStatus:
        if self.mock_generator.is_running:
            return UdpStreamStatus.SIMULATION
        if self._udp_server is not None:
            if self.total_measured_hz > 0.5:
                return UdpStreamStatus.RECEIVING
            return UdpStreamStatus.LISTENING
        return UdpStreamStatus.STOPPED

    def start_mock(self) -> None:
        """Start simulated telemetry stream."""
        if self._udp_server:
            self.stop_udp_server()
        logger.info("Starting mock telemetry stream (60 FPS)...")
        self.mock_generator.start()
        self._check_status_change()

    def stop_mock(self) -> None:
        """Stop simulated telemetry."""
        logger.info("Stopping mock telemetry stream...")
        self.mock_generator.stop()
        self._check_status_change()

    def start_udp_server(self, host: str = "0.0.0.0", port: int = 5000, target_port: int = 5001) -> bool:
        """Start live UDP ingestion from the game plugin."""
        if self.mock_generator.is_running:
            self.stop_mock()

        self.udp_host = host
        self.udp_port = port
        try:
            self._udp_server = UDPServer(
                host=host,
                port=port,
                target_port=target_port,
                packet_listener=self._on_udp_packet_received
            )
            self._udp_server.start()
            logger.info(f"Started live UDP telemetry listener on {host}:{port} (Inbound: {target_port})")
            self._check_status_change()
            return True
        except Exception as e:
            logger.error(f"Failed to start live UDP server: {e}")
            self._udp_server = None
            self._check_status_change()
            return False

    def stop_udp_server(self) -> None:
        """Stop live UDP telemetry listener."""
        if self._udp_server:
            try:
                if self._udp_server._client:
                    self._udp_server._client.stop()
            except Exception as e:
                logger.warning(f"Error stopping UDP server: {e}")
            self._udp_server = None
            logger.info("Stopped live UDP telemetry listener.")
            self._check_status_change()

    def _on_udp_packet_received(
        self,
        channel_str_or_enum: Union[TelemetryChannel, str],
        packet_data: TelemetryPayload,
        raw_bytes_len: int,
    ) -> None:
        """Callback invoked by UDPServer whenever a decoded UDP packet arrives from the game."""
        if isinstance(channel_str_or_enum, TelemetryChannel):
            channel = channel_str_or_enum
        else:
            try:
                channel = TelemetryChannel(str(channel_str_or_enum))
            except ValueError:
                channel = TelemetryChannel.TELEMETRY

        self.process_raw_packet(channel, packet_data, raw_bytes_len)

    def process_raw_packet(
        self,
        channel: TelemetryChannel,
        data: TelemetryPayload,
        raw_bytes_len: int,
        override_sensors: Optional[VehicleSensors] = None,
    ) -> None:
        """Process an incoming raw UDP packet from the game."""
        now = time.time()
        metrics = self.channel_metrics[channel]
        metrics.update_measurement(raw_bytes_len, now)

        self._channel_timestamps[channel].append(now)
        self._channel_bytes[channel].append((now, raw_bytes_len))

        packet = TelemetryRawPacket(
            channel=channel,
            data=data,
            raw_bytes_len=raw_bytes_len,
            timestamp=now
        )

        store = TelemetryStateStore.get_instance()

        # 1. Merge the raw packet into the Store — the ONE place this happens (see
        # _STORE_MERGE_METHODS). Not a raw VehicleSensors/dict: those never reach
        # the Store (VehicleSensors is already-derived mock data; dict is the
        # defensive-only JSON-scoring path, see the isinstance(data, dict) branch
        # below).
        if data is not None and not isinstance(data, (VehicleSensors, dict)):
            merge_method_name = _STORE_MERGE_METHODS.get(channel)
            merge_method = getattr(store, merge_method_name, None) if merge_method_name else None
            if merge_method is not None:
                merge_method(data, now, raw_bytes_len)

        # 2. Engines consume the Store's consolidated View — never a hand-extracted
        # raw packet — so DeltaEngine sees the exact same fused state as everyone
        # else (this is what resolves CompactScoring/FullScoringSession disagreeing
        # on transient values: they're merged into one View by the Store first).
        delta_pkt: Optional[LapDeltaPacket] = None
        if data is not None:
            if isinstance(data, TelemInfo):
                delta_pkt = self.reference_lap_mgr.update_physics_from_view(store.snapshot())
            elif isinstance(data, (CompactScoring, FullScoringSession)):
                delta_pkt = self.reference_lap_mgr.update_scoring_from_view(store.timing, store.grid)
            elif isinstance(data, dict):
                # Defensive-only path: TelemetryPayload never carries a raw dict in
                # production (UDP packets always decode to typed isimotor_rawudp_client
                # objects), so this never reaches the Store via CHANNEL_ROUTING. Kept for
                # callers that still hand-build a JSON-shaped scoring dict directly.
                delta_pkt = self.reference_lap_mgr.update_scoring(data)

        # 3. NOW notify observers (PluginManager.dispatch_packet, via this Qt
        # signal's direct connection) — the Store (raw + derived) AND the Engine's
        # delta output are both fully up to date for this exact packet by this
        # point, so store.snapshot() built downstream carries the current tick's
        # delta, not the previous one.
        self.packet_received.emit(packet)

        # 4. Build VehicleSensors for the UI/overlay from the same consolidated View.
        if data is not None:
            if override_sensors is not None:
                sensors = override_sensors
                delta_pkt = self._apply_delta_fields(sensors, delta_pkt)
                self._apply_presence_fields(sensors)
                self.process_frame(sensors, delta_pkt)
            elif isinstance(data, VehicleSensors):
                self.process_frame(data, delta_pkt)
            else:
                sensors = VehicleSensors.from_view(store.snapshot())
                delta_pkt = self._apply_delta_fields(sensors, delta_pkt)
                self._apply_presence_fields(sensors)
                self.process_frame(sensors, delta_pkt)

    def _apply_delta_fields(self, sensors: VehicleSensors, delta_pkt: Optional[LapDeltaPacket]) -> LapDeltaPacket:
        """Stamps sensors' delta/timing/sector fields from the single authoritative
        LapDeltaPacket (ReferenceLapManager/DeltaEngine) — falling back to the most
        recently emitted one when this particular raw packet didn't trigger a fresh
        recompute (e.g. Weather/ExtendedState/SystemEvent, which never touch the
        engine). This is the ONLY place VehicleSensors gets these fields; neither
        the Store's TelemetryView nor VehicleSensors.from_view() compute or carry
        them.
        """
        effective = delta_pkt if delta_pkt is not None else self.reference_lap_mgr.latest_packet
        sensors.delta_time = effective.display_delta
        sensors.sector1_delta = effective.sector1_delta
        sensors.sector2_delta = effective.sector2_delta
        sensors.sector3_delta = effective.sector3_delta
        sensors.sector1_time = effective.sector1_time
        sensors.sector1_status = effective.sector1_status
        sensors.sector2_time = effective.sector2_time
        sensors.sector2_status = effective.sector2_status
        sensors.sector3_time = effective.sector3_time
        sensors.sector3_status = effective.sector3_status
        sensors.last_lap_time = effective.last_lap_time
        sensors.last_lap_time_str = effective.last_lap_time_str
        sensors.last_lap_status = effective.last_lap_status
        sensors.is_lap_freeze_active = effective.is_lap_freeze_active
        sensors.has_delta_reference = effective.has_reference
        sensors.estimated_lap_time = effective.estimated_lap_time
        sensors.estimated_lap_time_str = effective.estimated_lap_time_str
        sensors.expected_status = getattr(effective, 'expected_status', 'white') or 'white'
        sensors.is_pit_lap = effective.is_pit_lap
        sensors.lap_flag = effective.lap_flag
        sensors.current_sector = effective.current_sector
        return effective

    def _apply_presence_fields(self, sensors: VehicleSensors) -> None:
        """Stamps sensors.in_realtime from the single authoritative
        TelemetryStateStore (backed by PresenceTracker) — same centralization
        pattern as _apply_delta_fields, but sourced from the Store, not
        ReferenceLapManager/DeltaEngine. Defensive: VehicleSensors.from_view()'s
        own in_realtime is already correct, but this is the only place that also
        covers the override_sensors path (mock mode).
        """
        sensors.in_realtime = TelemetryStateStore.get_instance().in_realtime

    def process_frame(self, sensors: VehicleSensors, delta_packet: Optional[LapDeltaPacket] = None) -> None:
        """Handle incoming high-level telemetry frame and broadcast to observers."""
        self._latest_sensors = sensors
        if delta_packet is None:
            delta_packet = self.reference_lap_mgr.latest_packet
        self._latest_delta = delta_packet

        # Emit signals for host UI, overlay, and plugin observers
        self.telemetry_updated.emit(sensors)
        self.delta_updated.emit(delta_packet)

    def _on_mock_frame(self, sensors: VehicleSensors) -> None:
        """Simulate real UDP packet arrival across multiple channels in mock mode."""
        now = time.time()
        telem_info = sensors.to_telem_info()

        # Telemetry packet (~640 bytes)
        self.process_raw_packet(TelemetryChannel.TELEMETRY, telem_info, 640, override_sensors=sensors)

        # Compact Scoring packet (every 100ms / 10 Hz, ~180 bytes)
        if int(now * 10) % 2 == 0:
            mock_compact = CompactScoring(
                in_realtime=sensors.in_realtime,
                count_lap_flag=sensors.lap_flag,
                sector=sensors.current_sector,
            )
            self.process_raw_packet(TelemetryChannel.COMPACT_SCORING, mock_compact, 184)

        # Full Scoring packet (every 200ms / 5 Hz, ~2400 bytes)
        if int(now * 5) % 3 == 0:
            mock_full = FullScoringSession(
                vehicles=[
                    VehicleScoring(
                        is_player=True,
                        in_garage_stall=False,
                        count_lap_flag=sensors.lap_flag,
                        sector=sensors.current_sector,
                        local_vel=telem_info.local_vel,
                        lap_dist=telem_info.elapsed_time * sensors.vehicle_speed,
                    )
                ]
            )
            self.process_raw_packet(TelemetryChannel.FULL_SCORING, mock_full, 2480)

        # Weather packet (every 1s / 1 Hz, ~96 bytes)
        if int(now) % 1 == 0 and len(self._channel_timestamps[TelemetryChannel.WEATHER]) == 0:
            mock_weather = WeatherControl(ambient_temp_k=295.15)
            self.process_raw_packet(TelemetryChannel.WEATHER, mock_weather, 96)

        # Extended State packet (every 200ms / 5 Hz, ~120 bytes)
        if int(now * 5) % 2 == 0:
            mock_extended = ExtendedState()
            self.process_raw_packet(TelemetryChannel.EXTENDED_STATE, mock_extended, 128)

    def _recalculate_metrics(self) -> None:
        """Update sliding-window Hz and Kb/s throughput for each channel."""
        now = time.time()
        cutoff = now - self._window_sec

        for ch in TelemetryChannel:
            ts_queue = self._channel_timestamps[ch]
            bytes_queue = self._channel_bytes[ch]

            # Prune old samples
            while ts_queue and ts_queue[0] < cutoff:
                ts_queue.popleft()
            while bytes_queue and bytes_queue[0][0] < cutoff:
                bytes_queue.popleft()

            count = len(ts_queue)
            total_b = sum(b for _, b in bytes_queue)

            metrics = self.channel_metrics[ch]
            metrics.measured_hz = count / self._window_sec
            metrics.measured_kbs = (total_b * 8.0) / (self._window_sec * 1000.0)
            metrics.is_active = (now - metrics.last_packet_timestamp) < 2.5 if metrics.last_packet_timestamp > 0 else False

        self.telemetry_fps_changed.emit(self.channel_metrics[TelemetryChannel.TELEMETRY].measured_hz)
        self.metrics_updated.emit()
        self._check_status_change()

    def _check_status_change(self) -> None:
        current = self.stream_status
        if current != self._last_status:
            self._last_status = current
            self.stream_status_changed.emit(current)

    def stop(self) -> None:
        """Stop all background generators, timers, and UDP listeners."""
        self._metrics_timer.stop()
        self.stop_mock()
        self.stop_udp_server()
