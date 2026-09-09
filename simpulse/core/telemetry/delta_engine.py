"""
SimPulse Telemetry — Delta Engine.
High-precision live lap delta calculator and spatial reference profile engine.

Features:
- Resampled uniform spatial reference grid (1m resolution) for fast, smooth O(1) interpolation.
- Full meter-by-meter telemetry capture: time, speed, throttle, brake, steering.
- Integrated track annotations management (Brake, Turn-in, Turn T1..T30, Gear 1..8).
- 50Hz continuous incremental trapezoidal dead-reckoning integration (no braking/acceleration jitter).
- Multi-Reference Profile Hierarchy: All-Time Best (disk), Session Best, Stint Best, and Last Lap.
- Finish-line Delta Freeze (configurable duration, default 3.5s) for clear HUD driver feedback.
- Live Estimated Lap Time projection (ref_lap_time + live_delta) formatted as M:SS.mmm.
- Strict lap validation (mCountLapFlag == 2, no pit stops, full track coverage, monotonic distance).
- Accurate sector checkpoint deltas (S1, S2, S3) captured at sector boundaries.
- Disk persistence for best laps per (track, car) pair.
- Auto-reset on session / track / vehicle change.
Architecture SOLID.
"""

import os
import time
import json
import logging
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Union

from isimotor_rawudp_client import TelemInfo, CompactScoring, FullScoringSession
from simpulse_sdk.models.delta import DeltaReferenceMode, ExpectedStatus, LapColorStatus, SectorInfo, SplitStatus
from simpulse_sdk.models.scoring import BaseTimingState, FullGridScoringState
from simpulse_sdk.models.timing import (
    TimeLap,
    TimeLapViewModel,
    TimeSectorViewModel,
    TimeStatus,
    TimeTarget,
    resolve_is_personal_record_target,
    resolve_target,
)
from .smoothing import TimeWindowAverage
from .reference_profile import (
    ReferenceLapProfile,
    TrackAnnotation,
    AnnotationType,
    DEFAULT_REF_LAPS_DIR,
    get_marks_filepath,
    find_marks_filepath_for_track,
    find_telemetry_filepath_for_track,
    clean_name_identifier,
)
from .sector_engine import SectorEngine
from .wall_of_fame_engine import WallOfFameEngine
from .metadata_engine import MetadataEngine

logger = logging.getLogger(__name__)

# Project root for saving reference lap profiles
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_REF_LAPS_DIR = DEFAULT_REF_LAPS_DIR
_DEBUG_LOG_PATH = _PROJECT_ROOT / "delta_debug.log"


DELTA_DEBUG_ENABLED: bool = True


def set_delta_debug_enabled(enabled: bool) -> None:
    """Enables or disables writing to delta_debug.log."""
    global DELTA_DEBUG_ENABLED
    DELTA_DEBUG_ENABLED = enabled


def log_delta_debug(msg: str) -> None:
    """Writes a log line to delta_debug.log for live diagnostics."""
    if not DELTA_DEBUG_ENABLED:
        return
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def format_lap_time(seconds: float) -> str:
    """Canonical MM:ss.mmm lap-time formatter (single impl in simpulse_sdk).

    Thin delegator kept so core modules importing from delta_engine keep resolving;
    the actual formatting lives in simpulse_sdk.models.math.format_lap_time (guards
    NaN/inf and returns '--:--.---' for unknown).
    """
    from simpulse_sdk import format_lap_time as _fmt
    return _fmt(seconds)


def sector_time_display_str(seconds: float) -> str:
    """Canonical MM:ss.mmm sector display ('--' when the split is unknown).

    Delegates to simpulse_sdk.models.math.format_sector_time so packets, engine
    snapshots and the Full-scoring parser share one clock format.
    """
    from simpulse_sdk import format_sector_time as _fmt
    return _fmt(seconds, missing="--")


def sector_display_status(val: float, best_val: float, session_best: float | None = None) -> SplitStatus:
    """Color of a displayed sector split time.

    Thin delegation to the single shared rule (core.telemetry.sector_colors) so all
    consumers of frozen sector boxes share one green/purple decision.
    """
    from .sector_colors import sector_split_status
    return sector_split_status(val, personal_best=best_val, session_best=session_best, source="delta")


def _individual_sector_splits(profile) -> Tuple[float, float, float]:
    """Decomposes a ReferenceLapProfile's cumulative loop clocks
    (sector_1_time, sector_2_time, lap_time) into standalone S1/S2/S3 splits.

    Returns 0.0 for any split that can't be derived (missing profile, or a
    cumulative clock that isn't strictly increasing yet).
    """
    if profile is None:
        return 0.0, 0.0, 0.0
    s1c = float(getattr(profile, "sector_1_time", 0.0) or 0.0)
    s2c = float(getattr(profile, "sector_2_time", 0.0) or 0.0)
    lap = float(getattr(profile, "lap_time", 0.0) or 0.0)
    s1 = s1c if s1c > 0.0 else 0.0
    s2 = (s2c - s1c) if (s2c > 0.0 and s1c > 0.0 and s2c > s1c) else 0.0
    s3 = (lap - s2c) if (lap > 0.0 and s2c > 0.0 and lap > s2c) else 0.0
    return s1, s2, s3


def _clean_name(name: str) -> str:
    """Sanitizes track or vehicle name for filenames."""
    if not name:
        return "unknown"
    cleaned = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in name)
    return cleaned.strip("_").lower()


class DeltaEngine:
    """
    Live Lap & Sector Delta Calculation Engine for SimPulse.
    Records and manages spatial meter-by-meter profiles (speed, throttle, brake, steering)
    and associated track annotations.
    """

    def __init__(self):
        self._current_profile: Optional[ReferenceLapProfile] = None
        self._freeze_duration: float = 3.5  # Delta freeze duration at finish line (seconds)
        # Moving-average window, in seconds of GAME time, for smoothed_live_delta
        # (and everything derived from it — see time_status_smoothed). Replaces
        # the old plugin-side HudTimeWindowAverage AND the old dead EMA
        # (ema_samples) — a single canonical smoothing knob, settable via
        # ReferenceLapManager.set_delta_smoothing_window_s(), same pattern as
        # freeze_duration/time_status_eps.
        self._delta_smoothing_window_s: float = 0.15
        self._live_delta_smoother: TimeWindowAverage = TimeWindowAverage(window_s=self._delta_smoothing_window_s)
        # Equality tolerance for TimeStatus's resolve_target/resolve_is_personal_record_target
        # (see TIME_STATUS_SPEC.md "eps") — a display decision, NOT a domain constant,
        # settable via ReferenceLapManager.set_time_status_eps(), same pattern as freeze_duration.
        self.time_status_eps: float = 0.001
        # Combo (track/vehicle) identity + on-disk filename resolution for the
        # whole ref_<track>_<car>.* family — SRP split from this class's own
        # delta/timing math, see MetadataEngine's docstring. Instantiated once
        # (not recreated in reset_session(), unlike _sectors/_wall_of_fame)
        # so nothing that ever comes to hold this reference is left stale by
        # a later session reset — reset_session() just clears its identity.
        self._metadata = MetadataEngine()
        self.reset_session()

    def reset_session(self) -> None:
        """Completely resets engine state (session/track change).

        DUPLICATE STATE (not yet migrated — flagged, not fixed, see each
        field below): DeltaEngine predates TelemetryStateStore's unified
        BaseTimingState/FullGridScoringState and still keeps its own private
        copies of several fields the unified state already carries, updated
        by hand on every tick instead of read once from there. This is real
        technical debt, not a style nit — it's the actual root cause behind
        this session's whole "Insufficient samples" chase: two independent
        trackers of "current car distance" (this class's _last_scoring_dist,
        and TelemetryStateStore's own position tracking) that could disagree
        with each other, instead of one shared value both could trust.
        Every duplicate is marked at its declaration below with which
        unified-state field it shadows and whether replacing it is a safe,
        mechanical swap or needs real design work first — migrating them is
        deliberately NOT done in the same pass as this marking (a
        behavior-changing swap needs its own review/tests, not a
        drive-by)."""
        # DUPLICATE of BaseTimingState.track_name / FullGridScoringState.
        # vehicle_name/.vehicle_class — _apply_scoring_update already
        # receives these fresh, every call, as track_name/veh_name/veh_class
        # parameters (sourced from the SAME unified timing/grid objects
        # update_scoring_from_view was handed) purely to compare against
        # these persistent copies and detect a change by hand. Safe,
        # mechanical migration: hold the fresh values (or the timing/grid
        # object itself) instead of re-copying them into private fields.
        self._track_name: str = ""
        self._vehicle_name: str = ""
        self._vehicle_class: str = ""
        # DUPLICATE of BaseTimingState.track_length — same story as
        # track_name/vehicle_name/vehicle_class above: _apply_scoring_update
        # already receives it fresh every call as track_len.
        self._track_length: float = 0.0
        self._metadata.reset()

        # Active reference mode
        self._ref_mode: DeltaReferenceMode = DeltaReferenceMode.ALL_TIME_BEST

        # Multi-reference profiles
        self._current_profile: Optional[ReferenceLapProfile] = None
        self._all_time_best_profile: Optional[ReferenceLapProfile] = None
        self._session_best_profile: Optional[ReferenceLapProfile] = None
        self._stint_best_profile: Optional[ReferenceLapProfile] = None
        self._last_lap_profile: Optional[ReferenceLapProfile] = None

        self._ref_lap_time: float = 999999.0
        self._all_time_best_lap_time: float = 999999.0
        self._session_best_lap_time: float = 999999.0
        # The game's OWN reported best_lap_time for the player this session
        # (mBestLapTime/bestLapTime on every scoring packet) — authoritative
        # and always available once a timed lap is set, unlike
        # _session_best_lap_time above which only updates once OUR OWN engine
        # has successfully captured a full spatial recording of that lap
        # (>=10 samples, coverage checks, etc.). "MY BEST" display and the
        # green/yellow session-scoped colour logic should never go blank just
        # because our own capture pipeline missed a lap the game already
        # knows about — see _session_lap_bound.
        self._game_session_best_lap_time: float = 999999.0
        # Paddock bests (OTHER cars, this session).  ``lap`` and cumulative split
        # clocks are recorded from Full/dict scoring packets that list the rivals.
        # S2 here is the cumulative time at loop 2 (comparable to cur_sector2).
        self._paddock_best_lap: float = 999999.0
        self._paddock_cum_s1: float = 999900.0
        self._paddock_cum_s2: float = 999900.0
        self._paddock_known: bool = False
        self._stint_best_lap_time: float = 999999.0
        self._last_lap_time: float = 999999.0

        self._ref_t_grid: Optional[List[float]] = None
        self._ref_spatial_step: float = 1.0
        self._ref_num_points: int = 0

        # Current lap samples: list of (dist, time_into, speed_ms, throttle, brake, steering, gear)
        self._current_lap_samples: List[Tuple[float, float, float, float, float, float, int]] = []
        # Diagnostic-only counters, always on (no delta_debug config gate — see
        # _finalize_completed_lap's log line): how many _apply_scoring_update()
        # calls happened since the last lap transition, and how many of those
        # passed the is_flying_lap gate. Answers "did scoring packets even
        # reach DeltaEngine this lap, and if so, why didn't they turn into
        # samples" on the very next "Lap completed"/"Insufficient samples"
        # line, without needing delta_debug.log (often disabled — see
        # config.json's "loggers" -> "delta_debug").
        self._scoring_ticks_this_lap: int = 0
        self._flying_ticks_this_lap: int = 0
        # Same always-on diagnostic pattern, one level deeper: how many
        # _collect_lap_sample() calls this lap were dropped specifically by
        # the monotonic-distance check (see its docstring), plus the min/max
        # player_dist actually observed. A tiny (min, max) span despite many
        # flying_ticks means player_dist itself is barely moving between
        # scoring ticks (dead-reckoning stalled — see _last_scoring_dist's
        # update_physics() integration) — not just noisy/backwards jitter.
        self._sample_monotonic_rejects_this_lap: int = 0
        self._sample_dist_min_this_lap: Optional[float] = None
        self._sample_dist_max_this_lap: Optional[float] = None
        # How many update_physics() calls happened this lap (should track
        # TelemInfo's own 50-120Hz rate) and how many of those actually ran
        # the dead-reckoning integration (dt>0 and speed>0 — see
        # update_physics's own comment). If physics_ticks stays in the same
        # ballpark as scoring_ticks (should be ~10x higher) TelemInfo isn't
        # reaching DeltaEngine at its expected rate at all; if physics_ticks
        # is healthy but dead_reckon_ticks isn't, dt/speed are the problem
        # instead — either way this is the field that actually explains why
        # player_dist (CompactScoring's only source between real position
        # updates) sits frozen for stretches, which is what starves
        # _collect_lap_sample's monotonic-distance check.
        self._physics_ticks_this_lap: int = 0
        self._physics_dead_reckon_ticks_this_lap: int = 0
        self._last_laps_completed: int = -1
        self._last_dist: float = -1.0
        # PARTIAL DUPLICATE of TelemetryStateStore._last_lap_flag — but NOT a
        # safe drop-in swap like track_name/track_length above: the Store's
        # copy goes through _process_lap_validity's own hysteresis (a
        # different concern — TIMING_IN_PROGRESS/TIME_DELETED transition
        # events for the race-engineer voice layer), while this one is the
        # raw, unfiltered per-tick flag DeltaEngine's own colour/validity
        # logic depends on. Needs a real look at whether the Store's
        # hysteresis would still serve DeltaEngine's needs, not a blind swap.
        self._last_lap_flag: int = 2
        # Fed by _apply_scoring_update, read by update_physics: unlike
        # _last_lap_flag (record-keeping validity, e.g. a track-limits cut),
        # these gate the LIVE delta only on genuinely delta-less situations
        # — see is_delta_computable in _apply_scoring_update.
        self._last_in_pits: bool = False
        self._last_in_garage: bool = False

        # DUPLICATE of TelemetryStateStore's own _last_speed_kmh/
        # _last_throttle_pct/_last_brake_pct/_last_gear — same TelemInfo
        # source (speed_mps/unfiltered_throttle/unfiltered_brake/gear),
        # tracked a second time here, in different units (m/s vs km/h, 0-1
        # vs 0-100 pct) — a mechanical unit-converting read instead of an
        # independent copy, not yet done (no _last_steering equivalent
        # exists on the Store today, so that one field stays DeltaEngine-only
        # either way).
        # Last physical inputs
        self._last_speed_ms: float = 0.0
        self._last_throttle: float = 0.0
        self._last_brake: float = 0.0
        self._last_steering: float = 0.0
        self._last_gear: int = 0

        # NOT a simple duplicate, despite looking like one — see
        # TelemetryStateStore.player_lap_dist/_last_lap_dist: that field is
        # PARTLY circular, itself fed by update_delta() from THIS engine's
        # own LapDeltaPacket.player_dist output (see _build_delta_packet).
        # Pointing DeltaEngine at it instead would read back its own answer.
        # The real gap this session's whole "Insufficient samples"/"stale
        # distance" chase kept running into: CompactScoring carries no car
        # position of its own (see update_scoring_from_view's CompactScoring
        # branch), so _last_scoring_dist's own dead-reckoning integration in
        # update_physics is the ONLY thing filling that gap right now — not
        # redundant with the unified state, compensating for what it doesn't
        # provide. Fixing this for real means either giving CompactScoring-
        # only sessions an authoritative position source, or moving this
        # dead-reckoning into TelemetryStateStore itself (so every consumer,
        # not just DeltaEngine, gets a trustworthy continuous position) —
        # real design work, not a rename.
        # Last scoring state (1-2 Hz)
        self._last_scoring_dist: float = 0.0
        self._last_scoring_time_into: float = 0.0
        self._last_scoring_timestamp: float = 0.0
        self._last_lap_start_et: float = 0.0
        # Self-tracked fallback lap-start ET, refreshed on every lap crossing (see
        # _handle_lap_transition). CompactScoring (always-on 10Hz channel) never
        # carries lap_start_et/time_into_lap -- those are FullScoringSession-only
        # fields -- so without this fallback, a session running on CompactScoring
        # alone (FullScoringSession delayed/dropped/failing to resolve the player
        # vehicle, e.g. a full-grid multiplayer race) would compute time_into=0.0
        # forever: no lap samples collected, no live delta, no expected status.
        self._local_lap_start_et: float = 0.0
        self._last_checkpoint_idx: int = -1

        # Current-sector tracking, S1/S2 checkpoint capture, HUD split display and
        # per-sector deltas: all factored into SectorEngine (see its docstring).
        # The `_last_current_sector`/`_s1_captured`/`_last_sector1_time`/... names
        # below stay available as thin delegating properties for existing callers.
        self._sectors = SectorEngine()

        # WallOfFameTimes tracking (my all-time best, my session best, paddock
        # session best) — feeds TimeStatus (see .time_status below). Computed
        # in parallel to the legacy _all_time_best_*/_session_best_*/_paddock_*
        # fields above during the TimeStatus migration (TIME_STATUS_SPEC.md).
        self._wall_of_fame = WallOfFameEngine()

        # Delta & Lap Time freeze at finish line
        self._frozen_final_delta: float = 0.0
        self._freeze_delta_until: float = 0.0
        self._last_completed_lap_time: float = 0.0
        self._last_completed_lap_status: LapColorStatus = LapColorStatus.DEFAULT
        self._last_completed_lap_is_pr: bool = False
        self._freeze_lap_until: float = 0.0
        # Frozen time_status.lap for the freeze window — see _handle_lap_transition.
        self._frozen_lap_vm: TimeLapViewModel = TimeLapViewModel()

        # Last calculated values
        self._live_delta: float = 0.0

        # Smoothed live delta (moving average over _delta_smoothing_window_s of
        # game time — see _live_delta_smoother) and its sector decomposition.
        # Additive to the raw values above; feeds time_status_smoothed only,
        # never time_status. The smoother instance itself (and its configured
        # window_s) is NOT reset here — only its sample buffer is, via
        # _live_delta_smoother.reset() — see _calculate_delta's reset points.
        self._smoothed_live_delta: float = 0.0
        self._smoothed_sector1_delta: float = 0.0
        self._smoothed_sector2_delta: float = 0.0
        self._smoothed_sector3_delta: float = 0.0
        self._smoother_was_freeze: bool = False
        self._live_delta_smoother.reset()

    # ---- Back-compat delegators to SectorEngine ---------------------------------
    # All current-sector tracking, S1/S2 capture, HUD split display and per-sector
    # deltas now live in ``self._sectors`` (see sector_engine.SectorEngine). These
    # properties keep the historical private names resolving to that single home so
    # every existing internal reference (and the tests that reach into them) keeps
    # working unchanged; new code should prefer ``self.sectors`` / ``self._sectors``.
    @property
    def _last_current_sector(self) -> int:
        return self._sectors.last_current_sector

    @_last_current_sector.setter
    def _last_current_sector(self, value: int) -> None:
        self._sectors.last_current_sector = value

    @property
    def _sector_primed(self) -> bool:
        return self._sectors.sector_primed

    @_sector_primed.setter
    def _sector_primed(self, value: bool) -> None:
        self._sectors.sector_primed = value

    @property
    def _s1_captured(self) -> bool:
        return self._sectors.s1_captured

    @_s1_captured.setter
    def _s1_captured(self, value: bool) -> None:
        self._sectors.s1_captured = value

    @property
    def _s2_captured(self) -> bool:
        return self._sectors.s2_captured

    @_s2_captured.setter
    def _s2_captured(self, value: bool) -> None:
        self._sectors.s2_captured = value

    @property
    def _player_s1_time(self) -> float:
        return self._sectors.player_s1_time

    @_player_s1_time.setter
    def _player_s1_time(self, value: float) -> None:
        self._sectors.player_s1_time = value

    @property
    def _player_s1_dist(self) -> float:
        return self._sectors.player_s1_dist

    @_player_s1_dist.setter
    def _player_s1_dist(self, value: float) -> None:
        self._sectors.player_s1_dist = value

    @property
    def _player_s2_time(self) -> float:
        return self._sectors.player_s2_time

    @_player_s2_time.setter
    def _player_s2_time(self, value: float) -> None:
        self._sectors.player_s2_time = value

    @property
    def _player_s2_dist(self) -> float:
        return self._sectors.player_s2_dist

    @_player_s2_dist.setter
    def _player_s2_dist(self, value: float) -> None:
        self._sectors.player_s2_dist = value

    @property
    def _session_split_best_s1(self) -> float:
        return self._sectors.session_split_best_s1

    @_session_split_best_s1.setter
    def _session_split_best_s1(self, value: float) -> None:
        self._sectors.session_split_best_s1 = value

    @property
    def _session_split_best_s2(self) -> float:
        return self._sectors.session_split_best_s2

    @_session_split_best_s2.setter
    def _session_split_best_s2(self, value: float) -> None:
        self._sectors.session_split_best_s2 = value

    @property
    def _session_split_best_s3(self) -> float:
        return self._sectors.session_split_best_s3

    @_session_split_best_s3.setter
    def _session_split_best_s3(self, value: float) -> None:
        self._sectors.session_split_best_s3 = value

    @property
    def _sector1_delta(self) -> float:
        return self._sectors.sector1_delta

    @_sector1_delta.setter
    def _sector1_delta(self, value: float) -> None:
        self._sectors.sector1_delta = value

    @property
    def _sector2_delta(self) -> float:
        return self._sectors.sector2_delta

    @_sector2_delta.setter
    def _sector2_delta(self, value: float) -> None:
        self._sectors.sector2_delta = value

    @property
    def _sector3_delta(self) -> float:
        return self._sectors.sector3_delta

    @_sector3_delta.setter
    def _sector3_delta(self, value: float) -> None:
        self._sectors.sector3_delta = value

    @property
    def _last_sector1_time(self) -> str:
        return self._sectors.last_sector1_time

    @_last_sector1_time.setter
    def _last_sector1_time(self, value: str) -> None:
        self._sectors.last_sector1_time = value

    @property
    def _last_sector1_status(self) -> SplitStatus:
        return self._sectors.last_sector1_status

    @_last_sector1_status.setter
    def _last_sector1_status(self, value: SplitStatus) -> None:
        self._sectors.last_sector1_status = value

    @property
    def _last_sector2_time(self) -> str:
        return self._sectors.last_sector2_time

    @_last_sector2_time.setter
    def _last_sector2_time(self, value: str) -> None:
        self._sectors.last_sector2_time = value

    @property
    def _last_sector2_status(self) -> SplitStatus:
        return self._sectors.last_sector2_status

    @_last_sector2_status.setter
    def _last_sector2_status(self, value: SplitStatus) -> None:
        self._sectors.last_sector2_status = value

    @property
    def _last_sector3_time(self) -> str:
        return self._sectors.last_sector3_time

    @_last_sector3_time.setter
    def _last_sector3_time(self, value: str) -> None:
        self._sectors.last_sector3_time = value

    @property
    def _last_sector3_status(self) -> SplitStatus:
        return self._sectors.last_sector3_status

    @_last_sector3_status.setter
    def _last_sector3_status(self, value: SplitStatus) -> None:
        self._sectors.last_sector3_status = value

    @property
    def sectors(self) -> List[SectorInfo]:
        """Nicer aggregate view of the S1/S2/S3 boxes (time/status/delta/is_current)
        — one list, one shape per box — instead of the flat sector1_*/sector2_*/
        sector3_* trio kept below for backward compatibility."""
        return self._sectors.snapshot()

    @property
    def reference_mode(self) -> DeltaReferenceMode:
        """Historical setting, kept for config/API compatibility. No longer
        selects which profile drives the live delta/HUD — that's always the
        All-Time Best profile now (see _apply_active_profile). Not read by
        anything in this engine any more."""
        return self._ref_mode

    @reference_mode.setter
    def reference_mode(self, mode: DeltaReferenceMode) -> None:
        """Stores the value only (config/API compatibility) — does not change
        the active profile. See the ``reference_mode`` getter docstring."""
        if isinstance(mode, str):
            try:
                mode = DeltaReferenceMode(mode)
            except ValueError:
                mode = DeltaReferenceMode.ALL_TIME_BEST
        self._ref_mode = mode

    @property
    def freeze_duration(self) -> float:
        """Delta freeze duration at finish line in seconds."""
        return self._freeze_duration

    @freeze_duration.setter
    def freeze_duration(self, val: float) -> None:
        self._freeze_duration = max(0.0, float(val))

    @property
    def delta_smoothing_window_s(self) -> float:
        """Moving-average window, in seconds of GAME time, for
        smoothed_live_delta (0.0 = disabled, reports the raw value as-is)."""
        return self._delta_smoothing_window_s

    @delta_smoothing_window_s.setter
    def delta_smoothing_window_s(self, val: float) -> None:
        self._delta_smoothing_window_s = max(0.0, float(val))
        self._live_delta_smoother.window_s = self._delta_smoothing_window_s

    @property
    def current_profile(self) -> Optional[ReferenceLapProfile]:
        """Returns currently active reference profile."""
        return self._current_profile

    @property
    def all_time_best_profile(self) -> Optional[ReferenceLapProfile]:
        return self._all_time_best_profile

    @property
    def session_best_profile(self) -> Optional[ReferenceLapProfile]:
        return self._session_best_profile

    @property
    def stint_best_profile(self) -> Optional[ReferenceLapProfile]:
        return self._stint_best_profile

    @property
    def last_lap_profile(self) -> Optional[ReferenceLapProfile]:
        return self._last_lap_profile

    @property
    def ref_lap_time(self) -> float:
        """Lap time of active reference (seconds)."""
        return self._ref_lap_time

    def get_reference_profile(self) -> Optional[ReferenceLapProfile]:
        """Getter for reference profile."""
        return self._current_profile

    def set_reference_profile(self, profile: Optional[ReferenceLapProfile]) -> None:
        """Manually sets active reference profile."""
        self._all_time_best_profile = profile
        if profile is not None:
            self._all_time_best_lap_time = profile.lap_time
        else:
            self._all_time_best_lap_time = 999999.0
        self._wall_of_fame.load_all_time_from_disk(profile)
        self._apply_active_profile()

    def _apply_active_profile(self) -> None:
        """Applies the reference profile driving the live delta/HUD colours.

        Always the All-Time Best profile — NOT gated by ``reference_mode``.
        Letting the user pick which profile drives the spatial delta curve
        (session/stint/last-lap) meant the HUD could silently show "no
        reference" for an entire session because a non-all-time mode has
        nothing recorded yet (that's the exact confusion this caused). Session
        best / paddock best still exist as SCALAR colour baselines (see
        sector_colors.expected_status) — that's a separate, always-on
        comparison, unrelated to which spatial profile computes live_delta.
        """
        target_prof = self._all_time_best_profile

        self._current_profile = target_prof
        if target_prof is not None and target_prof.t_grid and len(target_prof.t_grid) > 1:
            self._ref_lap_time = target_prof.lap_time
            self._ref_spatial_step = target_prof.spatial_step
            self._ref_t_grid = target_prof.t_grid
            self._ref_num_points = target_prof.num_points
            self._track_name = target_prof.track_name
            self._track_length = target_prof.track_length
        else:
            self._ref_lap_time = 999999.0
            self._ref_t_grid = None
            self._ref_num_points = 0

        log_delta_debug(
            f"[APPLY_MODE] mode={self._ref_mode.value}, target_present={target_prof is not None}, "
            f"has_ref={self.has_reference}, ref_lap_time={self._ref_lap_time:.3f}s, points={self._ref_num_points}"
        )

        # Immediate dynamic delta recalculation against new reference
        if self._last_scoring_dist >= 0.0 and self._last_scoring_time_into > 0.0:
            self._calculate_delta(self._last_scoring_dist, self._last_scoring_time_into)
        else:
            self._live_delta = 0.0
            self._reset_delta_smoother()
            self._sectors.clear_deltas()
            log_delta_debug(
                f"[APPLY_MODE_CLEAR_DELTAS] last_scoring_dist={self._last_scoring_dist:.1f}, "
                f"last_scoring_time_into={self._last_scoring_time_into:.3f}s — sector deltas zeroed here"
            )

    def _find_player_vehicle(self, vehicles: list) -> Optional[dict]:
        """SLAP Helper: Finds player vehicle in scoring vehicles list."""
        if not isinstance(vehicles, list):
            return None
        for v in vehicles:
            if isinstance(v, dict) and (v.get("mIsPlayer") or v.get("isPlayer")):
                return v
        for v in vehicles:
            if isinstance(v, dict) and v.get("mControl") == 0:
                return v
        return None

    def _handle_lap_transition(
        self,
        laps_comp: int,
        last_lap_time: float,
        lap_flag: int,
        in_garage: bool,
        in_pits: bool,
        current_et: float = 0.0,
    ) -> None:
        """SLAP Helper: Finalizes previous lap and resets state for new lap."""
        # Initialization on first received packet
        if self._last_laps_completed < 0:
            self._last_laps_completed = laps_comp
            self._current_lap_samples = []
            self._scoring_ticks_this_lap = 0
            self._flying_ticks_this_lap = 0
            self._sample_monotonic_rejects_this_lap = 0
            self._sample_dist_min_this_lap = None
            self._sample_dist_max_this_lap = None
            self._physics_ticks_this_lap = 0
            self._physics_dead_reckon_ticks_this_lap = 0
            # Best-effort local lap-start reference for the CompactScoring-only
            # fallback (see _local_lap_start_et) — we join mid-lap so this slightly
            # undercounts time_into until the next clean line crossing corrects it.
            if current_et > 0.0:
                self._local_lap_start_et = current_et
            return

        # Case 1: Session reset / Restart (mTotalLaps returns to 0 or decreases)
        if laps_comp < self._last_laps_completed:
            logger.info(f"[DeltaEngine] Session reset detected: laps completed went from {self._last_laps_completed} to {laps_comp}")
            print(f"[DeltaEngine] Session reset: lap counter reset to {laps_comp}", flush=True)
            log_delta_debug(f"[SESSION_RESET] laps_completed went from {self._last_laps_completed} to {laps_comp}")
            self._current_lap_samples = []
            self._scoring_ticks_this_lap = 0
            self._flying_ticks_this_lap = 0
            self._sample_monotonic_rejects_this_lap = 0
            self._sample_dist_min_this_lap = None
            self._sample_dist_max_this_lap = None
            self._physics_ticks_this_lap = 0
            self._physics_dead_reckon_ticks_this_lap = 0
            self._sectors.reset_lap_capture(clear_primed=True)
            self._reset_delta_smoother()
            self._last_laps_completed = laps_comp
            if current_et > 0.0:
                self._local_lap_start_et = current_et
            return

        # Case 2: Crossing start/finish line (new completed lap)
        if laps_comp > self._last_laps_completed:
            log_delta_debug(
                f"[LAP_LINE_CROSS] lap_completed={laps_comp} (was {self._last_laps_completed}), "
                f"last_lap_time={last_lap_time:.3f}s, flag={lap_flag}, in_pits={in_pits}, in_garage={in_garage}"
            )

            # Evaluation of color status for completed lap — delegates to the same
            # shared rule as the live "expected" projection and the sector splits
            # (sector_colors.expected_status): purple = beat the paddock (other
            # cars) this session, green = beat my own session best, yellow = valid
            # but no improvement. This used to be reimplemented inline here with a
            # DIFFERENT rule (purple on ANY personal-best improvement) that never
            # looked at paddock data at all, so beating your own session best —
            # which should be green — always won the purple branch first and green/
            # yellow were effectively dead code for the completed-lap badge.
            prev_session_best = self._session_best_lap_time
            prev_all_time_best = self._all_time_best_lap_time
            prev_paddock_best = self._paddock_best_lap if self._paddock_known else None

            if lap_flag != 2 or in_pits or in_garage:
                lap_status = LapColorStatus.INVALID
            elif last_lap_time > 0.0:
                from .sector_colors import expected_status
                status = expected_status(
                    last_lap_time,
                    ever=None,
                    paddock=prev_paddock_best,
                    session=prev_session_best if prev_session_best < 999900.0 else None,
                    invalid=False,
                    source="delta.completed_lap",
                )
                lap_status = LapColorStatus.DEFAULT if status == ExpectedStatus.WHITE else LapColorStatus(status.value)
            else:
                lap_status = LapColorStatus.DEFAULT

            self._last_completed_lap_time = last_lap_time
            self._last_completed_lap_status = lap_status
            # PR ("personal record"): this lap beat my all-time best — kept
            # separate from lap_status's colour tiers (session-scoped only,
            # see expected_lap_status) and surfaced as a text tag instead.
            self._last_completed_lap_is_pr = (
                lap_status != LapColorStatus.INVALID and last_lap_time > 0.0
                and prev_all_time_best < 999900.0 and last_lap_time <= prev_all_time_best + 0.001
            )

            # Frozen TimeStatus.lap for the just-completed lap — resolved
            # against WallOfFameTimes as it stood BEFORE this lap updates it
            # below (self._wall_of_fame.snapshot() here IS the "before" state,
            # update_from_lap_completed() only runs inside
            # _finalize_completed_lap further down). Needed because
            # time_status.lap is otherwise a CONTINUOUS live projection of the
            # NEW lap — reading it during the freeze window would compare this
            # very lap's own result against a WallOfFame that already includes
            # it (e.g. a brand-new best always resolving as merely "equalled",
            # never "beaten" — the same off-by-one-lap bug
            # resolve_is_personal_record_target's strict "<" prevents at the
            # instant level, re-introduced one level up if not frozen here).
            is_lap_valid = (lap_status != LapColorStatus.INVALID and last_lap_time > 0.0)
            wof_before = self._wall_of_fame.snapshot()
            eps = self.time_status_eps
            if is_lap_valid:
                frozen_target = resolve_target(last_lap_time, wof_before, "total", eps)
                frozen_is_pr = resolve_is_personal_record_target(last_lap_time, wof_before, "total", eps)
            else:
                frozen_target = TimeTarget.NONE
                frozen_is_pr = False
            self._frozen_lap_vm = TimeLapViewModel(
                target=frozen_target,
                expected_time=last_lap_time if last_lap_time > 0.0 else 0.0,
                delta_time=self._live_delta,
                is_personal_record_target=frozen_is_pr,
            )

            # Capture and freeze final delta and lap time before reset
            self._frozen_final_delta = self._live_delta
            if self._freeze_duration > 0.0:
                freeze_until = time.time() + self._freeze_duration
                self._freeze_delta_until = freeze_until
                self._freeze_lap_until = freeze_until
            else:
                self._freeze_delta_until = 0.0
                self._freeze_lap_until = 0.0

            # try/finally: a real session showed _current_lap_samples STILL
            # holding the just-finished lap's last sample deep into the next
            # one (poisoning its every reading, same mechanism as the
            # crossing-tick fix below, just never actually reaching this
            # reset at all) despite _finalize_completed_lap() visibly
            # completing (its own "New All-Time Best"/"File saved to disk"
            # lines printed) — meaning something between there and here was
            # throwing, silently, with no traceback surfacing anywhere. This
            # guarantees the reset happens even if _finalize_completed_lap()
            # (profile resampling, disk I/O, WallOfFame update, all real
            # ways to fail) raises, and — unlike before — actually surfaces
            # that exception instead of leaving it to be silently swallowed
            # by whatever wraps this call further up the stack.
            try:
                self._finalize_completed_lap(
                    lap_time=last_lap_time,
                    lap_flag=lap_flag,
                    in_garage=in_garage,
                    in_pits=in_pits,
                )
            except Exception:
                logger.exception(
                    "[DeltaEngine] _finalize_completed_lap raised — lap samples "
                    "still being reset for the new lap, but this lap's reference "
                    "recording may be incomplete/corrupted."
                )
                print("[DeltaEngine] _finalize_completed_lap CRASHED (see logger.exception above) — recovering for the new lap regardless", flush=True)
            finally:
                self._current_lap_samples = []
                self._scoring_ticks_this_lap = 0
                self._flying_ticks_this_lap = 0
                self._sample_monotonic_rejects_this_lap = 0
                self._sample_dist_min_this_lap = None
                self._sample_dist_max_this_lap = None
                self._physics_ticks_this_lap = 0
                self._physics_dead_reckon_ticks_this_lap = 0
            # _last_scoring_dist's own wrap (see update_physics's dead-
            # reckoning block) only runs inside a dt>0/speed>0 physics tick —
            # if THIS scoring tick's player_dist (read from _last_scoring_dist
            # for a CompactScoring-only frame — see _apply_scoring_update)
            # fires before the next physics tick gets a chance to wrap it,
            # it's still sitting at the just-finished lap's tail (near
            # _track_length), not near 0. _current_lap_samples was JUST
            # emptied above, so THAT stale, near-track-length value would be
            # accepted unconditionally as the new lap's very first sample
            # (nothing to compare it against yet) — poisoning every genuinely
            # low, correctly-increasing reading for the rest of the lap,
            # which would all fail the monotonic-distance check against it
            # until the car's real progress caught back up. Wrapping it here,
            # right where the lap boundary is actually detected, closes that
            # race instead of leaving it to whichever tick happens to run
            # next. A no-op if it's already correctly wrapped (or unknown).
            if self._track_length > 0.0 and self._last_scoring_dist >= self._track_length:
                self._last_scoring_dist -= self._track_length
            # New lap starts now: refresh the CompactScoring-only fallback reference
            # (see _local_lap_start_et) whether or not FullScoringSession ever
            # supplies its own authoritative lap_start_et for this lap.
            if current_et > 0.0:
                self._local_lap_start_et = current_et
            self._sectors.reset_lap_capture(clear_primed=False)

        self._last_laps_completed = laps_comp

    def _handle_sector_transition(self, curr_sec: int, time_into: float = 0.0, player_dist: float = 0.0, lap_crossed: Optional[bool] = None) -> None:
        """SLAP Helper: Memorizes exact time and distance when crossing S1/S2 splits.

        Thin delegator — the guard logic (one-way forward-step, jitter rejection,
        3->1 wrap qualification) now lives in SectorEngine.handle_transition;
        see its docstring for the full rationale.
        """
        self._sectors.handle_transition(
            curr_sec,
            time_into=time_into,
            player_dist=player_dist,
            lap_crossed=lap_crossed,
            fallback_time=self._last_scoring_time_into,
            fallback_dist=self._last_scoring_dist,
            log=log_delta_debug,
        )

    def _refresh_display_sector_times(
        self,
        *,
        cur_sector1: float = 0.0,
        cur_sector2: float = 0.0,
        last_sector1: float = 0.0,
        last_sector2: float = 0.0,
        last_lap_time: float = 0.0,
        best_sector1: float = 0.0,
        best_sector2: float = 0.0,
        best_lap_time: float = 0.0,
        session_best_s1: float = 0.0,
        session_best_s2: float = 0.0,
        session_best_s3: float = 0.0,
    ) -> None:
        """
        Keeps the HUD per-sector times stable across packets.

        Thin delegator to SectorEngine.refresh_display_times — see its docstring for
        the cur_*/last_* composition rule that keeps a split from flicking to '--'
        mid-lap. The paddock (other cars) violet-highlight inputs come from this
        engine's own rival-tracking state, so they're passed through as parameters.
        """
        self._sectors.refresh_display_times(
            cur_sector1=cur_sector1,
            cur_sector2=cur_sector2,
            last_sector1=last_sector1,
            last_sector2=last_sector2,
            last_lap_time=last_lap_time,
            best_sector1=best_sector1,
            best_sector2=best_sector2,
            best_lap_time=best_lap_time,
            paddock_known=self._paddock_known,
            paddock_cum_s1=self._paddock_cum_s1,
            paddock_cum_s2=self._paddock_cum_s2,
        )

    def _collect_lap_sample(
        self,
        time_into: float,
        player_dist: float,
        speed_ms: float = 0.0,
        throttle: float = 0.0,
        brake: float = 0.0,
        steering: float = 0.0,
        gear: int = 0,
    ) -> None:
        """SLAP Helper: Collects live lap samples (full telemetry) for reference profile building.

        Every rejection is logged (full float precision, not the 1-decimal
        rounding _apply_scoring_update's own [DELTA_NO_REF]/[SCORING_NOT_FLYING]
        diagnostics use) — this is the ONLY place that decides whether a
        flying-lap tick actually becomes a saved checkpoint, and it was
        previously silent, making "why did an otherwise-flying lap end up
        with almost no samples" impossible to answer without guessing."""
        # Always-on (no delta_debug gate): track the full span of player_dist
        # values actually offered to this function this lap, regardless of
        # whether they end up accepted — see the field's docstring for why
        # (distinguishes "stalled dead-reckoning" from "noisy jitter").
        if self._sample_dist_min_this_lap is None or player_dist < self._sample_dist_min_this_lap:
            self._sample_dist_min_this_lap = player_dist
        if self._sample_dist_max_this_lap is None or player_dist > self._sample_dist_max_this_lap:
            self._sample_dist_max_this_lap = player_dist

        if time_into <= 0.0 or player_dist < 0.0:
            log_delta_debug(
                f"[SAMPLE_REJECTED] invalid inputs: player_dist={player_dist!r}, time_into={time_into!r}"
            )
            return
        if self._track_length > 0.0 and player_dist > self._track_length + 200.0:
            log_delta_debug(
                f"[SAMPLE_REJECTED] out of track range: player_dist={player_dist!r} > "
                f"track_length+200={self._track_length + 200.0!r}"
            )
            return
        if self._current_lap_samples and player_dist <= self._current_lap_samples[-1][0]:
            self._sample_monotonic_rejects_this_lap += 1
            log_delta_debug(
                f"[SAMPLE_REJECTED] not monotonic: player_dist={player_dist!r} <= "
                f"last_sample_dist={self._current_lap_samples[-1][0]!r} (time_into={time_into!r})"
            )
            return
        self._current_lap_samples.append((
            player_dist,
            time_into,
            speed_ms,
            throttle,
            brake,
            steering,
            gear,
        ))

    def update_scoring(
        self,
        scoring_js: Union[FullScoringSession, CompactScoring, Dict[str, Union[str, int, float, bool, None]]],
    ) -> None:
        """
        Processes a Scoring packet (FullScoringSession, CompactScoring or JSON dict).
        Handles lap transitions, session resets, and sector transitions.
        """
        now = time.time()
        if isinstance(scoring_js, FullScoringSession):
            track_name = scoring_js.track_name.strip()
            track_len = float(scoring_js.lap_dist)
            current_et = float(scoring_js.current_et)

            player_veh = scoring_js.player_vehicle
            if not player_veh:
                return
            veh_name = player_veh.vehicle_name.strip()
            veh_class = player_veh.vehicle_class.strip()
            laps_comp = int(player_veh.total_laps)
            lap_start_et = float(player_veh.lap_start_et)
            time_into_lap = float(player_veh.time_into_lap)
            player_dist = float(player_veh.lap_dist)
            raw_sec = int(player_veh.sector)
            in_garage = bool(player_veh.in_garage_stall)
            in_pits = bool(player_veh.in_pits)
            lap_flag = int(player_veh.count_lap_flag)
            last_lap_time = float(player_veh.last_lap_time)
            cur_s1 = float(player_veh.cur_sector1)
            cur_s2 = float(player_veh.cur_sector2)
            last_s1 = float(player_veh.last_sector1)
            last_s2 = float(player_veh.last_sector2)
            best_s1 = float(player_veh.best_sector1)
            best_s2 = float(player_veh.best_sector2)
            best_lap = float(player_veh.best_lap_time)
        elif isinstance(scoring_js, CompactScoring):
            track_name = scoring_js.track_name.strip()
            track_len = float(scoring_js.lap_dist)
            current_et = float(scoring_js.current_et)
            veh_name = self._vehicle_name
            veh_class = self._vehicle_class
            laps_comp = int(scoring_js.total_laps)
            lap_start_et = 0.0
            time_into_lap = 0.0
            # CompactScoring.lap_dist represents total track length (e.g. 5781m), NOT car position!
            player_dist = self._last_scoring_dist
            raw_sec = int(scoring_js.sector)
            in_garage = bool(scoring_js.in_garage_stall)
            in_pits = False
            lap_flag = int(scoring_js.count_lap_flag)
            last_lap_time = float(scoring_js.last_lap_time)
            cur_s1 = float(scoring_js.cur_sector1)
            cur_s2 = float(scoring_js.cur_sector2)
            last_s1 = float(scoring_js.last_sector1)
            last_s2 = float(scoring_js.last_sector2)
            best_s1 = float(scoring_js.best_sector1)
            best_s2 = float(scoring_js.best_sector2)
            best_lap = float(scoring_js.best_lap_time)
        else:
            scoring_info = scoring_js.get("mScoringInfo", scoring_js) if isinstance(scoring_js, dict) else {}
            track_name = str(scoring_info.get("mTrackName", scoring_info.get("trackName", ""))).strip()
            track_len = float(scoring_info.get("mLapDist", scoring_info.get("lapDist", 0.0)))

            vehicles = scoring_info.get("mVehicles", scoring_info.get("vehicles", []))
            player_veh = self._find_player_vehicle(vehicles)
            if not player_veh:
                return

            veh_name = str(player_veh.get("mVehicleName", player_veh.get("vehicleName", ""))).strip()
            veh_class = str(player_veh.get("mVehicleClass", player_veh.get("vehicleClass", ""))).strip()
            laps_comp = int(player_veh.get("mTotalLaps", player_veh.get("totalLaps", 0)))
            current_et = float(scoring_info.get("mCurrentET", scoring_info.get("currentET", 0.0)))
            lap_start_et = float(player_veh.get("mLapStartET", player_veh.get("lapStartET", 0.0)))
            time_into_lap = float(player_veh.get("mTimeIntoLap", -1.0))
            player_dist = float(player_veh.get("mLapDist", 0.0))
            raw_sec = int(player_veh.get("mSector", 1))
            in_garage = bool(player_veh.get("mInGarageStall", player_veh.get("inGarageStall", False)))
            in_pits = bool(player_veh.get("mInPits", player_veh.get("inPits", False)))
            lap_flag = int(player_veh.get("mCountLapFlag", player_veh.get("countLapFlag", 2)))
            last_lap_time = float(player_veh.get("mLastLapTime", -1.0))
            cur_s1 = float(player_veh.get("mCurSector1", player_veh.get("curSector1", 0.0)))
            cur_s2 = float(player_veh.get("mCurSector2", player_veh.get("curSector2", 0.0)))
            last_s1 = float(player_veh.get("mLastSector1", player_veh.get("lastSector1", 0.0)))
            last_s2 = float(player_veh.get("mLastSector2", player_veh.get("lastSector2", 0.0)))
            best_s1 = float(player_veh.get("mBestSector1", player_veh.get("bestSector1", 0.0)))
            best_s2 = float(player_veh.get("mBestSector2", player_veh.get("bestSector2", 0.0)))
            best_lap = float(player_veh.get("mBestLapTime", player_veh.get("bestLapTime", 0.0)))

        # Session split bests / paddock scan need every car listed in this packet;
        # CompactScoring carries none (only the player), Full/dict expose the grid.
        vehicles_src: list = []
        if isinstance(scoring_js, FullScoringSession):
            vehicles_src = list(scoring_js.vehicles)
        elif isinstance(scoring_js, dict):
            scoring_info = scoring_js.get("mScoringInfo", scoring_js) if isinstance(scoring_js, dict) else {}
            vehicles_src = list(scoring_info.get("mVehicles", scoring_info.get("vehicles", [])))

        self._apply_scoring_update(
            now=now, track_name=track_name, track_len=track_len, current_et=current_et,
            veh_name=veh_name, veh_class=veh_class, laps_comp=laps_comp,
            lap_start_et=lap_start_et, time_into_lap=time_into_lap, player_dist=player_dist,
            raw_sec=raw_sec, in_garage=in_garage, in_pits=in_pits, lap_flag=lap_flag,
            last_lap_time=last_lap_time, cur_s1=cur_s1, cur_s2=cur_s2, last_s1=last_s1,
            last_s2=last_s2, best_s1=best_s1, best_s2=best_s2, best_lap=best_lap,
            vehicles_src=vehicles_src,
        )

    def update_scoring_from_view(
        self,
        timing: BaseTimingState,
        grid: Optional[FullGridScoringState] = None,
    ) -> None:
        """
        Processes the consolidated View (``TelemetryStateStore.timing``/``.grid``)
        instead of re-parsing a raw packet. Same processing core as update_scoring()
        (``_apply_scoring_update``) — this is only a typed field extraction.

        ``grid`` (FullGridScoringState) mirrors update_scoring()'s FullScoringSession/
        dict branch (multi-car session, player pit/lap-start specifics); when it is
        None, only ``timing`` (BaseTimingState) is available, mirroring the
        CompactScoring branch — including its dead-reckoned player_dist (CompactScoring
        never carries car position, only DeltaEngine's own 100Hz integration does) and
        its vehicle name/class kept from engine state (CompactScoring carries neither).
        """
        now = time.time()
        if grid is not None:
            track_name = grid.track_name
            track_len = grid.track_length
            current_et = grid.current_et
            veh_name = grid.vehicle_name
            veh_class = grid.vehicle_class
            laps_comp = grid.total_laps
            lap_start_et = grid.lap_start_et
            time_into_lap = grid.time_into_lap
            player_dist = grid.car_lap_dist
            raw_sec = grid.sector
            in_garage = grid.in_garage
            in_pits = grid.in_pits
            lap_flag = grid.count_lap_flag
            last_lap_time = grid.last_lap_time
            cur_s1 = grid.cur_sector1
            cur_s2 = grid.cur_sector2
            last_s1 = grid.last_sector1
            last_s2 = grid.last_sector2
            best_s1 = grid.best_sector1
            best_s2 = grid.best_sector2
            best_lap = grid.best_lap_time
            vehicles_src = list(grid.vehicles)
        else:
            track_name = timing.track_name
            track_len = timing.track_length
            current_et = timing.current_et
            veh_name = self._vehicle_name
            veh_class = self._vehicle_class
            laps_comp = timing.total_laps
            lap_start_et = 0.0
            time_into_lap = 0.0
            # CompactScoring.lap_dist represents total track length (e.g. 5781m), NOT
            # car position — already disambiguated into timing.track_length above.
            player_dist = self._last_scoring_dist
            raw_sec = timing.sector
            in_garage = timing.in_garage
            in_pits = False
            lap_flag = timing.count_lap_flag
            last_lap_time = timing.last_lap_time
            cur_s1 = timing.cur_sector1
            cur_s2 = timing.cur_sector2
            last_s1 = timing.last_sector1
            last_s2 = timing.last_sector2
            best_s1 = timing.best_sector1
            best_s2 = timing.best_sector2
            best_lap = timing.best_lap_time
            vehicles_src = []

        self._apply_scoring_update(
            now=now, track_name=track_name, track_len=track_len, current_et=current_et,
            veh_name=veh_name, veh_class=veh_class, laps_comp=laps_comp,
            lap_start_et=lap_start_et, time_into_lap=time_into_lap, player_dist=player_dist,
            raw_sec=raw_sec, in_garage=in_garage, in_pits=in_pits, lap_flag=lap_flag,
            last_lap_time=last_lap_time, cur_s1=cur_s1, cur_s2=cur_s2, last_s1=last_s1,
            last_s2=last_s2, best_s1=best_s1, best_s2=best_s2, best_lap=best_lap,
            vehicles_src=vehicles_src,
        )

    def _apply_scoring_update(
        self,
        *,
        now: float,
        track_name: str,
        track_len: float,
        current_et: float,
        veh_name: str,
        veh_class: str,
        laps_comp: int,
        lap_start_et: float,
        time_into_lap: float,
        player_dist: float,
        raw_sec: int,
        in_garage: bool,
        in_pits: bool,
        lap_flag: int,
        last_lap_time: float,
        cur_s1: float,
        cur_s2: float,
        last_s1: float,
        last_s2: float,
        best_s1: float,
        best_s2: float,
        best_lap: float,
        vehicles_src: list,
    ) -> None:
        """
        Single shared scoring-update core: sector/lap transitions, delta calculation,
        paddock & session bests. Fed by either update_scoring() (raw packet) or
        update_scoring_from_view() (consolidated View) — this is the only place this
        logic is implemented; the two callers only differ in how they extract these
        fields from their respective source.
        """
        # ----- Session split bests (single rule shared with parser for status) -----
        # Updated on whole-session packets (Full/dict expose every car); Compact
        # scoring falls back to the most recently observed session splits so status
        # of a given frozen split does not flip green/purple frame-to-frame.
        self._sectors.update_session_bests(vehicles_src)
        self._wall_of_fame.update_from_scoring(best_lap, vehicles_src)

        if vehicles_src:
            # ----- paddock scalar: best full-lap of the OTHER cars this session -----
            def _is_player(v):
                if isinstance(v, dict):
                    for k in ("mIsPlayer", "isPlayer", "is_player"):
                        if k in v:
                            return bool(v.get(k))
                    ctrl = v.get("mControl", v.get("control", None))
                    return ctrl is not None and int(ctrl) == 0
                return bool(getattr(v, "is_player", False)) or (getattr(v, "control", None) == 0)

            min_other_lap = 999900.0
            min_other_s1 = 999900.0
            min_other_s2 = 999900.0
            for v in vehicles_src:
                if _is_player(v):
                    continue
                if isinstance(v, dict):
                    bs1 = float(v.get("mBestSector1", v.get("bestSector1", 0.0)) or 0.0)
                    bs2 = float(v.get("mBestSector2", v.get("bestSector2", 0.0)) or 0.0)
                    blap = float(v.get("mBestLapTime", v.get("bestLapTime", 0.0)) or 0.0)
                else:
                    bs1 = float(getattr(v, "best_sector1", 0.0) or 0.0)
                    bs2 = float(getattr(v, "best_sector2", 0.0) or 0.0)
                    blap = float(getattr(v, "best_lap_time", 0.0) or 0.0)
                if 0.0 < blap < min_other_lap:
                    min_other_lap = blap
                # cumulative loop clocks from a *coherent* timed lap of that rival
                if bs1 > 0.0 and bs2 > bs1:
                    if bs1 < min_other_s1:
                        min_other_s1 = bs1
                    if bs2 < min_other_s2:
                        min_other_s2 = bs2
            if min_other_lap < 999900.0:
                self._paddock_best_lap = min_other_lap
                self._paddock_known = True
                self._paddock_cum_s1 = min_other_s1
                self._paddock_cum_s2 = min_other_s2

        # Refresh stable per-sector HUD display (keeps intermediate sectors frozen).
        self._refresh_display_sector_times(
            cur_sector1=cur_s1,
            cur_sector2=cur_s2,
            last_sector1=last_s1,
            last_sector2=last_s2,
            last_lap_time=last_lap_time,
            best_sector1=best_s1,
            best_sector2=best_s2,
            best_lap_time=best_lap,
        )

        # Session/track/vehicle change
        if track_name and (track_name != self._track_name or (veh_name and veh_name != self._vehicle_name)):
            logger.info(f"[DeltaEngine] Reset session: track='{track_name}', veh='{veh_name}', class='{veh_class}'")
            print(f"[DeltaEngine] Track/session change detected: '{track_name}' (Car: {veh_name})", flush=True)
            log_delta_debug(f"[TRACK_CHANGE] track='{track_name}', veh='{veh_name}', class='{veh_class}', laps={laps_comp}")
            self._track_name = track_name
            self._vehicle_name = veh_name
            self._vehicle_class = veh_class
            self._current_lap_samples = []
            self._scoring_ticks_this_lap = 0
            self._flying_ticks_this_lap = 0
            self._sample_monotonic_rejects_this_lap = 0
            self._sample_dist_min_this_lap = None
            self._sample_dist_max_this_lap = None
            self._physics_ticks_this_lap = 0
            self._physics_dead_reckon_ticks_this_lap = 0
            self._last_laps_completed = laps_comp
            self._last_checkpoint_idx = -1
            self._sectors.reset_lap_capture(clear_primed=True)
            self._reset_delta_smoother()
            self._last_scoring_timestamp = 0.0
            self._local_lap_start_et = current_et if current_et > 0.0 else 0.0
            # BUGFIX: these two were never reset here, so _load_reference_profile()
            # below -> _apply_active_profile() would compute (or clear_deltas()
            # against) a delta/sector-split using distance+time_into from the
            # PREVIOUS track/session — garbage at best, an unwanted blank/reset
            # of the sector boxes at worst, right at every track change.
            self._last_scoring_dist = 0.0
            self._last_scoring_time_into = 0.0

            # Reset session and stint best
            self._session_best_profile = None
            self._stint_best_profile = None
            self._last_lap_profile = None
            self._session_best_lap_time = 999999.0
            self._stint_best_lap_time = 999999.0
            self._last_lap_time = 999999.0
            self._game_session_best_lap_time = 999999.0
            self._wall_of_fame.reset_session()

            # Load reference profile for track/car from disk
            self._load_reference_profile()

        if track_len > 0.0:
            self._track_length = track_len

        # Game's own authoritative player best-lap-time this session — see
        # _game_session_best_lap_time's docstring. Stateless: every packet
        # already carries the game's current best_lap_time directly, so just
        # take it as-is each time (no persisted min-tracking, no reset dance
        # to get right relative to the track-change block above).
        if 0.0 < best_lap < 999900.0:
            self._game_session_best_lap_time = best_lap

        # Authoritative calculation of elapsed lap time: current_et - lap_start_et
        if lap_start_et > 0.0 and current_et >= lap_start_et:
            time_into = current_et - lap_start_et
            self._last_lap_start_et = lap_start_et
        elif time_into_lap > 0.0:
            time_into = time_into_lap
            self._last_lap_start_et = current_et - time_into_lap
        elif self._local_lap_start_et > 0.0 and current_et >= self._local_lap_start_et:
            # CompactScoring-only fallback: neither lap_start_et nor time_into_lap
            # are available (those are FullScoringSession-only fields — CompactScoring
            # never carries them). Without this, a session running on CompactScoring
            # alone (FullScoringSession delayed/dropped/failing to resolve the player
            # vehicle, e.g. a full-grid multiplayer race) would freeze time_into at
            # 0.0 forever: no lap samples collected, no live delta, no expected status.
            time_into = current_et - self._local_lap_start_et
            self._last_lap_start_et = self._local_lap_start_et
        else:
            time_into = 0.0

        if raw_sec in (1, 2, 3):
            curr_sec = raw_sec
        elif raw_sec == 0:
            # isiMotor keeps ``sector == 0`` as the stable code for the whole "Sector 3"
            # phase after the S2 loop is crossed (observed for dozens of seconds in
            # delta_debug.log between the S2 cross at ``raw=0`` and the next finish
            # line). Do keep mapping it to 3; the sequential guard in
            # ``_handle_sector_transition`` below absorbs the transient echoes that a
            # stale FullScoring packet can inject while the car is still in S1/S2.
            curr_sec = 3
        else:
            # Out-of-range sample -> stay on the last coherent sector (no jumpy box).
            curr_sec = self._last_current_sector
        self._last_lap_flag = lap_flag

        # A wrap back to S1 is only valid when this scoring packet just completed a
        # lap (total_laps rolled over); an identical 3->1 sequence without a new lap
        # is a stale echo and must not snap the HUD back up to the S1 box.
        lap_crossed = (laps_comp > self._last_laps_completed)
        # Distinct from lap_crossed above (which _handle_sector_transition
        # needs exactly as-is): this specifically excludes the very first
        # packet ever received (self._last_laps_completed == -1 -> Case 0
        # "Initialization" in _handle_lap_transition, not a real Case 2
        # crossing with an actual previous lap's tail to worry about) — see
        # the stale-distance skip below, which must NOT also skip the
        # engine's very first sample.
        is_real_lap_crossing = self._last_laps_completed >= 0 and lap_crossed
        if is_real_lap_crossing:
            # This tick's OWN player_dist was captured by the caller (see
            # update_scoring_from_view) BEFORE we got here — for a
            # CompactScoring-only frame that's self._last_scoring_dist,
            # dead-reckoned from BEFORE the line crossing, so it's still
            # sitting near the OLD lap's tail (~track_length), not the new
            # lap's actual start (~0m). _collect_lap_sample already skips
            # this tick entirely below (is_real_lap_crossing gate), but
            # player_dist is ALSO used by _handle_sector_transition right
            # below (would spuriously see a near-finish-line position for
            # what's actually sector 1 of the new lap) and, more importantly,
            # is unconditionally written back into self._last_scoring_dist
            # at this function's tail — which used to silently UNDO
            # _handle_lap_transition's own wrap-on-crossing correction the
            # very same tick it ran, leaving every subsequent CompactScoring
            # tick this whole lap reading that same stale near-track-length
            # baseline instead of a corrected one (this, not just the single
            # first tick, is what a 816/819 or 867/869 monotonic-rejection
            # rate for an ENTIRE lap was actually coming from). Zeroing it
            # here, once, fixes every one of those downstream reads in a
            # single place instead of chasing each site separately.
            player_dist = 0.0
        self._handle_lap_transition(laps_comp, last_lap_time, lap_flag, in_garage, in_pits, current_et=current_et)
        self._handle_sector_transition(curr_sec, time_into=time_into, player_dist=player_dist, lap_crossed=lap_crossed)

        if in_garage:
            # In the garage, the current-sector tracking must not carry over
            # from before: the driver can re-emerge on any sector, so there's
            # no valid "last known position" to keep — reporting S2/S3 while
            # sitting in the garage is nonsense. Force back to a neutral S1
            # state on every packet while parked (not just on entry: a stale
            # raw sector value from the garage telemetry itself could
            # otherwise re-lock in on the very next call) and re-arm "not yet
            # primed" so the first real on-track sector report, once the
            # driver drives out, is accepted unconditionally instead of being
            # jitter-rejected against this reset (mirrors the track-change
            # reset above).
            if not self._last_in_garage:
                log_delta_debug(f"[GARAGE_ENTER] sector tracking reset to S1 (was S{self._sectors.last_current_sector})")
            self._sectors.reset_lap_capture(clear_primed=True)
            self._sectors.last_current_sector = 1

        is_flying_lap = (lap_flag == 2 and time_into > 0.0)
        self._scoring_ticks_this_lap += 1
        if is_flying_lap:
            self._flying_ticks_this_lap += 1
        # Live delta/expected keeps updating even when the CURRENT lap is
        # invalidated for record-keeping (lap_flag != 2, e.g. a track-limits
        # cut) — the driver already has separate visual/audio invalid-lap
        # indicators elsewhere; freezing/blanking the live number too would
        # just be a redundant, unwanted second indicator (requested
        # explicitly, more than once). Only genuinely delta-less situations
        # (pits, garage, no time context yet) stop the live projection.
        # Recording into the reference-lap spatial profile stays gated on
        # is_flying_lap below: an invalidated lap must never pollute a
        # future "all-time best" recording, that's a separate concern.
        is_delta_computable = (time_into > 0.0 and not in_garage and not in_pits)
        self._last_in_pits = in_pits
        self._last_in_garage = in_garage

        # Reset stint best if stopped in pits
        if in_pits and self._stint_best_lap_time != 999999.0 and self._last_speed_ms < 0.1:
            self._stint_best_profile = None
            self._stint_best_lap_time = 999999.0
            self._apply_active_profile()

        # Record reference samples only if valid flying lap in progress.
        # Skipped on the exact tick that just crossed the line (is_real_lap_crossing):
        # `player_dist` for this tick was captured by the caller BEFORE
        # _handle_lap_transition ran above, from a CompactScoring-only
        # frame's `self._last_scoring_dist` (see update_scoring_from_view) —
        # still possibly sitting at the just-finished lap's tail (near
        # _track_length) if no physics tick had a chance to wrap it yet (see
        # _handle_lap_transition's own wrap-on-crossing fix). _current_lap_
        # samples was JUST emptied, so that stale value would otherwise be
        # accepted unconditionally as the new lap's very first sample —
        # poisoning every genuinely low, correctly-increasing reading for
        # the rest of the lap against it (see [Incomplete track coverage]
        # rejections starting well past 0m, and near-total monotonic_rejects
        # counts). One skipped tick costs nothing against the hundreds
        # collected per lap; the very next tick reads a fresh, correctly-
        # wrapped value either way.
        if is_flying_lap and not is_real_lap_crossing:
            self._collect_lap_sample(
                time_into=time_into,
                player_dist=player_dist,
                speed_ms=self._last_speed_ms,
                throttle=self._last_throttle,
                brake=self._last_brake,
                steering=self._last_steering,
                gear=self._last_gear,
            )

        self._last_scoring_dist = player_dist
        self._last_scoring_time_into = time_into
        self._last_scoring_timestamp = now
        self._last_dist = player_dist

        # Update position and calculate delta whenever it's meaningful to
        # (see is_delta_computable above) — not gated on lap validity.
        if is_delta_computable:
            # Delta calculation with exact game telemetry
            self._calculate_delta(player_dist, time_into)
        else:
            # Pits / Garage / Pre-start: no flying lap delta. Reset the
            # smoother too — otherwise re-emerging on track would blend the
            # window with stale pre-stop samples.
            self._live_delta = 0.0
            self._reset_delta_smoother()
            self._last_checkpoint_idx = -1
            log_delta_debug(
                f"[SCORING_NOT_FLYING] dist={player_dist:.1f}m, t_into={time_into:.3f}s, flag={lap_flag}, "
                f"sec={curr_sec}, laps={laps_comp}, in_pits={in_pits}, in_garage={in_garage}"
            )
        # Note: When lap_flag == 2 (flying lap) but time_into is unavailable (e.g. CompactScoring),
        # do NOT overwrite _live_delta; let update_physics maintain continuous 100Hz delta.

    def update_physics(
        self,
        veh_speed_ms: Union[float, TelemInfo],
        throttle: float = 0.0,
        brake: float = 0.0,
        steering: float = 0.0,
        gear: int = 0,
        dt: float = 0.0,
        elapsed_time: float = 0.0,
        lap_start_et: float = 0.0,
        current_sector: int = 0,
    ) -> None:
        """
        Processes high frequency TelemInfoV01 / TelemInfo packet (50-100 Hz).
        Updates live delta at 100 Hz with continuous timer (elapsed_time - lap_start_et).
        """
        if isinstance(veh_speed_ms, TelemInfo):
            telem = veh_speed_ms
            veh_speed_ms = float(telem.speed_mps)
            throttle = float(telem.unfiltered_throttle)
            brake = float(telem.unfiltered_brake)
            steering = float(telem.unfiltered_steering)
            gear = int(telem.gear)
            dt = float(telem.delta_time)
            elapsed_time = float(telem.elapsed_time)
            lap_start_et = float(telem.lap_start_et)
            if current_sector == 0:
                current_sector = int(telem.current_sector)

        self._last_speed_ms = float(veh_speed_ms)
        self._last_throttle = throttle
        self._last_brake = brake
        self._last_steering = steering
        self._last_gear = gear

        # Always-on diagnostic counters (see their field docstring) — settle
        # whether TelemInfo is even reaching this method at its expected
        # rate, and whether the dead-reckoning below actually runs when it
        # does, without guessing from SAMPLE_REJECTED patterns alone.
        self._physics_ticks_this_lap += 1

        # High-frequency continuous distance dead reckoning integration (120Hz)
        if dt > 0.0 and self._last_speed_ms > 0.0 and self._last_scoring_dist >= 0.0:
            self._physics_dead_reckon_ticks_this_lap += 1
            self._last_scoring_dist += self._last_speed_ms * dt
            if self._track_length > 0.0 and self._last_scoring_dist >= self._track_length:
                self._last_scoring_dist -= self._track_length

        effective_start_et = lap_start_et if lap_start_et > 0.0 else self._last_lap_start_et
        if effective_start_et > 0.0 and elapsed_time >= effective_start_et:
            phys_time_into = elapsed_time - effective_start_et
        else:
            phys_time_into = self._last_scoring_time_into

        if current_sector > 0:
            self._handle_sector_transition(current_sector, time_into=phys_time_into, player_dist=self._last_scoring_dist)

        # Same gating as _apply_scoring_update's is_delta_computable: keep the
        # live delta updating at 100Hz even during an invalidated lap, only
        # stop it in pits/garage — see that docstring.
        if not self._last_in_pits and not self._last_in_garage and self._last_scoring_dist >= 0.0:
            if phys_time_into > 0.0:
                self._calculate_delta(self._last_scoring_dist, phys_time_into)

    def _get_ref_time_at_dist(self, dist: float) -> Optional[float]:
        """Returns interpolated reference time at a given distance on active profile."""
        if not self.has_reference or self._ref_t_grid is None or self._ref_num_points < 2 or dist < 0.0:
            return None
        step = self._ref_spatial_step if self._ref_spatial_step > 0.0 else 1.0
        idx_float = dist / step
        idx_floor = int(idx_float)
        if idx_floor < 0:
            return self._ref_t_grid[0]
        elif idx_floor >= self._ref_num_points - 1:
            return self._ref_t_grid[-1]
        else:
            frac = idx_float - idx_floor
            t1 = self._ref_t_grid[idx_floor]
            t2 = self._ref_t_grid[idx_floor + 1]
            return t1 + frac * (t2 - t1)

    def _reset_delta_smoother(self) -> None:
        """Clears the smoothed-delta moving-average window and its derived
        sector decomposition. Called at every point that discontinuities the
        live delta (no reference, ref-lookup failure, extreme clamp,
        finish-line freeze just ending, active-profile loss, track/vehicle
        change, lap/session reset, pits/garage) — otherwise the window would
        blend samples across the discontinuity."""
        self._live_delta_smoother.reset()
        self._smoothed_live_delta = 0.0
        self._smoothed_sector1_delta = 0.0
        self._smoothed_sector2_delta = 0.0
        self._smoothed_sector3_delta = 0.0

    def _calculate_delta(self, player_dist: float, time_into: float) -> None:
        """Calculates live delta and per-sector deltas from distance and time."""
        # Finish-line freeze just ended -> the window would otherwise blend
        # the previous lap's tail samples into the new lap's first live
        # readings. Centralizes what used to be 4 separate per-widget/
        # per-sector-box resets in the Cockpit HUD plugin.
        is_freeze_now = self.is_lap_freeze_active
        if not is_freeze_now and self._smoother_was_freeze:
            self._live_delta_smoother.reset()
        self._smoother_was_freeze = is_freeze_now

        if not self.has_reference or time_into <= 0.0 or player_dist < 0.0:
            self._live_delta = 0.0
            self._reset_delta_smoother()
            self._sectors.clear_deltas()
            log_delta_debug(
                f"[DELTA_NO_REF] dist={player_dist:.1f}m, t_into={time_into:.3f}s, has_ref={self.has_reference}, "
                f"flag={self._last_lap_flag}, mode={self._ref_mode.value}"
            )
            return

        ref_time = self._get_ref_time_at_dist(player_dist)
        if ref_time is None:
            self._live_delta = 0.0
            self._reset_delta_smoother()
            self._sectors.clear_deltas()
            log_delta_debug(
                f"[DELTA_REF_LOOKUP_FAIL] dist={player_dist:.1f}m, t_into={time_into:.3f}s, "
                f"ref_num_points={self._ref_num_points}"
            )
            return

        raw_delta = time_into - ref_time

        # Clamp extreme deltas to +/- 999.0s
        if abs(raw_delta) < 999.0:
            self._live_delta = raw_delta
            self._smoothed_live_delta = self._live_delta_smoother.sample(raw_delta, time_into)
        else:
            self._live_delta = 0.0
            self._reset_delta_smoother()

        # Save delta for freeze maintenance
        self._frozen_checkpoint_delta = self._live_delta

        # Dynamic calculation of sector deltas against ACTIVE profile — raw
        # (mutating, existing behaviour) and smoothed (pure, additive; feeds
        # time_status_smoothed only). See SectorEngine.compute_split_deltas_pure
        # for why decomposing the already-smoothed live_delta is equivalent to
        # smoothing each sector's delta independently.
        self._sectors.compute_split_deltas(self._live_delta, self._get_ref_time_at_dist)
        (
            self._smoothed_sector1_delta,
            self._smoothed_sector2_delta,
            self._smoothed_sector3_delta,
        ) = self._sectors.compute_split_deltas_pure(self._smoothed_live_delta, self._get_ref_time_at_dist)

        log_delta_debug(
            f"[DELTA_CALC] dist={player_dist:.1f}m, t_into={time_into:.3f}s, ref_t={ref_time:.3f}s, "
            f"raw_delta={raw_delta:+.3f}s, live_delta={self._live_delta:+.3f}s, "
            f"smoothed_delta={self._smoothed_live_delta:+.3f}s, "
            f"S1={self._sector1_delta:+.3f}s, S2={self._sector2_delta:+.3f}s, S3={self._sector3_delta:+.3f}s, "
            f"mode={self._ref_mode.value}, ref_lap_time={self._ref_lap_time:.3f}s"
        )

    def _resample_spatial_grid(
        self,
        clean_samples: List[Tuple[float, ...]],
        spatial_step: float = 1.0,
    ) -> Tuple[List[float], List[float], List[float], List[float], List[float], List[int], int]:
        """
        SLAP Helper: Builds resampled spatial profile meter-by-meter on uniform grid.
        Interpolates: time, speed, throttle, brake, steering, gear.
        """
        import bisect
        track_dist = clean_samples[-1][0]
        num_points = int(track_dist / spatial_step) + 1

        t_grid: List[float] = []
        speed_grid: List[float] = []
        throttle_grid: List[float] = []
        brake_grid: List[float] = []
        steering_grid: List[float] = []
        gear_grid: List[int] = []

        d_keys = [s[0] for s in clean_samples]

        def _get_val(sample_tuple, idx, default=0.0):
            return sample_tuple[idx] if len(sample_tuple) > idx else default

        def _get_gear_val(sample_tuple, idx, default=0):
            return int(round(sample_tuple[idx])) if len(sample_tuple) > idx else default

        for i in range(num_points):
            target_d = i * spatial_step
            idx = bisect.bisect_left(d_keys, target_d)

            if idx <= 0:
                s = clean_samples[0]
                t_grid.append(s[1])
                speed_grid.append(_get_val(s, 2, 0.0))
                throttle_grid.append(_get_val(s, 3, 0.0))
                brake_grid.append(_get_val(s, 4, 0.0))
                steering_grid.append(_get_val(s, 5, 0.0))
                gear_grid.append(_get_gear_val(s, 6, 0))
            elif idx >= len(clean_samples):
                s = clean_samples[-1]
                t_grid.append(s[1])
                speed_grid.append(_get_val(s, 2, 0.0))
                throttle_grid.append(_get_val(s, 3, 0.0))
                brake_grid.append(_get_val(s, 4, 0.0))
                steering_grid.append(_get_val(s, 5, 0.0))
                gear_grid.append(_get_gear_val(s, 6, 0))
            else:
                s1 = clean_samples[idx - 1]
                s2 = clean_samples[idx]
                d1, t1 = s1[0], s1[1]
                d2, t2 = s2[0], s2[1]
                frac = (target_d - d1) / (d2 - d1) if d2 > d1 else 0.0

                t_grid.append(t1 + frac * (t2 - t1))

                v1, v2 = _get_val(s1, 2, 0.0), _get_val(s2, 2, 0.0)
                speed_grid.append(v1 + frac * (v2 - v1))

                thr1, thr2 = _get_val(s1, 3, 0.0), _get_val(s2, 3, 0.0)
                throttle_grid.append(thr1 + frac * (thr2 - thr1))

                brk1, brk2 = _get_val(s1, 4, 0.0), _get_val(s2, 4, 0.0)
                brake_grid.append(brk1 + frac * (brk2 - brk1))

                str1, str2 = _get_val(s1, 5, 0.0), _get_val(s2, 5, 0.0)
                steering_grid.append(str1 + frac * (str2 - str1))

                g1, g2 = _get_gear_val(s1, 6, 0), _get_gear_val(s2, 6, 0)
                gear_grid.append(g1 if frac < 0.5 else g2)

        return t_grid, speed_grid, throttle_grid, brake_grid, steering_grid, gear_grid, num_points

    def _finalize_completed_lap(
        self,
        lap_time: float,
        lap_flag: int,
        in_garage: bool,
        in_pits: bool,
    ) -> None:
        """Validates and records completed lap (SLAP: high-level orchestration)."""
        # 1. Only laps with lap_flag == 2 (valid and timed) can be saved
        if lap_flag != 2:
            logger.info(f"[DeltaEngine] Lap rejected: Not a valid timed lap (lap_flag={lap_flag})")
            print(f"[DeltaEngine] Lap not saved: Invalid game status / Invalid lap / Out-lap (lap_flag={lap_flag})", flush=True)
            log_delta_debug(f"[LAP_REJECTED] Invalid game status (lap_flag={lap_flag})")
            return

        # 2. Official lap time from game must be strictly positive (> 0)
        # If mLastLapTime <= 0 (e.g. -1.0 on Out-lap), REJECT
        if lap_time <= 0.0:
            logger.info(f"[DeltaEngine] Lap rejected: Invalid official lap time ({lap_time:.3f}s)")
            print(f"[DeltaEngine] Lap not saved: No official timed lap time ({lap_time:.3f}s, Out-lap)", flush=True)
            log_delta_debug(f"[LAP_REJECTED] No official timed lap time (lap_time={lap_time:.3f}s)")
            return

        sample_count = len(self._current_lap_samples)
        # scoring_ticks/flying_ticks are always-on diagnostic counters (no
        # delta_debug.log config gate — see their field docstring): how many
        # scoring packets reached DeltaEngine this lap, and how many passed
        # the is_flying_lap gate. Distinguishes "packets never arrived"
        # (both low) from "arrived but time_into stayed 0" (flying_ticks low,
        # scoring_ticks not) from "flying but _collect_lap_sample's own
        # filters rejected them" (both high, samples still low) on this same
        # line, without needing a second reproduction. dist_span/
        # monotonic_rejects go one level deeper into that last case: a tiny
        # dist_span despite many flying_ticks means player_dist itself barely
        # moved between scoring ticks (dead-reckoning stalled), not just
        # noisy backwards jitter (which would show a wide span AND a high
        # monotonic_rejects count). physics_ticks/dead_reckon_ticks settle
        # WHY player_dist stalls in the first place: physics_ticks close to
        # scoring_ticks (instead of ~10x higher, matching TelemInfo's own
        # 50-120Hz vs CompactScoring's ~10Hz) means TelemInfo isn't reaching
        # update_physics() at its expected rate at all; physics_ticks healthy
        # but dead_reckon_ticks much lower means dt/speed are the problem
        # instead (see update_physics's own dead-reckoning guard).
        dist_min = self._sample_dist_min_this_lap
        dist_max = self._sample_dist_max_this_lap
        dist_span = (dist_max - dist_min) if (dist_min is not None and dist_max is not None) else None
        logger.info(
            f"[DeltaEngine] Lap completed: lap_time={lap_time:.3f}s, flag={lap_flag}, samples={sample_count}, "
            f"scoring_ticks={self._scoring_ticks_this_lap}, flying_ticks={self._flying_ticks_this_lap}, "
            f"dist_span={dist_span}, monotonic_rejects={self._sample_monotonic_rejects_this_lap}, "
            f"physics_ticks={self._physics_ticks_this_lap}, dead_reckon_ticks={self._physics_dead_reckon_ticks_this_lap}"
        )
        print(
            f"[DeltaEngine] Lap completed: {lap_time:.3f}s (flag={lap_flag}, samples={sample_count}, "
            f"scoring_ticks={self._scoring_ticks_this_lap}, flying_ticks={self._flying_ticks_this_lap}, "
            f"dist_span={dist_span}, monotonic_rejects={self._sample_monotonic_rejects_this_lap}, "
            f"physics_ticks={self._physics_ticks_this_lap}, dead_reckon_ticks={self._physics_dead_reckon_ticks_this_lap})",
            flush=True,
        )

        # 3. Physical plausibility check (minimum time according to track length, max ~400 km/h)
        if self._track_length > 500.0:
            min_possible_time = self._track_length / 110.0  # 110 m/s = 396 km/h max average speed
            if lap_time < min_possible_time:
                logger.warning(f"[DeltaEngine] Lap rejected: Impossible lap time ({lap_time:.3f}s < min {min_possible_time:.1f}s)")
                print(f"[DeltaEngine] Lap not saved: Physically impossible lap time ({lap_time:.3f}s for {self._track_length:.0f}m)", flush=True)
                log_delta_debug(f"[LAP_REJECTED] Impossible time ({lap_time:.3f}s < min {min_possible_time:.1f}s)")
                return
        elif lap_time <= 15.0:
            logger.info(f"[DeltaEngine] Lap rejected: Lap time too short ({lap_time:.3f}s)")
            log_delta_debug(f"[LAP_REJECTED] Lap time too short ({lap_time:.3f}s)")
            return

        if sample_count < 10:
            logger.info(f"[DeltaEngine] Lap rejected: Insufficient samples ({sample_count})")
            print(f"[DeltaEngine] Lap not saved: Insufficient samples ({sample_count} pts)", flush=True)
            log_delta_debug(f"[LAP_REJECTED] Insufficient samples ({sample_count} pts)")
            return

        # Filter list to guarantee strict monotonicity of distances
        clean_samples: List[Tuple[float, ...]] = []
        last_d = -1.0
        for sample in self._current_lap_samples:
            d = sample[0]
            if d > last_d:
                clean_samples.append(sample)
                last_d = d

        if len(clean_samples) < 10 or clean_samples[-1][0] <= 0.0:
            print(f"[DeltaEngine] Lap not saved: Invalid filtered samples ({len(clean_samples)} pts)", flush=True)
            log_delta_debug(f"[LAP_REJECTED] Invalid filtered samples ({len(clean_samples)} pts)")
            return

        # 4. Verification of full track spatial coverage
        if self._track_length > 500.0:
            first_d = clean_samples[0][0]
            last_d = clean_samples[-1][0]
            if first_d > 250.0 or last_d < (self._track_length - 350.0):
                print(f"[DeltaEngine] Lap not saved: Incomplete track coverage ({first_d:.0f}m -> {last_d:.0f}m / {self._track_length:.0f}m)", flush=True)
                log_delta_debug(f"[LAP_REJECTED] Incomplete coverage ({first_d:.0f}m -> {last_d:.0f}m / {self._track_length:.0f}m)")
                return

        # Automatic extrapolation of start point (0.0m, 0.0s) if missing
        if clean_samples[0][0] > 0.0:
            first_s = clean_samples[0]
            clean_samples.insert(0, (
                0.0,
                0.0,
                first_s[2] if len(first_s) > 2 else 0.0,
                first_s[3] if len(first_s) > 3 else 0.0,
                first_s[4] if len(first_s) > 4 else 0.0,
                first_s[5] if len(first_s) > 5 else 0.0,
                first_s[6] if len(first_s) > 6 else 0,
            ))

        # Automatic extrapolation of end point (track_length, lap_time) if missing
        if self._track_length > 0.0 and clean_samples[-1][0] < self._track_length:
            last_s = clean_samples[-1]
            clean_samples.append((
                self._track_length,
                lap_time,
                last_s[2] if len(last_s) > 2 else 0.0,
                last_s[3] if len(last_s) > 3 else 0.0,
                last_s[4] if len(last_s) > 4 else 0.0,
                last_s[5] if len(last_s) > 5 else 0.0,
                last_s[6] if len(last_s) > 6 else 0,
            ))

        spatial_step = 1.0
        t_grid, speed_grid, throttle_grid, brake_grid, steering_grid, gear_grid, num_points = self._resample_spatial_grid(
            clean_samples,
            spatial_step=spatial_step,
        )

        # Determine filepaths (telemetry .json and marks .marks.json)
        filepath = self._get_profile_filepath()
        marks_path = get_marks_filepath(filepath) if filepath else None

        # Keep existing annotations ONLY if they belong to THIS track
        existing_annotations: List[TrackAnnotation] = []
        if self._current_profile and self._current_profile.annotations:
            prof_track = self._current_profile.track_name
            if not prof_track or clean_name_identifier(prof_track) == clean_name_identifier(self._track_name):
                existing_annotations = list(self._current_profile.annotations)

        # If no annotation in memory, rigorously search disk for THIS track
        if not existing_annotations:
            disk_marks_path = find_marks_filepath_for_track(
                self._track_name,
                self._vehicle_class,
                self._vehicle_name,
                base_dir=_REF_LAPS_DIR,
            )
            if disk_marks_path and disk_marks_path.exists():
                temp_prof = ReferenceLapProfile(track_name=self._track_name)
                temp_prof.load_marks_from_file(disk_marks_path)
                existing_annotations = temp_prof.annotations

        # Determine positions of timing loops S1 and S2
        s1_dist = self._player_s1_dist if self._player_s1_dist > 0.0 else (
            self._current_profile.sector_1_dist if (self._current_profile and self._current_profile.sector_1_dist > 0.0) else 0.0
        )
        s2_dist = self._player_s2_dist if self._player_s2_dist > 0.0 else (
            self._current_profile.sector_2_dist if (self._current_profile and self._current_profile.sector_2_dist > 0.0) else 0.0
        )
        s1_time = self._player_s1_time if self._player_s1_time > 0.0 else (
            self._current_profile.sector_1_time if (self._current_profile and self._current_profile.sector_1_time > 0.0) else 0.0
        )
        s2_time = self._player_s2_time if self._player_s2_time > 0.0 else (
            self._current_profile.sector_2_time if (self._current_profile and self._current_profile.sector_2_time > 0.0) else 0.0
        )

        # Build full profile of completed lap
        effective_len = self._track_length if self._track_length > 0.0 else clean_samples[-1][0]
        profile = ReferenceLapProfile(
            track_name=self._track_name,
            vehicle_name=self._vehicle_name,
            vehicle_class=self._vehicle_class,
            lap_time=lap_time,
            track_length=effective_len,
            spatial_step=spatial_step,
            num_points=num_points,
            t_grid=t_grid,
            speed_grid=speed_grid,
            gear_grid=gear_grid,
            throttle_grid=throttle_grid,
            brake_grid=brake_grid,
            steering_grid=steering_grid,
            sector_1_dist=s1_dist,
            sector_2_dist=s2_dist,
            sector_1_time=s1_time,
            sector_2_time=s2_time,
            annotations=existing_annotations,
        )

        if marks_path:
            profile.set_marks_filepath(marks_path)

        # Feed WallOfFameTimes (my-session-best / all-time-best) in parallel —
        # see WallOfFameEngine docstring. Same lap, decomposed the same way as
        # the legacy fields below (_individual_sector_splits).
        s1, s2, s3 = _individual_sector_splits(profile)
        self._wall_of_fame.update_from_lap_completed(
            TimeLap(sector1=s1, sector2=s2, sector3=s3, total=lap_time), is_valid=True,
        )

        # Update Multi-Reference hierarchy
        self._last_lap_profile = profile
        self._last_lap_time = lap_time

        if self._stint_best_profile is None or lap_time < self._stint_best_lap_time:
            self._stint_best_profile = profile
            self._stint_best_lap_time = lap_time

        if self._session_best_profile is None or lap_time < self._session_best_lap_time:
            self._session_best_profile = profile
            self._session_best_lap_time = lap_time

        # Update All-Time Best (disk)
        if self._all_time_best_profile is None or lap_time < self._all_time_best_lap_time:
            self._all_time_best_profile = profile
            self._all_time_best_lap_time = lap_time
            logger.info(f"[DeltaEngine] New All-Time Best Reference Lap Recorded! Time: {lap_time:.3f}s ({num_points} grid points, {len(existing_annotations)} marks)")
            print(f"[DeltaEngine] ★ NEW ALL-TIME BEST REFERENCE LAP: {lap_time:.3f}s on '{self._track_name}' ({len(existing_annotations)} annotations)", flush=True)
            self._save_reference_profile()
        else:
            logger.info(f"[DeltaEngine] Valid lap ({lap_time:.3f}s) -> Stored in Last/Session/Stint references.")
            print(f"[DeltaEngine] Valid lap ({lap_time:.3f}s) saved in session (All-time best: {self._all_time_best_lap_time:.3f}s)", flush=True)

        log_delta_debug(
            f"[LAP_FINALIZED] lap_time={lap_time:.3f}s, flag={lap_flag}, samples={len(clean_samples)}, "
            f"grid_points={num_points}, AllTimeBest={self._all_time_best_lap_time:.3f}s, "
            f"SessionBest={self._session_best_lap_time:.3f}s, StintBest={self._stint_best_lap_time:.3f}s, "
            f"LastLap={self._last_lap_time:.3f}s"
        )

        # Apply active reference according to configured mode
        self._apply_active_profile()

    def _sync_metadata(self) -> None:
        """Pushes this session's current combo identity + configured ref-laps
        directory into MetadataEngine — the single owner of combo->filename
        naming (SRP: this class does delta/timing math, not file naming).
        Cheap (string ops only, no I/O): safe to call before every filepath
        lookup below rather than only on a detected combo change, so it stays
        correct even for callers (tests included) that poke _track_name/
        _vehicle_class/_vehicle_name directly instead of going through
        _apply_scoring_update()'s combo-change block."""
        self._metadata.update(self._track_name, self._vehicle_class, self._vehicle_name, base_dir=_REF_LAPS_DIR)

    def _get_profile_filepath(self) -> Optional[Path]:
        """Returns JSON filepath for (track, vehicle_class/vehicle)."""
        self._sync_metadata()
        return self._metadata.get_profile_filepath()

    def _save_reference_profile(self) -> None:
        """Automatically saves all-time best reference lap telemetry to disk."""
        filepath = self._get_profile_filepath()
        if not filepath or self._all_time_best_profile is None:
            return
        ok = self._all_time_best_profile.save_telemetry_to_file(filepath)
        if ok:
            print(f"[DeltaEngine] File saved to disk: {filepath}", flush=True)
            log_delta_debug(f"[REF_SAVE_OK] file='{filepath.name}'")
        else:
            print(f"[DeltaEngine] ERROR: Unable to write reference file: {filepath}", flush=True)
            log_delta_debug(f"[REF_SAVE_ERROR] file='{filepath}'")

    def _load_reference_profile(self) -> None:
        """Attempts to load reference profile and marks saved to disk for track/car."""
        filepath = self._get_profile_filepath()
        if not filepath or not filepath.exists():
            filepath = find_telemetry_filepath_for_track(
                self._track_name,
                self._vehicle_class,
                self._vehicle_name,
                base_dir=_REF_LAPS_DIR,
            )

        marks_filepath = find_marks_filepath_for_track(
            self._track_name,
            self._vehicle_class,
            self._vehicle_name,
            base_dir=_REF_LAPS_DIR,
        )

        # 1. Ideal case: Complete telemetry existing for this track
        if filepath and filepath.exists():
            loaded = ReferenceLapProfile.load_from_file(filepath)
            if loaded and loaded.t_grid and len(loaded.t_grid) > 1:
                self._all_time_best_profile = loaded
                self._all_time_best_lap_time = loaded.lap_time
                self._wall_of_fame.load_all_time_from_disk(loaded)
                self._apply_active_profile()
                logger.info(f"[DeltaEngine] Loaded reference profile from {filepath.name} ({self._ref_lap_time:.3f}s, {len(loaded.annotations)} annotations)")
                print(f"[DeltaEngine] Reference lap and marks loaded: {filepath.name} ({self._ref_lap_time:.3f}s, {len(loaded.annotations)} annotations)", flush=True)
                log_delta_debug(
                    f"[REF_LOAD_FULL] file='{filepath.name}', lap_time={loaded.lap_time:.3f}s, "
                    f"points={loaded.num_points}, marks={len(loaded.annotations)}"
                )
                return

        # 2. Case without timed lap but with marks file (.marks.json) existing for track
        if marks_filepath and marks_filepath.exists():
            # Race guard: if we already hold a *valid* all-time (telemetry) reference and
            # the JSON merely appears marks-only (e.g. mid-write / transient partial read),
            # never replace the good profile with a 999999s placeholder.
            if self._all_time_best_lap_time < 999900.0 and self._all_time_best_lap_time > 0.0:
                logger.info(
                    f"[DeltaEngine] Kept valid all-time ({self._all_time_best_lap_time:.3f}s) while "
                    f"{filepath.name} read marks-only (likely partial write); flags loaded from "
                    f"{marks_filepath.name}."
                )
                log_delta_debug(
                    f"[REF_LOAD_MARKS_KEEP_BEST] file='{filepath.name}', kept={self._all_time_best_lap_time:.3f}s"
                )
                return
            placeholder = ReferenceLapProfile(
                track_name=self._track_name,
                vehicle_name=self._vehicle_name,
                vehicle_class=self._vehicle_class,
                track_length=self._track_length,
            )
            placeholder.set_marks_filepath(marks_filepath)
            placeholder.load_marks_from_file(marks_filepath)
            self._all_time_best_profile = placeholder
            self._all_time_best_lap_time = 999999.0
            self._wall_of_fame.load_all_time_from_disk(None)
            self._apply_active_profile()
            print(f"[DeltaEngine] Track marks loaded for '{self._track_name}': {marks_filepath.name} ({len(placeholder.annotations)} annotations). Waiting for 1st timed lap.", flush=True)
            log_delta_debug(f"[REF_LOAD_MARKS_ONLY] marks_file='{marks_filepath.name}', marks={len(placeholder.annotations)}")
            return

        # 3. No file found for track: pristine state (0 annotations, no leak from other tracks)
        self._all_time_best_profile = None
        self._all_time_best_lap_time = 999999.0
        self._wall_of_fame.load_all_time_from_disk(None)
        self._apply_active_profile()
        fname = filepath.name if filepath else "none"
        print(f"[DeltaEngine] No reference lap or marks for '{self._track_name}' ({fname}). Waiting for 1st flying lap.", flush=True)
        log_delta_debug(f"[REF_LOAD_NONE] track='{self._track_name}', searched_file='{fname}'")

    @property
    def live_delta(self) -> float:
        """Raw live delta."""
        return self._live_delta

    @property
    def display_delta(self) -> float:
        """Delta for HUD display (frozen for freeze_duration seconds after crossing line)."""
        if time.time() < self._freeze_delta_until:
            return self._frozen_final_delta
        return self._live_delta

    @property
    def smoothed_live_delta(self) -> float:
        """Live delta smoothed over delta_smoothing_window_s seconds of game
        time — see time_status_smoothed for the full consistent (value +
        colour + PR) projection built from this."""
        return self._smoothed_live_delta

    @property
    def smoothed_display_delta(self) -> float:
        """Smoothed delta for HUD display — mirrors display_delta's freeze
        window, reusing the same frozen constant (a completed lap's delta is
        already a captured fact; smoothing it further has no meaning)."""
        if time.time() < self._freeze_delta_until:
            return self._frozen_final_delta
        return self._smoothed_live_delta

    @property
    def is_lap_freeze_active(self) -> bool:
        """Returns True if lap time display is frozen after crossing line."""
        return time.time() < self._freeze_lap_until and self._last_completed_lap_time > 0.0

    @property
    def last_completed_lap_time(self) -> float:
        """Returns last completed lap time in seconds."""
        return self._last_completed_lap_time

    @property
    def last_completed_lap_time_str(self) -> str:
        """Returns last completed lap time formatted as 'MM:ss.mmm'."""
        if self._last_completed_lap_time > 0.0:
            return format_lap_time(self._last_completed_lap_time)
        return "--:--.---"

    @property
    def last_completed_lap_is_pr(self) -> bool:
        """True when the just-completed lap beat my all-time best ("PR")."""
        return self._last_completed_lap_is_pr

    @property
    def last_completed_lap_status(self) -> LapColorStatus:
        """Returns color status of last completed lap ('purple', 'green', 'yellow', 'invalid', 'default')."""
        return self._last_completed_lap_status

    @property
    def estimated_lap_time(self) -> float:
        """Estimated final lap time projection (ref_lap_time + live_delta)."""
        if self.has_reference and self._ref_lap_time < 999999.0:
            return max(0.0, self._ref_lap_time + self._live_delta)
        return 0.0

    @property
    def estimated_lap_time_str(self) -> str:
        """Estimated final lap time projection formatted as 'MM:ss.mmm'."""
        projected_time = self.estimated_lap_time
        if projected_time > 0.0:
            return format_lap_time(projected_time)
        return "--:--.---"

    @property
    def smoothed_estimated_lap_time(self) -> float:
        """Estimated final lap time projection built from smoothed_live_delta."""
        if self.has_reference and self._ref_lap_time < 999999.0:
            return max(0.0, self._ref_lap_time + self._smoothed_live_delta)
        return 0.0

    @property
    def _ever_lap_bound(self) -> Optional[float]:
        return self._all_time_best_lap_time if (self._all_time_best_lap_time or 0.0) < 999900.0 else None

    @property
    def _session_lap_bound(self) -> Optional[float]:
        """My best lap time this session — the tighter of the game's own
        authoritative report and our own successfully-captured recording (see
        _game_session_best_lap_time's docstring: the game's value is known as
        soon as a timed lap is set, even when our own capture pipeline missed
        it, so it must never be blank just because ours is)."""
        game = self._game_session_best_lap_time if (self._game_session_best_lap_time or 0.0) < 999900.0 else None
        ours = self._session_best_lap_time if (self._session_best_lap_time or 0.0) < 999900.0 else None
        if game is not None and ours is not None:
            return min(game, ours)
        return game if game is not None else ours

    @property
    def _paddock_lap_bound(self) -> Optional[float]:
        return self._paddock_best_lap if (self._paddock_known and (self._paddock_best_lap or 0.0) < 999900.0) else None

    @property
    def expected_lap_status(self) -> ExpectedStatus:
        """Unified colour of the expected lap time — SESSION-scoped only
        (purple/green/yellow/white): never pink. All-time-best ("ever") is not
        a colour tier here; see ``expected_lap_is_pr`` for that comparison.

        Compares the *projection* estimated_lap_time to the two references
        the engine tracks this session:
          paddock → best other-car lap this session (_paddock_best_lap),
          session → _session_best_lap_time (my session best).
        First valid match wins; white when no usable reference exists yet.
        """
        from .sector_colors import expected_status
        invalid = not self.has_reference
        return expected_status(
            self.estimated_lap_time,
            ever=None,
            paddock=self._paddock_lap_bound,
            session=self._session_lap_bound,
            invalid=invalid,
            source="delta.expected",
        )

    @property
    def expected_lap_is_pr(self) -> bool:
        """True when the projected lap time already beats my all-time best
        ("PR" — personal record). Purely informational; never drives colour.

        Strictly-better-than (not "or equal"): in ALL_TIME_BEST mode,
        current_profile IS all_time_best_profile, so the projection at
        live_delta == 0.0 (e.g. right at the start of every lap, before any
        input has actually diverged from the reference) is EXACTLY equal to
        ``ever`` — an inclusive ``<=`` there would flag "PR" by default before
        the driver has proven anything. Requiring a real epsilon margin below
        ``ever`` means the flag only lights up once genuinely running ahead.
        """
        ever = self._ever_lap_bound
        if ever is None or not self.has_reference:
            return False
        v = self.estimated_lap_time
        return 0.0 < v and v < ever - 0.001

    # ------------------------------------------------------------ expected sectors
    @property
    def _paddock_sector_splits(self) -> Tuple[float, float, float]:
        """Standalone S1/S2/S3 of the best OTHER car this session, decomposed
        from the cumulative loop clocks tracked in ``_update_scoring_core``."""
        if not self._paddock_known:
            return 0.0, 0.0, 0.0
        cs1 = float(self._paddock_cum_s1 or 0.0)
        cs2 = float(self._paddock_cum_s2 or 0.0)
        lap = float(self._paddock_best_lap or 0.0)
        s1 = cs1 if 0.0 < cs1 < 999900.0 else 0.0
        s2 = (cs2 - cs1) if (0.0 < cs1 < cs2 < 999900.0) else 0.0
        s3 = (lap - cs2) if (0.0 < cs2 < lap < 999900.0) else 0.0
        return s1, s2, s3

    def _expected_sector(self, idx: int) -> Tuple[str, ExpectedStatus, bool]:
        """Projected time/colour/PR-flag for sector ``idx`` (1/2/3).

        Mirrors ``estimated_lap_time`` (reference + live delta) at sector
        granularity: ``expected = reference_split(idx) + splitN_delta``. While
        a sector hasn't been reached yet its delta is 0, so this reads as the
        *target* split; once inside it, it live-updates; once past it, it's
        frozen at the actual result — same rule as the EXPECTED lap value.

        Colour is SESSION-scoped only (purple/green/yellow/white) — never
        pink; beating my all-time-best split for this sector is reported via
        the returned ``is_pr`` flag instead (see the module docstring on the
        "no pink, PR flag" convention this plugin uses).
        """
        from .sector_colors import expected_status
        i = idx - 1
        ref = _individual_sector_splits(self._current_profile)[i]
        if ref <= 0.0 or not self.has_reference:
            return "--", ExpectedStatus.WHITE, False
        delta = (self._sector1_delta, self._sector2_delta, self._sector3_delta)[i]
        expected = max(0.0, ref + delta)
        ever = _individual_sector_splits(self._all_time_best_profile)[i] or None
        session = _individual_sector_splits(self._session_best_profile)[i] or None
        paddock = self._paddock_sector_splits[i] or None
        status = expected_status(
            expected, ever=None, paddock=paddock, session=session, invalid=False,
            source="delta.expected_sector",
        )
        # Strictly-better-than (not "or equal") — same reasoning as
        # expected_lap_is_pr: in ALL_TIME_BEST mode `ref` and `ever` are the
        # same profile, so at delta == 0.0 (sector not reached yet) expected
        # == ever exactly; an inclusive "<=" would flag PR by default.
        is_pr = ever is not None and 0.0 < expected < ever - 0.001
        return sector_time_display_str(expected), status, is_pr

    @property
    def expected_sector1_time(self) -> str:
        return self._expected_sector(1)[0]

    @property
    def expected_sector1_status(self) -> ExpectedStatus:
        return self._expected_sector(1)[1]

    @property
    def expected_sector1_is_pr(self) -> bool:
        return self._expected_sector(1)[2]

    @property
    def expected_sector2_time(self) -> str:
        return self._expected_sector(2)[0]

    @property
    def expected_sector2_status(self) -> ExpectedStatus:
        return self._expected_sector(2)[1]

    @property
    def expected_sector2_is_pr(self) -> bool:
        return self._expected_sector(2)[2]

    @property
    def expected_sector3_time(self) -> str:
        return self._expected_sector(3)[0]

    @property
    def expected_sector3_status(self) -> ExpectedStatus:
        return self._expected_sector(3)[1]

    @property
    def expected_sector3_is_pr(self) -> bool:
        return self._expected_sector(3)[2]

    # ------------------------------------------------------------ reference times
    @property
    def my_session_best_lap_time_str(self) -> str:
        """My best lap this session ('mon meilleur de la session')."""
        b = self._session_lap_bound
        return format_lap_time(b) if b is not None else "--:--.---"

    @property
    def session_best_lap_time_str(self) -> str:
        """Best lap of the session set by another car ('le meilleur de la session')."""
        b = self._paddock_lap_bound
        return format_lap_time(b) if b is not None else "--:--.---"

    # NOTE: no my_all_time_best_lap_time_str property here — it's a static
    # value read straight from a JSON file, not live telemetry, so it doesn't
    # belong on the per-packet LapDeltaPacket/VehicleSensors path. Consumers
    # read it from VehicleSensors.reference_profile.lap_time instead (pushed
    # only when the profile actually changes — see ReferenceLapManager.
    # _push_reference_profile_view). _ever_lap_bound below stays: it's a live
    # comparison used by the PR-flag colour logic, a different concern.

    @property
    def sector1_delta(self) -> float:
        return self._sector1_delta

    @property
    def sector2_delta(self) -> float:
        return self._sector2_delta

    @property
    def sector3_delta(self) -> float:
        return self._sector3_delta

    @property
    def current_sector(self) -> int:
        """Returns current sector index (1, 2, or 3)."""
        return self._last_current_sector

    @property
    def sector1_time_str(self) -> str:
        """Display string ('MM:ss.mmm' or '--') for the S1 box — see _refresh_display_sector_times."""
        return self._last_sector1_time

    @property
    def sector1_status(self) -> SplitStatus:
        """Display colour ('default'/'green'/'purple'/'pink'...) for the S1 box."""
        return self._last_sector1_status

    @property
    def sector2_time_str(self) -> str:
        """Display string for the S2 box."""
        return self._last_sector2_time

    @property
    def sector2_status(self) -> SplitStatus:
        """Display colour for the S2 box."""
        return self._last_sector2_status

    @property
    def sector3_time_str(self) -> str:
        """Display string for the S3 box."""
        return self._last_sector3_time

    @property
    def sector3_status(self) -> SplitStatus:
        """Display colour for the S3 box."""
        return self._last_sector3_status

    @property
    def sector_1_dist(self) -> float:
        """Position in meters of Sector 1 timing loop."""
        if self._current_profile and self._current_profile.sector_1_dist > 0.0:
            return self._current_profile.sector_1_dist
        return self._player_s1_dist

    @property
    def sector_2_dist(self) -> float:
        """Position in meters of Sector 2 timing loop."""
        if self._current_profile and self._current_profile.sector_2_dist > 0.0:
            return self._current_profile.sector_2_dist
        return self._player_s2_dist

    @property
    def sector_1_time(self) -> float:
        """Time in seconds when passing Sector 1 loop."""
        if self._current_profile and self._current_profile.sector_1_time > 0.0:
            return self._current_profile.sector_1_time
        return self._player_s1_time

    @property
    def sector_2_time(self) -> float:
        """Time in seconds when passing Sector 2 loop."""
        if self._current_profile and self._current_profile.sector_2_time > 0.0:
            return self._current_profile.sector_2_time
        return self._player_s2_time

    @property
    def has_reference(self) -> bool:
        return self._ref_t_grid is not None and self._ref_num_points > 0

    @property
    def track_name(self) -> str:
        """Returns track name of active session."""
        return self._track_name

    @property
    def vehicle_class(self) -> str:
        """Returns vehicle class of active session (see _find_player_vehicle)."""
        return self._vehicle_class

    @property
    def vehicle_name(self) -> str:
        """Returns vehicle name of active session (see _find_player_vehicle)."""
        return self._vehicle_name

    @property
    def track_length(self) -> float:
        """Returns total track length in meters."""
        return self._track_length

    def get_energy_history_filepath(self) -> Optional[Path]:
        """Filepath for this combo's persisted per-lap fuel/energy consumption
        history (ref_<track>_<car>.energy.json) — same track/vehicle identity
        and directory as the reference-lap telemetry file (_get_profile_filepath),
        sitting next to it exactly the way its .marks.json sibling does.
        Deliberately a separate file rather than a new key merged into
        ref_<track>_<car>.json itself: FuelEnergyEngine (the only writer) has
        to work from lap 1 of a combo that has never set a timed lap — before
        _all_time_best_profile exists — without either creating a fake 0-point
        profile that would perturb has_reference, or racing
        _save_reference_profile()'s full telemetry rewrite whenever a new best
        lap is set.

        This class only *detects* the combo (from scoring packets, via
        _apply_scoring_update()) — the actual name is resolved by
        MetadataEngine, not computed here; see _sync_metadata()."""
        self._sync_metadata()
        return self._metadata.get_energy_history_filepath()

    @property
    def last_scoring_dist(self) -> float:
        """Returns latest known distance from scoring packet."""
        return self._last_scoring_dist

    @property
    def is_pit_lap(self) -> bool:
        """Returns True if current lap is an out-lap / in-lap (lap_flag == 1)."""
        return self._last_lap_flag == 1

    def get_live_car_distance(self) -> float:
        """Returns estimated current car distance."""
        return self._last_scoring_dist

    # ------------------------------------------------------------ TimeStatus
    def _build_time_status(
        self,
        lap_delta_display: float,
        lap_expected: float,
        sector_deltas: Tuple[float, float, float],
    ) -> TimeStatus:
        """Shared construction for time_status/time_status_smoothed — same
        WallOfFameTimes/eps/frozen-lap handling either way, only the live
        projection inputs differ (raw vs. smoothed). See TIME_STATUS_SPEC.md.
        """
        wof = self._wall_of_fame.snapshot()
        eps = self.time_status_eps

        if self.is_lap_freeze_active:
            # See _handle_lap_transition: the just-completed lap's own result,
            # resolved against WallOfFameTimes as it stood BEFORE that lap —
            # never the continuous live projection during this window (it
            # would self-compare, see that docstring). A frozen lap's result
            # is already a captured constant, so BOTH the raw and smoothed
            # TimeStatus reuse this exact same frozen viewmodel — smoothing a
            # constant has no meaning.
            lap_vm = self._frozen_lap_vm
        else:
            lap_vm = TimeLapViewModel(
                target=resolve_target(lap_expected, wof, "total", eps),
                expected_time=lap_expected,
                delta_time=lap_delta_display,
                is_personal_record_target=resolve_is_personal_record_target(lap_expected, wof, "total", eps),
            )

        splits = _individual_sector_splits(self._current_profile)
        keys = ("sector1", "sector2", "sector3")
        sectors = []
        for i in range(3):
            ref = splits[i]
            expected = max(0.0, ref + sector_deltas[i]) if (ref > 0.0 and self.has_reference) else 0.0
            sectors.append(TimeSectorViewModel(
                target=resolve_target(expected, wof, keys[i], eps),
                expected_time=expected,
                delta_time=sector_deltas[i],
                is_current=(self._last_current_sector == i + 1),
                is_personal_record_target=resolve_is_personal_record_target(expected, wof, keys[i], eps),
            ))

        return TimeStatus(lap=lap_vm, sectors=tuple(sectors), wall_of_fame=wof)

    @property
    def time_status(self) -> TimeStatus:
        """The single, unified timing/colour model — see TIME_STATUS_SPEC.md.
        Computed on demand from WallOfFameTimes + the RAW live projection, in
        parallel to the (now legacy) expected_*/sector*_status/etc. properties
        above during the migration; both read the same underlying state
        through two different paths.
        """
        return self._build_time_status(
            self.display_delta,
            self.estimated_lap_time,
            (self._sector1_delta, self._sector2_delta, self._sector3_delta),
        )

    @property
    def time_status_smoothed(self) -> TimeStatus:
        """Second, additive TimeStatus — same shape as time_status, built
        from the SMOOTHED live delta (see smoothed_live_delta /
        delta_smoothing_window_s) instead of the raw one. Never replaces
        time_status; both are populated every tick so a consumer (e.g. the
        Cockpit HUD plugin) can pick whichever it wants — see
        OfficialCockpitHudConfig.delta_smoothing_mode.
        """
        return self._build_time_status(
            self.smoothed_display_delta,
            self.smoothed_estimated_lap_time,
            (self._smoothed_sector1_delta, self._smoothed_sector2_delta, self._smoothed_sector3_delta),
        )
