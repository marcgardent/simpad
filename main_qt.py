"""
SimPad Qt6 — Main Entry Point (100% Pure Qt6 Stack).
"""

import sys
from pathlib import Path

# Ensure root directory is in sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from simpad_qt.core.app import SimPadQtApp


def main():
    try:
        app = SimPadQtApp(sys.argv)
        sys.exit(app.run())
    except Exception as e:
        import traceback
        print(f"[FATAL] Error starting SimPad Qt6: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
