"""
SimPulse Core — Reference Lap plugin-facing SDK.

`ReferenceLapApi` is the ONLY way a plugin should touch reference-lap catalog
concerns (list/load reference files, read the active profile, add/remove/move
annotations). It is a thin façade around the real `ReferenceLapManager` —
built once by the host and handed to plugins via `PluginContext.
get_reference_lap_api()`. It carries no logic of its own beyond delegation;
every operation is implemented on `ReferenceLapManager`/`DeltaEngine` (Core),
exactly as documented in `simpulse_sdk/models/reference_profile.py`'s module
docstring: "plugins never see the mutable class, its file I/O, or
ReferenceLapManager/DeltaEngine singletons." Reference Lap Studio is currently
the only plugin that needs this surface.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Union, TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from simpulse_sdk.models.reference_profile import (
    AnnotationType,
    ReferenceLapProfileView,
    ReferenceLapSummary,
    TrackAnnotationView,
)

if TYPE_CHECKING:
    from simpulse.core.reference_lap import ReferenceLapManager


class ReferenceLapApi(QObject):
    """Plugin-facing façade for reference lap catalog concerns."""

    def __init__(self, manager: "ReferenceLapManager", parent: Optional[QObject] = None):
        super().__init__(parent)
        self._manager = manager

    # ---- signals (re-exposed, not the raw manager) -------------------------
    @property
    def profile_changed(self) -> Signal:
        """Fires whenever the active reference profile changes (new load, new
        best lap recorded, or annotations edited). Payload is unused — call
        get_active_profile() to read the new state."""
        return self._manager.reference_profile_changed

    @property
    def annotations_changed(self) -> Signal:
        """Fires whenever annotations on the active profile are added/removed/moved."""
        return self._manager.annotations_changed

    @property
    def delta_updated(self) -> Signal:
        """Fires on every live delta recompute (player_dist, live_delta, ...)."""
        return self._manager.delta_updated

    # ---- reads ---------------------------------------------------------------
    def get_active_profile(self) -> Optional[ReferenceLapProfileView]:
        """Read-only snapshot of the currently active reference profile
        (track/car/lap_time/telemetry grids/annotations), or None if nothing
        is loaded yet for the current track/car."""
        return self._manager.get_active_profile_view()

    def list_reference_laps(self) -> List[ReferenceLapSummary]:
        """Catalog of every reference-lap file saved on disk."""
        return self._manager.list_reference_laps()

    def get_annotations(self) -> List[TrackAnnotationView]:
        """Track annotations (Brake/Turn-in/Turn/Gear) on the active profile."""
        return [
            TrackAnnotationView(
                id=a.id, type=a.type, distance=a.distance, gear=a.gear,
                label=a.label, color=tuple(a.color) if a.color else None,
            )
            for a in self._manager.get_annotations()
        ]

    # ---- actions ---------------------------------------------------------------
    def load_reference_lap(self, file_path: Union[str, Path]) -> bool:
        """Loads a specific reference-lap file and makes it the active
        All-Time Best profile (e.g. picking a file in the Studio's file combo).
        Returns False if the file doesn't exist or fails to parse."""
        return self._manager.load_reference_lap(file_path)

    def add_annotation(
        self,
        ann_type: AnnotationType,
        distance: float,
        gear: Optional[int] = None,
        label: Optional[str] = None,
        color: Optional[tuple] = None,
    ) -> Optional[TrackAnnotationView]:
        """Adds a track annotation (Brake/Turn-in/Turn/Gear) to the active
        profile and auto-persists it to its .marks.json file."""
        ann = self._manager.add_annotation(ann_type, distance, gear=gear, label=label, color=color)
        if ann is None:
            return None
        return TrackAnnotationView(
            id=ann.id, type=ann.type, distance=ann.distance, gear=ann.gear,
            label=ann.label, color=tuple(ann.color) if ann.color else None,
        )

    def remove_annotation(self, annotation_id: str) -> bool:
        return self._manager.remove_annotation(annotation_id)

    def move_annotation(self, annotation_id: str, new_distance: float) -> bool:
        return self._manager.move_annotation(annotation_id, new_distance)
