"""
SimPad Qt6 Telemetry Bus & Ingestion Pipeline.
Tracks real-time bandwidth (Kb/s), measured frequencies (Hz), per-channel statistics,
and connects live UDP socket datagrams directly to plugins and telemetry domain models.
"""

from __future__ import annotations
import time
import logging
from collections import deque
from enum import Enum
from typing import Optional, Dict, Any, TYPE_CHECKING
from PySide6.QtCore import QObject, Signal, QTimer

if TYPE_CHECKING:
    from simpad_qt.plugins.manager import PluginManager

from src.telemetry.sensors import VehicleSensors
from simpad_qt.core.telemetry_channels import (
    TelemetryChannel, ChannelMetrics, TelemetryRawPacket
)
from simpad_qt.core.mock_telemetry import MockTelemetryGenerator
from src.telemetry.udp_server import UDPServer
from src.telemetry.lmu_parser import LMUParser

logger = logging.getLogger("simpad.telemetry_bus")


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
    packet_received = Signal(object)        # TelemetryRawPacket
    metrics_updated = Signal()              # Triggered periodically for UI refresh
    telemetry_fps_changed = Signal(float)
    stream_status_changed = Signal(object)  # UdpStreamStatus

    def __init__(self, plugin_manager: PluginManager, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.plugin_manager = plugin_manager
        self.mock_generator = MockTelemetryGenerator(fps=60, parent=self)
        self.mock_generator.frame_ready.connect(self._on_mock_frame)

        self.udp_host: str = "0.0.0.0"
        self.udp_port: int = 5000
        self._udp_server: Optional[UDPServer] = None
        self._latest_sensors = VehicleSensors()
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

        # Metrics calculation timer (10 Hz)
        self._metrics_timer = QTimer(self)
        self._metrics_timer.setInterval(100)
        self._metrics_timer.timeout.connect(self._recalculate_metrics)
        self._metrics_timer.start()

    @property
    def latest_sensors(self) -> VehicleSensors:
        return self._latest_sensors

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

    def _on_udp_packet_received(self, channel_str_or_enum: Any, packet_data: Any, raw_bytes_len: int) -> None:
        """Callback invoked by UDPServer whenever a decoded UDP packet arrives from the game."""
        if isinstance(channel_str_or_enum, TelemetryChannel):
            channel = channel_str_or_enum
        else:
            try:
                channel = TelemetryChannel(str(channel_str_or_enum))
            except ValueError:
                channel = TelemetryChannel.TELEMETRY

        self.process_raw_packet(channel, packet_data, raw_bytes_len)

    def process_raw_packet(self, channel: TelemetryChannel, data: Any, raw_bytes_len: int) -> None:
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

        # 1. Dispatch raw packet to IPacketSubscriber plugins (e.g. TelemetryDiagnosticsPlugin)
        self.plugin_manager.dispatch_packet(packet)
        self.packet_received.emit(packet)

        # 2. Process high-level telemetry domain representations
        if data is not None:
            if isinstance(data, VehicleSensors):
                self.process_frame(data)
            else:
                snap = LMUParser.process_packet(data)
                if snap is not None:
                    self.process_frame(snap.to_sensors())

    def process_frame(self, sensors: VehicleSensors) -> None:
        """Handle incoming high-level telemetry frame and broadcast to plugins and UI."""
        self._latest_sensors = sensors

        # 1. Dispatch safely to all ITelemetrySubscriber plugins
        self.plugin_manager.dispatch_telemetry(sensors)

        # 2. Emit signal for host UI observers
        self.telemetry_updated.emit(sensors)

    def _on_mock_frame(self, sensors: VehicleSensors) -> None:
        """Simulate real UDP packet arrival across multiple channels in mock mode."""
        now = time.time()

        # Telemetry packet (~640 bytes)
        self.process_raw_packet(TelemetryChannel.TELEMETRY, sensors, 640)

        # Compact Scoring packet (every 100ms / 10 Hz, ~180 bytes)
        if int(now * 10) % 2 == 0:
            self.process_raw_packet(TelemetryChannel.COMPACT_SCORING, sensors, 184)

        # Full Scoring packet (every 200ms / 5 Hz, ~2400 bytes)
        if int(now * 5) % 3 == 0:
            self.process_raw_packet(TelemetryChannel.FULL_SCORING, sensors, 2480)

        # Weather packet (every 1s / 1 Hz, ~96 bytes)
        if int(now) % 1 == 0 and len(self._channel_timestamps[TelemetryChannel.WEATHER]) == 0:
            self.process_raw_packet(TelemetryChannel.WEATHER, sensors, 96)

        # Extended State packet (every 200ms / 5 Hz, ~120 bytes)
        if int(now * 5) % 2 == 0:
            self.process_raw_packet(TelemetryChannel.EXTENDED_STATE, sensors, 128)

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
