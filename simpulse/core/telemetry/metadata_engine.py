"""
Track/Vehicle Combo Metadata Engine.

Single Responsibility: the active track/vehicle combo identity, and where
that combo's on-disk files live. No timing math (that's DeltaEngine's job),
no fuel/energy math (that's FuelEnergyEngine's job) — this is just "who's
racing, and what filename does that map to" for the whole ref_<track>_<car>.*
family (best-lap telemetry .json, FuelEnergyEngine's .energy.json, and any
future sibling — see get_marks_filepath()'s pattern in reference_profile.py
for the existing .marks.json one).

Deliberately never detects identity itself: it's fed by whoever already
parses the scoring packets robustly enough to know who's driving
(DeltaEngine._apply_scoring_update(), via DeltaEngine._sync_metadata()) —
that keeps a single source of truth for "who is racing", and keeps this
class a pure, easily-testable naming lookup with no packet-format knowledge
of its own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .reference_profile import DEFAULT_REF_LAPS_DIR, clean_name_identifier


class MetadataEngine:
    """Owns the current track/vehicle combo identity and resolves every other
    engine's on-disk filenames from it."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir: Path = Path(base_dir) if base_dir else DEFAULT_REF_LAPS_DIR
        self.track_name: str = ""
        self.vehicle_class: str = ""
        self.vehicle_name: str = ""

    def reset(self) -> None:
        """Clears identity (base_dir is kept — it's a location setting, not
        part of "who's racing")."""
        self.track_name = ""
        self.vehicle_class = ""
        self.vehicle_name = ""

    def update(
        self,
        track_name: str,
        vehicle_class: str = "",
        vehicle_name: str = "",
        base_dir: Optional[Path] = None,
    ) -> bool:
        """Records the active combo (and, optionally, the directory its files
        live in — pass the caller's current override each time, e.g. tests
        monkeypatching delta_engine._REF_LAPS_DIR, rather than only once at
        construction). Returns True if the combo actually changed since the
        last update, so callers can gate their own per-combo resets/reloads
        on a real change rather than repeating them every tick.
        """
        changed = (
            track_name != self.track_name
            or vehicle_class != self.vehicle_class
            or vehicle_name != self.vehicle_name
        )
        self.track_name = track_name
        self.vehicle_class = vehicle_class
        self.vehicle_name = vehicle_name
        if base_dir is not None:
            self.base_dir = Path(base_dir)
        return changed

    def _combo_stem(self) -> Optional[str]:
        """`ref_<track>_<car>` — car falls back to vehicle_name, then
        "default", same priority order as the rest of the ref-laps family
        (see reference_profile.find_telemetry_filepath_for_track)."""
        if not self.track_name:
            return None
        t_clean = clean_name_identifier(self.track_name)
        v_identifier = (
            clean_name_identifier(self.vehicle_class)
            if self.vehicle_class
            else clean_name_identifier(self.vehicle_name)
        )
        if not v_identifier:
            v_identifier = "default"
        return f"ref_{t_clean}_{v_identifier}"

    def get_profile_filepath(self) -> Optional[Path]:
        """ref_<track>_<car>.json — best-lap spatial telemetry (DeltaEngine)."""
        stem = self._combo_stem()
        return self.base_dir / f"{stem}.json" if stem else None

    def get_energy_history_filepath(self) -> Optional[Path]:
        """ref_<track>_<car>.energy.json — FuelEnergyEngine's persisted
        per-lap consumption history."""
        stem = self._combo_stem()
        return self.base_dir / f"{stem}.energy.json" if stem else None
