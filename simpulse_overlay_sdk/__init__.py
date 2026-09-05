"""
SimPulse In-Game HUD Overlay SDK.
Third-party developers implement BaseHudWidget to create custom HUD widgets.
"""

from simpulse_overlay_sdk.contracts import BaseHudWidget
from simpulse_sdk import HudSlot, HudLayoutSpec, VehicleSensors

__all__ = [
    # Contract
    "BaseHudWidget",
    # Re-exported from simpulse_sdk for convenience
    "HudSlot",
    "HudLayoutSpec",
    "VehicleSensors",
]
