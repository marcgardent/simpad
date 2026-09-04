import socket
import threading
import time
import logging
from typing import Optional, Tuple, Any

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

from .lmu_parser import LMUParser, TelemetryData

logger = logging.getLogger(__name__)


class UDPServer:
    """
    Thread-safe UDP telemetry server for Le Mans Ultimate Telemetry Plugin & isiMotor-RawUDP.
    Encapsulates standard IsiMotorClient for high-frequency binary decoding (SIMP)
    while preserving full backwards compatibility with JSON streams and the SimPad API.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5000,
        target_port: int = 5001,
        packet_listener: Optional[Any] = None,
    ):
        self.host = host
        self.port = port
        self.target_port = target_port
        self.packet_listener = packet_listener
        self._client: Optional[IsiMotorClient] = None
        self._lock = threading.Lock()
        self._latest_data: Optional[TelemetryData] = None
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
        self._setup_callbacks()
        # Starts ingestion with unified binary + JSON hook
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

    def _setup_callbacks(self) -> None:
        """Configures isiMotor client event callbacks."""
        if not self._client:
            return

        def _handle_telem(telem: TelemInfo):
            snap = LMUParser.process_telemetry(telem)
            if snap is not None:
                with self._lock:
                    self._latest_data = snap

        def _handle_compact_scoring(scoring: CompactScoring):
            snap = LMUParser.process_compact_scoring(scoring)
            with self._lock:
                if self._latest_data is not None:
                    # Updates only timing and scoring fields on active physics snapshot
                    # without ever overwriting pedal inputs, engine RPM, gear, or speed
                    self._latest_data.raw_scoring = scoring
                    self._latest_data.delta_time = snap.delta_time
                    self._latest_data.estimated_lap_time = snap.estimated_lap_time
                    self._latest_data.estimated_lap_time_str = snap.estimated_lap_time_str
                    self._latest_data.sector1_time = snap.sector1_time
                    self._latest_data.sector1_status = snap.sector1_status
                    self._latest_data.sector2_time = snap.sector2_time
                    self._latest_data.sector2_status = snap.sector2_status
                    self._latest_data.sector3_time = snap.sector3_time
                    self._latest_data.sector3_status = snap.sector3_status
                    self._latest_data.sector1_delta = snap.sector1_delta
                    self._latest_data.sector2_delta = snap.sector2_delta
                    self._latest_data.sector3_delta = snap.sector3_delta
                    self._latest_data.current_sector = snap.current_sector
                    self._latest_data.total_laps = snap.total_laps
                    self._latest_data.laps_completed = snap.laps_completed
                    self._latest_data.lap_flag = snap.lap_flag
                    self._latest_data.track_cut_state = snap.track_cut_state
                else:
                    self._latest_data = snap

        def _handle_full_scoring(session: FullScoringSession):
            snap = LMUParser.process_full_scoring(session)
            with self._lock:
                if self._latest_data is not None:
                    # Updates only multi-car session and timing fields without disturbing physics
                    self._latest_data.raw_scoring = session
                    self._latest_data.delta_time = snap.delta_time
                    self._latest_data.estimated_lap_time = snap.estimated_lap_time
                    self._latest_data.estimated_lap_time_str = snap.estimated_lap_time_str
                    self._latest_data.sector1_time = snap.sector1_time
                    self._latest_data.sector1_status = snap.sector1_status
                    self._latest_data.sector2_time = snap.sector2_time
                    self._latest_data.sector2_status = snap.sector2_status
                    self._latest_data.sector3_time = snap.sector3_time
                    self._latest_data.sector3_status = snap.sector3_status
                    self._latest_data.sector1_delta = snap.sector1_delta
                    self._latest_data.sector2_delta = snap.sector2_delta
                    self._latest_data.sector3_delta = snap.sector3_delta
                    self._latest_data.current_sector = snap.current_sector
                    self._latest_data.total_laps = snap.total_laps
                    self._latest_data.laps_completed = snap.laps_completed
                    self._latest_data.lap_flag = snap.lap_flag
                    self._latest_data.track_cut_state = snap.track_cut_state
                else:
                    self._latest_data = snap

        def _handle_system_event(event: SystemEvent):
            snap = LMUParser.process_system_event(event)
            with self._lock:
                if self._latest_data is not None:
                    self._latest_data.in_realtime = snap.in_realtime
                else:
                    self._latest_data = snap

        def _handle_packet(pkt: Any):
            # Internal handling of packet (FFB, Weather, Graphics, ExtendedState) without polluting physics stream
            LMUParser.process_packet(pkt)

        self._client.on_telemetry = _handle_telem
        self._client.on_scoring = _handle_compact_scoring
        self._client.on_full_scoring = _handle_full_scoring
        self._client.on_system_event = _handle_system_event
        self._client.on_weather = _handle_packet
        self._client.on_extended_state = _handle_packet
        self._client.on_force_feedback = _handle_packet
        self._client.on_graphics = _handle_packet

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

    def get_latest_data(self, timeout: float = 1.2) -> Optional[TelemetryData]:
        """
        Retrieves latest received data in a thread-safe manner with Zero-Order Hold.
        Absorbs micro-drops in UDP stream (< 1.2s) without propagating null/reset state.
        """
        with self._lock:
            if self._latest_data is not None:
                if timeout <= 0 or (time.time() - self._last_packet_time) <= timeout:
                    return self._latest_data
            return None

    def get_latest_telemetry(self) -> Optional[Any]:
        """Returns latest TelemInfo packet received."""
        if self._client:
            return self._client.get_latest_telemetry() or LMUParser.get_latest_telemetry_info()
        return LMUParser.get_latest_telemetry_info()

    def get_latest_scoring(self) -> Optional[Any]:
        """Returns latest CompactScoring packet received."""
        if self._client:
            return self._client.get_latest_scoring() or LMUParser.get_latest_compact_scoring()
        return LMUParser.get_latest_compact_scoring()

    def get_latest_full_scoring(self) -> Optional[Any]:
        """Returns latest FullScoringSession packet received."""
        if self._client:
            return self._client.get_latest_full_scoring() or LMUParser.get_latest_full_scoring()
        return LMUParser.get_latest_full_scoring()

    @property
    def client(self) -> Optional[IsiMotorClient]:
        """Direct access to underlying IsiMotorClient instance."""
        return self._client

    # ── Outbound Control API ──────────────────────────────────────────────────

    def send_hw_control(self, command: Any, control_value: float = 1.0, duration_ms: int = 50) -> None:
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

    def send_weather_override(self, command: Any = None, **kwargs) -> None:
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

    def stop(self) -> None:
        """Stops UDP server and releases IsiMotorClient."""
        if self._client:
            self._client.stop()
            self._client = None
        logger.info("UDP Server stopped.")

    @property
    def is_running(self) -> bool:
        """Indicates whether UDP server is actively listening."""
        return bool(self._client and self._client.is_running)



