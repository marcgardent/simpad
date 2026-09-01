import socket
import threading
import time
import logging
from typing import Optional, Tuple, Any

try:
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
except ImportError:
    IsiMotorClient = Any  # type: ignore
    TelemInfo = Any  # type: ignore
    CompactScoring = Any  # type: ignore
    FullScoringSession = Any  # type: ignore
    SystemEvent = Any  # type: ignore
    ExtendedState = Any  # type: ignore
    ForceFeedback = Any  # type: ignore
    Graphics = Any  # type: ignore
    WeatherControl = Any  # type: ignore
    HWControlCommand = Any  # type: ignore
    WeatherControlCommand = Any  # type: ignore

from src.telemetry.lmu_parser import LMUParser, TelemetryData

logger = logging.getLogger(__name__)


class UDPServer:
    """
    Serveur de télémétrie UDP thread-safe pour Le Mans Ultimate Telemetry Plugin & isiMotor-RawUDP.
    Encapsule le client standard IsiMotorClient pour le décodage binaire haute fréquence (SIMP)
    tout en préservant la rétrocompatibilité complète avec les trames JSON et l'API SimPad.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 5000, target_port: int = 5001):
        self.host = host
        self.port = port
        self.target_port = target_port
        self._client: Optional[IsiMotorClient] = None
        self._lock = threading.Lock()
        self._latest_data: Optional[TelemetryData] = None
        self._last_packet_time: float = 0.0
        self._packet_count: int = 0

    def start(self) -> None:
        """Démarre le serveur UDP et le client IsiMotorClient dans un thread dédié."""
        if self._client and self._client.is_running:
            return

        self._client = IsiMotorClient(
            host=self.host,
            port=self.port,
            inbound_host="127.0.0.1",
            inbound_port=self.target_port,
        )
        self._setup_callbacks()
        # Démarre l'ingestion avec le hook unifié binaire + JSON
        self._client._receiver.start(self._on_datagram_received)
        logger.info(f"Serveur UDP démarré sur port {self.port} avec IsiMotorClient")
        print(f"[UDP] Listening on UDP {self.host}:{self.port} via isimotor_rawudp_client (120 Hz+ ultra-low latency)", flush=True)

    def _setup_callbacks(self) -> None:
        """Configure les callbacks d'événements du client isiMotor."""
        if not self._client:
            return

        def _handle_telem(telem: TelemInfo):
            snap = LMUParser.process_telemetry(telem)
            with self._lock:
                self._latest_data = snap

        def _handle_compact_scoring(scoring: CompactScoring):
            snap = LMUParser.process_compact_scoring(scoring)
            with self._lock:
                self._latest_data = snap

        def _handle_full_scoring(session: FullScoringSession):
            snap = LMUParser.process_full_scoring(session)
            with self._lock:
                self._latest_data = snap

        def _handle_system_event(event: SystemEvent):
            snap = LMUParser.process_system_event(event)
            with self._lock:
                self._latest_data = snap

        def _handle_packet(pkt: Any):
            snap = LMUParser.process_packet(pkt)
            if snap:
                with self._lock:
                    self._latest_data = snap

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
        Hook d'ingestion des paquets UDP binaires SIMP via le client isimotor_rawudp_client.
        """
        with self._lock:
            self._last_packet_time = timestamp
            self._packet_count += 1

        if self._client:
            packet = self._client._decode_or_reassemble(data, timestamp)
            if packet is not None:
                self._client._state.update(packet, timestamp)
                self._client._dispatcher.dispatch(packet)

    def get_latest_data(self, timeout: float = 1.0) -> Optional[TelemetryData]:
        """Récupère les dernières données reçues de manière thread-safe."""
        with self._lock:
            return self._latest_data

    def get_latest_telemetry(self) -> Optional[Any]:
        """Retourne la dernière trame TelemInfo reçue."""
        if self._client:
            return self._client.get_latest_telemetry() or LMUParser.get_latest_telemetry_info()
        return LMUParser.get_latest_telemetry_info()

    def get_latest_scoring(self) -> Optional[Any]:
        """Retourne la dernière trame CompactScoring reçue."""
        if self._client:
            return self._client.get_latest_scoring() or LMUParser.get_latest_compact_scoring()
        return LMUParser.get_latest_compact_scoring()

    def get_latest_full_scoring(self) -> Optional[Any]:
        """Retourne la dernière session FullScoringSession reçue."""
        if self._client:
            return self._client.get_latest_full_scoring() or LMUParser.get_latest_full_scoring()
        return LMUParser.get_latest_full_scoring()

    @property
    def client(self) -> Optional[IsiMotorClient]:
        """Accès direct à l'instance IsiMotorClient sous-jacente."""
        return self._client

    # ── Outbound Control API ──────────────────────────────────────────────────

    def send_hw_control(self, command: Any, control_value: float = 1.0, duration_ms: int = 50) -> None:
        """Transmet une commande de contrôle matériel (HWControlCommand ou str) au simulateur."""
        if not self._client:
            return
        if hasattr(command, "control_name"):
            self._client.send_hw_control(
                control_name=command.control_name,
                control_value=getattr(command, "control_value", 1.0),
                duration_ms=getattr(command, "duration_ms", 50),
            )
        elif isinstance(command, str):
            self._client.send_hw_control(
                control_name=command,
                control_value=control_value,
                duration_ms=duration_ms,
            )

    def send_weather_override(self, command: Any = None, **kwargs) -> None:
        """Transmet une commande météo (WeatherControlCommand ou kwargs) au simulateur."""
        if not self._client:
            return
        if hasattr(command, "ambient_temp"):
            self._client.send_weather_override(
                ambient_temp=getattr(command, "ambient_temp", 20.0),
                track_temp=getattr(command, "track_temp", 25.0),
                dark_cloud=getattr(command, "dark_cloud", 0.0),
                raining=getattr(command, "raining", 0.0),
                wind_speed=getattr(command, "wind_speed", 0.0),
                wind_direction=getattr(command, "wind_direction", 0.0),
                min_path_wetness=getattr(command, "min_path_wetness", 0.0),
                max_path_wetness=getattr(command, "max_path_wetness", 0.0),
            )
        elif isinstance(command, dict):
            self._client.send_weather_override(**command)
        elif kwargs:
            self._client.send_weather_override(**kwargs)

    def send_unfreeze_physics(self) -> None:
        """Envoie la commande de dégel de la physique."""
        self.send_hw_control("UnfreezePhysics", control_value=1.0)

    def send_pit_lane_speed_limit(self, enabled: bool = True) -> None:
        """Active ou désactive le limiteur de vitesse des stands."""
        self.send_hw_control("PitLimiter", control_value=1.0 if enabled else 0.0)

    def send_tc_override(self, level: int) -> None:
        """Envoie une consigne de Traction Control."""
        self.send_hw_control("TCLevel", control_value=float(level))

    def send_abs_override(self, level: int) -> None:
        """Envoie une consigne d'ABS."""
        self.send_hw_control("ABSLevel", control_value=float(level))

    # ── Diagnostics & Lifecycle ───────────────────────────────────────────────

    def is_receiving_packets(self, timeout: float = 1.0) -> Tuple[bool, float, int]:
        """
        Vérifie la présence active de paquets UDP.
        Retourne (is_active, timestamp_dernier_paquet, nb_total_paquets).
        """
        with self._lock:
            is_active = (time.time() - self._last_packet_time) < timeout if self._last_packet_time > 0 else False
            return is_active, self._last_packet_time, self._packet_count

    def is_receiving(self, timeout: float = 1.0) -> bool:
        """Retourne True si des paquets UDP ont été reçus récemment."""
        return self.is_receiving_packets(timeout)[0]

    def stop(self) -> None:
        """Arrête le serveur UDP et libère le client IsiMotorClient."""
        if self._client:
            self._client.stop()
            self._client = None
        logger.info("Serveur UDP arrêté.")

    @property
    def is_running(self) -> bool:
        """Indique si le serveur UDP écoute actuellement."""
        return bool(self._client and self._client.is_running)



