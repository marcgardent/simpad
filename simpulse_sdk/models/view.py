"""
SimPulse SDK — Immutable Telemetry View.

TelemetryView is the single consolidated, read-only snapshot of TelemetryStateStore
handed to Engines (DeltaEngine, ...) and to Plugins. It bundles the one raw packet
still needed downstream (raw_telemetry, a single well-defined TelemInfo type) and
every derived/cross-channel value the Store computes (presence, lap validity,
hit-count, wheels/surface, speed & pedals, track-limits, unified timing/grid) plus
the authoritative Engine output (delta), once available.

There used to be a `raw_scoring: Optional[Union[FullScoringSession, CompactScoring]]`
field here too — a raw, ambiguous union that made every consumer re-implement its own
isinstance dispatch to tell the two packet shapes apart (see
`VehicleSensors.from_telem_info()`'s `remaining_laps` derivation for the textbook
example). Removed: `timing`/`grid` below are the single merge of both
(`BaseTimingState.merge()`/`FullGridScoringState.from_timing()` in scoring.py) —
anything raw_scoring used to answer, they already answer without a union.

Nothing downstream should ever need to reach into the raw PacketSlot ingestion layer
(TelemetryStateStore.telemetry/.compact_scoring/.full_scoring/etc.) directly — this
frozen dataclass is the one type both Engines and Plugins consume instead. Follows the
same @dataclass(frozen=True) precedent already used for LapDeltaPacket/SectorInfo
(simpulse_sdk/models/delta.py).

Note: frozen prevents reassigning a top-level field, but `timing`/`grid`/`raw_*` are
themselves ordinary (non-frozen) objects owned by the Store — treat this View as
read-only by convention on those nested objects too, never mutate them in place.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple

from isimotor_rawudp_client import TelemInfo

from .scoring import BaseTimingState, FullGridScoringState
from .delta import LapDeltaPacket
from .reference_profile import ReferenceLapProfileView


class TrackCutState(str, Enum):
    """User-facing track-limits state derived from lap_flag (see
    TelemetryStateStore.track_cut_state for the rule). Defined here rather than
    in state_store.py so this leaf module has no import-time dependency back on
    the Store — state_store.py imports it from here instead."""
    GREEN = "green"
    YELLOW = "yellow"
    INVALID = "invalid"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class TelemetryView:
    """Immutable snapshot of TelemetryStateStore at one instant."""

    # Raw packet still needed downstream (Engines/VehicleSensors construction) —
    # read-only pass-through, never mutated by consumers. See module docstring
    # for why there's no raw_scoring next to it any more.
    raw_telemetry: Optional[TelemInfo] = None

    # Unified typed scoring models
    timing: BaseTimingState = field(default_factory=BaseTimingState)
    grid: Optional[FullGridScoringState] = None

    # Authoritative Engine output (DeltaEngine, via ReferenceLapManager), None until
    # the first tick has run.
    delta: Optional[LapDeltaPacket] = None

    # Active reference lap profile (immutable), pushed by ReferenceLapManager
    # whenever it changes (new best lap, track/car switch, reference-mode
    # switch). Plugins read this instead of reaching for
    # ReferenceLapManager.get_instance()/DeltaEngine — see reference_profile.py
    # module docstring: "plugins never see ... ReferenceLapManager/DeltaEngine
    # singletons."
    reference_profile: Optional[ReferenceLapProfileView] = None

    # Wheels / surface
    wheels_on_track: int = 4
    is_on_track: bool = True
    surface_types: Tuple[int, ...] = (0, 0, 0, 0)
    terrain_names: Tuple[str, ...] = ("", "", "", "")

    # Lap validity / track limits
    lap_flag: int = 2
    is_lap_valid: bool = True
    is_lap_invalid: bool = False
    track_cut_state: TrackCutState = TrackCutState.GREEN
    num_penalties: int = 0
    track_limits_steps: int = 0
    steps_per_point: int = 3
    steps_per_penalty: int = 12
    current_sector: int = 1
    total_laps: int = 0

    # Physics / pedals
    speed_kmh: float = 0.0
    speed_mps: float = 0.0
    throttle_pct: float = 0.0
    brake_pct: float = 0.0
    gear: int = 0
    engine_rpm: float = 0.0
    engine_max_rpm: float = 7500.0
    fuel: float = 0.0

    # Presence
    in_realtime: bool = True
    in_garage: bool = False

    # Hit / clean-lap detection
    hit_count_current_lap: int = 0
    is_clean_lap: bool = True

    @classmethod
    def from_store(cls, store) -> "TelemetryView":
        """Builds an immutable snapshot from the current (mutable) Store state.

        `store` is typed loosely (not `TelemetryStateStore`) to avoid a circular
        import — this is only ever called from TelemetryStateStore.snapshot().
        """
        return cls(
            raw_telemetry=store.telemetry.data,
            timing=store.timing,
            grid=store.grid,
            delta=store.delta.data,
            reference_profile=store.reference_profile.data,
            wheels_on_track=store.wheels_on_track,
            is_on_track=store.is_on_track,
            surface_types=store.surface_types,
            terrain_names=store.terrain_names,
            lap_flag=store.lap_flag,
            is_lap_valid=store.is_lap_valid,
            is_lap_invalid=store.is_lap_invalid,
            track_cut_state=store.track_cut_state,
            num_penalties=store.num_penalties,
            track_limits_steps=store.track_limits_steps,
            steps_per_point=store.steps_per_point,
            steps_per_penalty=store.steps_per_penalty,
            current_sector=store.current_sector,
            total_laps=store.total_laps,
            speed_kmh=store.speed_kmh,
            speed_mps=store.speed_mps,
            throttle_pct=store.throttle_pct,
            brake_pct=store.brake_pct,
            gear=store.gear,
            engine_rpm=store.engine_rpm,
            engine_max_rpm=store.engine_max_rpm,
            fuel=store.fuel,
            in_realtime=store.in_realtime,
            in_garage=store.in_garage,
            hit_count_current_lap=store.hit_count_current_lap,
            is_clean_lap=store.is_clean_lap,
        )
