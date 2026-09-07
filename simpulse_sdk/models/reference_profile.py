"""
SimPulse SDK — Reference Lap Profile read-only view.

`simpulse.core.telemetry.reference_profile.ReferenceLapProfile` (Core) owns the
mutable model: recording, meter-grid construction, annotation editing, and
autosave/load to '.json'/'.marks.json' — none of that is plugin-facing.

`ReferenceLapProfileView` here is the plugin-facing counterpart, same family as
`TelemetryView`: a `@dataclass(frozen=True)` snapshot exposing only the data
and pure read-only helpers (`get_value_at_dist`, annotation labels/phrase keys)
that race_engineer sub-plugins actually consume. Built once per tick by Core
via `ReferenceLapProfile.to_view()` — plugins never see the mutable class, its
file I/O, or `ReferenceLapManager`/`DeltaEngine` singletons.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple


class AnnotationType(str, Enum):
    """Driving reference annotation types."""
    BRAKE = "brake"        # Brake marker ('B' key) -> Audio: "Brake"
    TURN_IN = "turn_in"    # Turn-in marker ('I' key) -> Audio: "Turn"
    TURN = "turn"          # Turn marker ('T' key) -> Auto numbering T1..T30 -> Audio: "Turn 1"..
    GEAR = "gear"          # Gear marker ('1'..'8' keys) -> Audio: "Gear 1".. "Gear 8"


@dataclass(frozen=True)
class TrackAnnotationView:
    """Immutable snapshot of a single track annotation/marker."""
    id: str
    type: AnnotationType = AnnotationType.BRAKE
    distance: float = 0.0  # Distance along the track in meters
    gear: Optional[int] = None  # Gear number if type == GEAR (1 to 8)
    label: Optional[str] = None  # Optional custom label
    color: Optional[Tuple[int, ...]] = None  # Optional custom RGBA color


@dataclass(frozen=True)
class ReferenceLapProfileView:
    """
    Read-only meter-by-meter spatial snapshot of a reference lap, plus its
    driving annotations. Immutable counterpart of Core's `ReferenceLapProfile`
    (see module docstring) — the only reference-lap type plugins may consume.
    """
    track_name: str = ""
    vehicle_name: str = ""
    vehicle_class: str = ""
    lap_time: float = 0.0
    track_length: float = 0.0
    spatial_step: float = 1.0
    num_points: int = 0
    t_grid: Tuple[float, ...] = field(default_factory=tuple)
    speed_grid: Tuple[float, ...] = field(default_factory=tuple)        # Speed in m/s
    throttle_grid: Tuple[float, ...] = field(default_factory=tuple)     # Throttle [0.0 - 1.0]
    brake_grid: Tuple[float, ...] = field(default_factory=tuple)        # Brake [0.0 - 1.0]
    steering_grid: Tuple[float, ...] = field(default_factory=tuple)     # Steering [-1.0 - 1.0]
    gear_grid: Tuple[int, ...] = field(default_factory=tuple)           # Gear (0=N, -1=R, 1..8)
    sector_1_dist: float = 0.0
    sector_2_dist: float = 0.0
    sector_1_time: float = 0.0
    sector_2_time: float = 0.0
    annotations: Tuple[TrackAnnotationView, ...] = field(default_factory=tuple)

    def get_sector_at_dist(self, distance: float) -> int:
        """Returns sector (1, 2 or 3) at a given distance in meters along the track."""
        if self.sector_1_dist > 0.0 and distance < self.sector_1_dist:
            return 1
        if self.sector_2_dist > 0.0 and distance < self.sector_2_dist:
            return 2
        if self.sector_2_dist > 0.0:
            return 3
        if self.track_length > 0.0:
            if distance < (self.track_length / 3.0):
                return 1
            if distance < (self.track_length * 2.0 / 3.0):
                return 2
            return 3
        return 1

    def get_turn_number(self, annotation_id: str) -> Optional[int]:
        """Calculates turn number (1-indexed) for TURN annotations, in track-distance order."""
        turn_anns = sorted(
            (a for a in self.annotations if a.type == AnnotationType.TURN),
            key=lambda a: a.distance,
        )
        for idx, ann in enumerate(turn_anns, start=1):
            if ann.id == annotation_id:
                return idx
        return None

    def get_sorted_turns(self) -> list[Tuple[int, TrackAnnotationView]]:
        """Returns list of turns sorted by distance with their sequential number (1, 2, 3...)."""
        turn_anns = sorted(
            (a for a in self.annotations if a.type == AnnotationType.TURN),
            key=lambda a: a.distance,
        )
        return list(enumerate(turn_anns, start=1))

    def get_annotation_display_label(self, annotation: TrackAnnotationView) -> str:
        """Returns short and clear display label for the annotation."""
        if annotation.label:
            return annotation.label

        if annotation.type == AnnotationType.BRAKE:
            return "Brake"
        elif annotation.type == AnnotationType.TURN_IN:
            return "Turn-in"
        elif annotation.type == AnnotationType.TURN:
            turn_num = self.get_turn_number(annotation.id)
            return f"T{turn_num}" if turn_num is not None else "Turn"
        elif annotation.type == AnnotationType.GEAR:
            g = annotation.gear if annotation.gear is not None else 1
            return f"G{g}"
        return "Marker"

    def get_annotation_phrase_key(self, annotation: TrackAnnotationView) -> str:
        """Returns audio speech key (phrase_key) for Race Engineer."""
        if annotation.type == AnnotationType.BRAKE:
            return "brake"
        elif annotation.type == AnnotationType.TURN_IN:
            return "turn"
        elif annotation.type == AnnotationType.TURN:
            turn_num = self.get_turn_number(annotation.id)
            num = turn_num if turn_num is not None else 1
            num_clamped = min(30, max(1, num))
            return f"turn_{num_clamped}"
        elif annotation.type == AnnotationType.GEAR:
            g = annotation.gear if annotation.gear is not None else 1
            g_clamped = min(8, max(1, g))
            return f"gear_{g_clamped}"
        return "lap"

    def get_value_at_dist(self, player_dist: float) -> dict[str, float]:
        """
        Performs O(1) linear interpolation of all telemetry quantities
        (time, speed km/h, throttle, brake, steering angle) at a given position.
        """
        if self.num_points < 2 or not self.t_grid:
            return {
                "time_into": 0.0,
                "speed_ms": 0.0,
                "speed_kmh": 0.0,
                "throttle": 0.0,
                "brake": 0.0,
                "steering": 0.0,
            }

        step = self.spatial_step if self.spatial_step > 0 else 1.0
        idx_float = player_dist / step
        idx_floor = int(idx_float)

        if idx_floor < 0:
            idx1 = 0
            idx2 = 0
            frac = 0.0
        elif idx_floor >= self.num_points - 1:
            idx1 = self.num_points - 1
            idx2 = self.num_points - 1
            frac = 0.0
        else:
            idx1 = idx_floor
            idx2 = idx_floor + 1
            frac = idx_float - idx_floor

        def _interp(grid: Tuple[float, ...], default: float = 0.0) -> float:
            if not grid or idx1 >= len(grid):
                return default
            v1 = grid[idx1]
            v2 = grid[idx2] if idx2 < len(grid) else v1
            return v1 + frac * (v2 - v1)

        def _get_gear(grid: Tuple[int, ...], default: int = 0) -> int:
            if not grid or idx1 >= len(grid):
                return default
            return int(grid[idx1] if frac < 0.5 else (grid[idx2] if idx2 < len(grid) else grid[idx1]))

        t_val = _interp(self.t_grid, 0.0)
        v_ms = _interp(self.speed_grid, 0.0)
        thr = _interp(self.throttle_grid, 0.0)
        brk = _interp(self.brake_grid, 0.0)
        steer = _interp(self.steering_grid, 0.0)
        gear_val = _get_gear(self.gear_grid, 0)

        return {
            "time_into": t_val,
            "speed_ms": v_ms,
            "speed_kmh": v_ms * 3.6,
            "gear": float(gear_val),
            "throttle": thr,
            "brake": brk,
            "steering": steer,
        }
