import os
import sys
import time
import logging
from pathlib import Path

# Ajouter le chemin racine du projet pour les imports autonomes
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.core.config import load_config
from src.telemetry.udp_server import UDPServer
from src.physics.effects import PhysicsToHaptic
from src.haptics.windows import WindowsHapticController

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("LMUHapticCore")


# TODO: [SLAP] Main function should orchestrate high-level component lifecycles, delegating loop iteration and frequency sleeping to dedicated helpers.
# TODO: [SRP] Application lifecycle management should be separated from runtime telemetry processing loop execution.
def main():
    logger.info("Démarrage du Middleware Haptique LMU (Windows Native)")
    config = load_config()

    controller = WindowsHapticController(invert_sides=config.get("invert_sides", False))
    processor = PhysicsToHaptic(config)
    udp_server = UDPServer(host=config.get("udp_host", "127.0.0.1"), port=config.get("udp_port", 5606))
    udp_server.start()

    rate_hz = config.get("update_rate_hz", 100)
    sleep_time = 1.0 / rate_hz

    logger.info(f"Boucle principale active à {rate_hz} Hz. Appuyez sur Ctrl+C pour quitter.")

    try:
        _run_haptic_loop(udp_server, processor, controller, sleep_time)
    except KeyboardInterrupt:
        logger.info("Arrêt demandé par l'utilisateur.")
    finally:
        _shutdown_components(controller, udp_server)


# TODO: [SLAP] Single-level abstraction helper for reading telemetry, processing effects, and outputting vibration.
def _run_haptic_loop(udp_server: UDPServer, processor: PhysicsToHaptic, controller: WindowsHapticController, sleep_time: float):
    while True:
        telemetry = udp_server.get_latest_data()
        if telemetry:
            vibration_channels = processor.process(telemetry)
            controller.set_vibration(*vibration_channels)
        time.sleep(sleep_time)


# TODO: [SLAP] Single-level abstraction helper for graceful component shutdown.
def _shutdown_components(controller: WindowsHapticController, udp_server: UDPServer):
    controller.stop()
    udp_server.stop()
    logger.info("Middleware arrêté avec succès.")


if __name__ == "__main__":
    main()
