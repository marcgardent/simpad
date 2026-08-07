import socket
import threading
import time
import logging
from typing import Optional, Tuple
from src.telemetry.lmu_parser import LMUParser, TelemetryData

logger = logging.getLogger(__name__)


class UDPServer:
    """
    Serveur de télémétrie UDP thread-safe pour Le Mans Ultimate Telemetry Plugin.
    Écoute les paquets JSON envoyés par le plugin LMU sur le port UDP 5000.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 5000):
        # TODO [DRY]: Fix host assignment using parameter instead of hardcoding "0.0.0.0"
        self.host = host
        self.port = port
        self._socket: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        self._latest_data: Optional[TelemetryData] = None
        self._last_packet_time: float = 0.0
        self._packet_count: int = 0

    def start(self) -> None:
        """Démarre le serveur UDP dans un thread dédié."""
        if self._running:
            return

        self._running = True
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.settimeout(0.05)  # 50ms non-blocking
            self._socket.bind((self.host, self.port))
            logger.info(f"Serveur UDP démarré sur port {self.port}")
            print(f"[UDP] Listening on UDP {self.host}:{self.port}", flush=True)
        except Exception as e:
            logger.warning(f"Could not bind UDP port {self.port}: {e}")
            print(f"[UDP WARNING] Could not bind port {self.port}: {e}", flush=True)

        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def _process_packet(self, data: bytes, now: float) -> None:
        """
        SLAP Helper: Traitement synchrone des paquets réseau séparé du contrôle de boucle UDP.
        """
        # TODO [SRP]: Socket server delegates telemetry parsing to LMUParser
        with self._lock:
            self._last_packet_time = now
            self._packet_count += 1

        parsed = LMUParser.parse(data)
        if parsed:
            with self._lock:
                self._latest_data = parsed

    def _listen_loop(self) -> None:
        """Boucle de réception UDP thread-safe régulée à ~50 Hz (20 ms)."""
        # TODO [SLAP]: High-level socket listening loop delegates packet processing to _process_packet
        # TODO [KISS]: Simplify pacing sleep calculation
        while self._running:
            start_tick = time.time()

            if self._socket:
                try:
                    data, addr = self._socket.recvfrom(65535)
                    now = time.time()
                    self._process_packet(data, now)
                except socket.timeout:
                    pass
                except Exception as e:
                    if self._running:
                        logger.error(f"Erreur UDP: {e}")

            elapsed = time.time() - start_tick
            sleep_time = max(0.005, 0.02 - elapsed)
            time.sleep(sleep_time)

    def get_latest_data(self, timeout: float = 1.0) -> Optional[TelemetryData]:
        """Récupère les dernières données reçues de manière thread-safe. Retourne None si la connexion est interrompue (timeout)."""
        with self._lock:
            if self._last_packet_time > 0 and (time.time() - self._last_packet_time) > timeout:
                return TelemetryData(in_realtime=False)
            return self._latest_data

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
        """Arrête le serveur UDP."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        logger.info("Serveur UDP arrêté.")

    @property
    def is_running(self) -> bool:
        return self._running
