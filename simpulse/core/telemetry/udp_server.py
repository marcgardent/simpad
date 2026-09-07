import socket
import threading
import time
import logging
from typing import Optional, Tuple, Callable, Union, Dict

from isimotor_rawudp_client import (
    IsiMotorClient,
    TelemInfo,
    CompactScoring,
    FullScoringSession,
    SystemEvent,
    ExtendedState,
    ForceFeedback,
    Graphics,
    WeatherControl,
    HWControlCommand,
    WeatherControlCommand,
)

from simpulse.core.telemetry_channels import TelemetryPayload

logger = logging.getLogger(__name__)


class UDPServer:
    """
    Thread-safe UDP telemetry server for Le Mans Ultimate Telemetry Plugin & isiMotor-RawUDP.
    Pure I/O: owns the socket/IsiMotorClient lifecycle and relays each decoded raw
    packet to `packet_listener` (TelemetryBus._on_udp_packet_received in production).
    Does not decode into any higher-level model itself, and keeps no "latest data"
    cache of its own — TelemetryStateStore (via TelemetryBus) is the single owner
    of that state; a second copy here previously drifted out of sync with it (see
    git history for the removed _latest_data/_handle_* merge code).
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5000,
        target_port: int = 5001,
        packet_listener: Optional[Callable[[str, Optional[TelemetryPayload], int], None]] = None,
    ):
        self.host = host
        self.port = port
        self.target_port = target_port
        self.packet_listener = packet_listener
        self._client: Optional[IsiMotorClient] = None
        self._lock = threading.Lock()
        self._last_packet_time: float = 0.0
        self._packet_count: int = 0

    def start(self) -> None:
        """Starts the UDP server and IsiMotorClient in a dedicated thread."""
        if self._client and self._client.is_running:
            return

        self._client = IsiMotorClient(
            host=self.host,
            port=self.port,
            inbound_host="127.0.0.1",
            inbound_port=self.target_port,
        )
        # Starts ingestion with unified binary + JSON hook. Decoded packets reach
        # consumers exclusively through packet_listener (set on __init__) via
        # _on_datagram_received below — no per-channel callback wiring needed here.
        self._client._receiver.start(self._on_datagram_received)
        logger.info(f"UDP server started on port {self.port} with IsiMotorClient")
        print(f"[UDP] Listening on UDP {self.host}:{self.port} via isimotor_rawudp_client (120 Hz+ ultra-low latency)", flush=True)

    def stop(self) -> None:
        """Stops UDP client and detaches listeners."""
        self.packet_listener = None
        if self._client:
            try:
                self._client.stop()
            except Exception as e:
                logger.warning(f"Error stopping IsiMotorClient: {e}")
            self._client = None

    def _on_datagram_received(self, data: bytes, timestamp: float) -> None:
        """
        Ingestion hook for binary SIMP UDP packets via isimotor_rawudp_client.
        """
        raw_len = len(data)
        with self._lock:
            self._last_packet_time = timestamp
            self._packet_count += 1

        if not self._client or len(data) < 24 or not data.startswith(b"SIMP") or data[4] != 1:
            return

        # Packets with standard SIMP v1 header (24 bytes)
        pkt_type = data[5]
        pkt_type_map = {
            1: "Telemetry",
            2: "CompactScoring",
            3: "SystemEvents",
            4: "FullScoring",
            7: "Weather",
            8: "ExtendedState",
            9: "ForceFeedback",
            10: "Graphics",
        }
        channel_name = pkt_type_map.get(pkt_type, "Telemetry")

        packet = self._client._decode_or_reassemble(data, timestamp)
        if packet is not None:
            self._client._state.update(packet, timestamp)
            self._client._dispatcher.dispatch(packet)

            if self.packet_listener is not None:
                try:
                    self.packet_listener(channel_name, packet, raw_len)
                except Exception as e:
                    logger.error(f"Error in packet_listener: {e}")
        elif self.packet_listener is not None:
            # Chunk of a multi-part packet (e.g. FullScoring)
            try:
                self.packet_listener(channel_name, None, raw_len)
            except Exception as e:
                logger.error(f"Error in packet_listener chunk: {e}")

    @property
    def client(self) -> Optional[IsiMotorClient]:
        """Direct access to underlying IsiMotorClient instance."""
        return self._client

    # ── Outbound Control API ──────────────────────────────────────────────────

    def send_hw_control(
        self,
        command: Union[HWControlCommand, str],
        control_value: float = 1.0,
        duration_ms: int = 50,
    ) -> None:
        """Sends a hardware control command (HWControlCommand or str) to the simulator."""
        if not self._client:
            return
        if isinstance(command, HWControlCommand):
            self._client.send_hw_control(
                control_name=command.control_name,
                control_value=command.control_value,
                duration_ms=command.duration_ms,
            )
        elif isinstance(command, str):
            self._client.send_hw_control(
                control_name=command,
                control_value=control_value,
                duration_ms=duration_ms,
            )

    def send_weather_override(
        self,
        command: Optional[Union[WeatherControlCommand, Dict[str, Union[float, int, bool]]]] = None,
        **kwargs: Union[float, int, bool],
    ) -> None:
        """Sends a weather override command (WeatherControlCommand or kwargs) to the simulator."""
        if not self._client:
            return
        if isinstance(command, WeatherControlCommand):
            self._client.send_weather_override(
                ambient_temp=command.ambient_temp,
                track_temp=command.track_temp,
                dark_cloud=command.dark_cloud,
                raining=command.raining,
                wind_speed=command.wind_speed,
                wind_direction=command.wind_direction,
                min_path_wetness=command.min_path_wetness,
                max_path_wetness=command.max_path_wetness,
            )
        elif isinstance(command, dict):
            self._client.send_weather_override(**command)
        elif kwargs:
            self._client.send_weather_override(**kwargs)

    def send_unfreeze_physics(self) -> None:
        """Sends physics unfreeze command."""
        self.send_hw_control("UnfreezePhysics", control_value=1.0)

    def send_pit_lane_speed_limit(self, enabled: bool = True) -> None:
        """Enables or disables the pit lane speed limiter."""
        self.send_hw_control("PitLimiter", control_value=1.0 if enabled else 0.0)

    def send_tc_override(self, level: int) -> None:
        """Sends Traction Control override command."""
        self.send_hw_control("TCLevel", control_value=float(level))

    def send_abs_override(self, level: int) -> None:
        """Sends ABS override command."""
        self.send_hw_control("ABSLevel", control_value=float(level))

    # ── Diagnostics & Lifecycle ───────────────────────────────────────────────

    def is_receiving_packets(self, timeout: float = 1.0) -> Tuple[bool, float, int]:
        """
        Checks active presence of UDP packets.
        Returns (is_active, timestamp_last_packet, total_packet_count).
        """
        with self._lock:
            is_active = (time.time() - self._last_packet_time) < timeout if self._last_packet_time > 0 else False
            return is_active, self._last_packet_time, self._packet_count

    def is_receiving(self, timeout: float = 1.0) -> bool:
        """Returns True if UDP packets were received recently."""
        return self.is_receiving_packets(timeout)[0]

    @property
    def is_running(self) -> bool:
        """Indicates whether UDP server is actively listening."""
        return bool(self._client and self._client.is_running)



