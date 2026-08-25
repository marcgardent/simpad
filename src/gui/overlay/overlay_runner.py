"""
SimPad Qt HUD Overlay Standalone Process Runner.
Listens to real-time UDP telemetry packets and renders the PySide6 transparent HUD overlay at 60 FPS.
"""

import os
import sys
import time
from pathlib import Path

# Ensure project root is in sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Force XCB for KWin window state sync
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication

from src.gui.overlay.lmu_hud_window import LmuHudQtWindow
from src.telemetry.udp_server import UDPServer
from src.telemetry.sensors import VehicleSensors
from src.utils.window_utils import get_lmu_window_status


def run_overlay_app(port: int = 5000) -> None:
    """Lance le processus autonome d'overlay HUD PySide6."""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("SimPad Qt HUD Overlay")

    overlay = LmuHudQtWindow()
    overlay.show()
    print("[Qt HUD Overlay] Fenêtre HUD Qt affichée.", flush=True)

    udp_server = UDPServer(host="0.0.0.0", port=port)
    try:
        udp_server.start()
        print(f"[Qt HUD Overlay] Écoute UDP active sur le port {port}.", flush=True)
    except Exception as e:
        print(f"[Qt HUD Overlay] Erreur démarrage UDP: {e}", flush=True)

    # Timer de rendu et de mise à jour 60 FPS
    timer = QTimer()
    timer.setInterval(16)

    def on_tick():
        data = udp_server.get_latest_data()
        if data is not None:
            sensors = data.to_sensors()
            overlay.update_telemetry(sensors)
        else:
            # Rendu d'attente
            pass

    timer.timeout.connect(on_tick)
    timer.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    run_overlay_app()
