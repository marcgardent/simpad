"""SimPad Haptic Middleware — Main entry point (Dear PyGui 60 FPS)."""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.gui.dpg_app import SimPadDPGApp

if __name__ == "__main__":
    try:
        app = SimPadDPGApp()
        app.run()
    except Exception as e:
        import traceback
        print(f"[FATAL] Error starting SimPad: {e}", flush=True)
        traceback.print_exc()
        try:
            with open("simpad_error.log", "w", encoding="utf-8") as f:
                traceback.print_exc(file=f)
        except Exception:
            pass
