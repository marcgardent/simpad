"""
SimPulse Qt6 — Main Entry Point (100% Pure Qt6 Stack).
"""

import sys
from pathlib import Path

# Ensure root directory is in sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from simpulse.app import SimPulseApp


def main():
    try:
        app = SimPulseApp(sys.argv)
        sys.exit(app.run())
    except Exception as e:
        import traceback
        print(f"[FATAL] Error starting SimPulse Qt6: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
