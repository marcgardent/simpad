"""
SimPulse SDK — Mathematical and Formatting Utilities.
Provides unified response curves, clamping, and lap time formatters.
"""

from __future__ import annotations
import math


def clamp(value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    """Clamps a numeric value to [min_val, max_val]."""
    return min(max_val, max(min_val, value))


def apply_response_curve(raw_intensity: float, gamma: float = 1.0, gain: float = 1.0, min_cutoff: float = 0.0) -> float:
    """
    Applies a parametric exponential response curve (Cutoff threshold + Gamma exponent + Gain scaling).
    """
    if raw_intensity < min_cutoff:
        return 0.0

    norm = (raw_intensity - min_cutoff) / max(0.001, 1.0 - min_cutoff)
    curved = math.pow(clamp(norm), gamma)
    return clamp(curved * gain)


def format_lap_time(seconds: float, *, missing: str = "--:--.---") -> str:
    """UNIFIED project-wide lap-time formatter.

    Canonical form: ``MM:ss.mmm`` (minutes zero-padded to 2 digits, ms padded to
    3) — e.g. ``01:32.450``.  This formatter is the single implementation used
    for whole laps, sector splits, expected times and deltas: never produce
    bare ``ss.mmm`` or non-padded ``M:ss.mmm`` from another module.

    Returns ``missing`` for unrepresentable input: ``<=0``, NaN, +/-Inf or
    ``>=999900`` (sentinels meaning “time unknown / not yet recorded”).
    """
    if (seconds is None or seconds <= 0.0 or math.isnan(seconds)
            or math.isinf(seconds) or seconds >= 999900.0):
        return missing
    mins = int(seconds // 60)
    secs = seconds % 60.0
    return f"{mins:02d}:{secs:06.3f}"


def format_sector_time(seconds: float, *, missing: str = "--") -> str:
    """Canonical formatter for a *sector split* displayed value.

    Same underlying MM:ss.mmm rendering as :func:`format_lap_time` (so packets,
    engine snapshots and the Full scoring parser all emit the very same clock
    format); only the “unknown” token defaults to ``--`` for the compact HUD box.
    """
    return format_lap_time(seconds, missing=missing)
