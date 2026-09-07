"""Configuration of the Expected Timing Inspector."""

from dataclasses import dataclass
from simpulse_sdk import HudSlot


@dataclass
class ExpectedTimingConfig:
    slot: HudSlot = HudSlot.BOTTOM_CENTER
    hud_enabled: bool = True
    scale: float = 1.0

    # rows on the overlay
    show_expected: bool = True
    show_sectors: bool = True      # S1/S2/S3 *expected* (projected) sector times
    show_references: bool = True   # my session best / session best / my all-time best
