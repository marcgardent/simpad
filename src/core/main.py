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
        while True:
            telemetry = udp_server.get_latest_data()
            if telemetry:
                l_low, l_high, r_low, r_high = processor.process(telemetry)
                controller.set_vibration(l_low, l_high, r_low, r_high)
            time.sleep(sleep_time)
    except KeyboardInterrupt:
        logger.info("Arrêt demandé par l'utilisateur.")
    finally:
        controller.stop()
        udp_server.stop()
        logger.info("Middleware arrêté avec succès.")


if __name__ == "__main__":
    main()
