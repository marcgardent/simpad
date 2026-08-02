"""SimPad Haptic Middleware — Point d'entrée principal (Dear PyGui 60 FPS)."""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.gui.dpg_app import SimPadDPGApp

if __name__ == "__main__":
    app = SimPadDPGApp()
    app.run()
