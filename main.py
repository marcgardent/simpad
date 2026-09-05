"""
SimPulse — Main Entry Point (100% Pure Qt6 Stack).
"""

import sys
from pathlib import Path

# Ensure root directory is in sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from simpulse.app import main


if __name__ == "__main__":
    sys.exit(main())
