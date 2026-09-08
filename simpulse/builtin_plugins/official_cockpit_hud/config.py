"""
Configuration schema for the Official Cockpit HUD plugin.
"""

from dataclasses import dataclass
from simpulse_sdk import HudSlot


@dataclass
class OfficialCockpitHudConfig:
    """Strongly-typed configuration schema for the Official Cockpit HUD."""
    slot: HudSlot = HudSlot.COCKPIT_CENTER
    hud_enabled: bool = True
    speed_unit: str = "kmh"          # "kmh" or "mph"
    scale: float = 1.0               # 0.7 to 1.5 multiplier
    show_background: bool = True
    show_gear_speed: bool = True
    show_rev_indicator: bool = True
    show_pedals: bool = True
    show_assists: bool = True
    show_tires: bool = True
    show_delta: bool = True
    delta_display_mode: str = "delta"  # "delta" (live +/-) or "expected" (projected finish time)
    # Moving-average window, in seconds of GAME time (0.0-2.0), for the Delta
    # Timer's and Sector Times' live numeric readouts (HudTimeWindowAverage)
    # — 0.0 disables smoothing (reports the latest raw sample as-is).
    hud_smoothing_window_s: float = 0.15
    show_sectors: bool = True
    show_aero: bool = True
    show_lap_status: bool = True
    show_energy: bool = True
