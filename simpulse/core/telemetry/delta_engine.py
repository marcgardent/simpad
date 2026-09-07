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
        self._ema_samples: int = 0  # 0 = direct/unfiltered, > 1 = EMA smoothing
        self.reset_session()

    def reset_session(self) -> None:
        """Completely resets engine state (session/track change)."""
        self._track_name: str = ""
        self._vehicle_name: str = ""
        self._vehicle_class: str = ""
        self._track_length: float = 0.0

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
        self._last_laps_completed: int = -1
        self._last_dist: float = -1.0
        self._last_lap_flag: int = 2

        # Last physical inputs
        self._last_speed_ms: float = 0.0
        self._last_throttle: float = 0.0
        self._last_brake: float = 0.0
        self._last_steering: float = 0.0
        self._last_gear: int = 0

        # Last scoring state (1-2 Hz)
        self._last_scoring_dist: float = 0.0
        self._last_scoring_time_into: float = 0.0
        self._last_scoring_timestamp: float = 0.0
        self._last_lap_start_et: float = 0.0
        self._last_checkpoint_idx: int = -1

        # Current-sector tracking, S1/S2 checkpoint capture, HUD split display and
        # per-sector deltas: all factored into SectorEngine (see its docstring).
        # The `_last_current_sector`/`_s1_captured`/`_last_sector1_time`/... names
        # below stay available as thin delegating properties for existing callers.
        self._sectors = SectorEngine()

        # Delta & Lap Time freeze at finish line
        self._frozen_final_delta: float = 0.0
        self._freeze_delta_until: float = 0.0
        self._last_completed_lap_time: float = 0.0
        self._last_completed_lap_status: LapColorStatus = LapColorStatus.DEFAULT
        self._last_completed_lap_is_pr: bool = False
        self._freeze_lap_until: float = 0.0

        # EMA smoothing
        self._ema_live_delta: float = 0.0

        # Last calculated values
        self._live_delta: float = 0.0

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
        """Returns active reference mode."""
        return self._ref_mode

    @reference_mode.setter
    def reference_mode(self, mode: DeltaReferenceMode) -> None:
        """Modifies reference mode and applies corresponding profile."""
        if isinstance(mode, str):
            try:
                mode = DeltaReferenceMode(mode)
            except ValueError:
                mode = DeltaReferenceMode.ALL_TIME_BEST
        self._ref_mode = mode
        self._apply_active_profile()

    @property
    def freeze_duration(self) -> float:
        """Delta freeze duration at finish line in seconds."""
        return self._freeze_duration

    @freeze_duration.setter
    def freeze_duration(self, val: float) -> None:
        self._freeze_duration = max(0.0, float(val))

    @property
    def ema_samples(self) -> int:
        """Sample count for EMA filter (0 = disabled)."""
        return self._ema_samples

    @ema_samples.setter
    def ema_samples(self, samples: int) -> None:
        self._ema_samples = max(0, int(samples))

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
        self._apply_active_profile()

    def _apply_active_profile(self) -> None:
        """Applies reference profile according to selected mode."""
        target_prof = None

        if self._ref_mode == DeltaReferenceMode.LAST_LAP:
            target_prof = self._last_lap_profile
        elif self._ref_mode == DeltaReferenceMode.STINT_BEST:
            target_prof = self._stint_best_profile
        elif self._ref_mode == DeltaReferenceMode.SESSION_BEST:
            target_prof = self._session_best_profile
        elif self._ref_mode == DeltaReferenceMode.ALL_TIME_BEST:
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
            self._sectors.clear_deltas()

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
    ) -> None:
        """SLAP Helper: Finalizes previous lap and resets state for new lap."""
        # Initialization on first received packet
        if self._last_laps_completed < 0:
            self._last_laps_completed = laps_comp
            self._current_lap_samples = []
            return

        # Case 1: Session reset / Restart (mTotalLaps returns to 0 or decreases)
        if laps_comp < self._last_laps_completed:
            logger.info(f"[DeltaEngine] Session reset detected: laps completed went from {self._last_laps_completed} to {laps_comp}")
            print(f"[DeltaEngine] Session reset: lap counter reset to {laps_comp}", flush=True)
            log_delta_debug(f"[SESSION_RESET] laps_completed went from {self._last_laps_completed} to {laps_comp}")
            self._current_lap_samples = []
            self._sectors.reset_lap_capture(clear_primed=True)
            self._last_laps_completed = laps_comp
            return

        # Case 2: Crossing start/finish line (new completed lap)
        if laps_comp > self._last_laps_completed:
            log_delta_debug(
                f"[LAP_LINE_CROSS] lap_completed={laps_comp} (was {self._last_laps_completed}), "
                f"last_lap_time={last_lap_time:.3f}s, flag={lap_flag}, in_pits={in_pits}, in_garage={in_garage}"
            )

            # Evaluation of color status for completed lap
            prev_session_best = self._session_best_lap_time
            prev_all_time_best = self._all_time_best_lap_time
            prev_ref_time = self._ref_lap_time

            if lap_flag != 2 or in_pits or in_garage:
                lap_status = LapColorStatus.INVALID
            elif last_lap_time > 0.0:
                if last_lap_time <= (prev_session_best + 0.001) or last_lap_time <= (prev_all_time_best + 0.001):
                    lap_status = LapColorStatus.PURPLE
                elif prev_ref_time < 999900.0 and last_lap_time < prev_ref_time:
                    lap_status = LapColorStatus.GREEN
                elif prev_ref_time < 999900.0 and last_lap_time >= prev_ref_time:
                    lap_status = LapColorStatus.YELLOW
                else:
                    lap_status = LapColorStatus.PURPLE if (prev_session_best >= 999900.0) else LapColorStatus.GREEN
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

            # Capture and freeze final delta and lap time before reset
            self._frozen_final_delta = self._live_delta
            if self._freeze_duration > 0.0:
                freeze_until = time.time() + self._freeze_duration
                self._freeze_delta_until = freeze_until
                self._freeze_lap_until = freeze_until
            else:
                self._freeze_delta_until = 0.0
                self._freeze_lap_until = 0.0

            self._finalize_completed_lap(
                lap_time=last_lap_time,
                lap_flag=lap_flag,
                in_garage=in_garage,
                in_pits=in_pits,
            )
            self._current_lap_samples = []
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
        """SLAP Helper: Collects live lap samples (full telemetry) for reference profile building."""
        if time_into > 0.0 and player_dist >= 0.0:
            if self._track_length <= 0.0 or player_dist <= self._track_length + 200.0:
                if not self._current_lap_samples or player_dist > self._current_lap_samples[-1][0]:
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
            self._last_laps_completed = laps_comp
            self._last_checkpoint_idx = -1
            self._sectors.reset_lap_capture(clear_primed=True)
            self._last_scoring_timestamp = 0.0

            # Reset session and stint best
            self._session_best_profile = None
            self._stint_best_profile = None
            self._last_lap_profile = None
            self._session_best_lap_time = 999999.0
            self._stint_best_lap_time = 999999.0
            self._last_lap_time = 999999.0

            # Load reference profile for track/car from disk
            self._load_reference_profile()

        if track_len > 0.0:
            self._track_length = track_len

        # Authoritative calculation of elapsed lap time: current_et - lap_start_et
        if lap_start_et > 0.0 and current_et >= lap_start_et:
            time_into = current_et - lap_start_et
            self._last_lap_start_et = lap_start_et
        else:
            time_into = time_into_lap if time_into_lap > 0.0 else 0.0

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
        self._handle_lap_transition(laps_comp, last_lap_time, lap_flag, in_garage, in_pits)
        self._handle_sector_transition(curr_sec, time_into=time_into, player_dist=player_dist, lap_crossed=lap_crossed)

        is_flying_lap = (lap_flag == 2 and time_into > 0.0)

        # Reset stint best if stopped in pits
        if in_pits and self._stint_best_lap_time != 999999.0 and self._last_speed_ms < 0.1:
            self._stint_best_profile = None
            self._stint_best_lap_time = 999999.0
            self._apply_active_profile()

        # Record reference samples only if valid flying lap in progress
        if is_flying_lap:
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

        # If flying lap, update position and calculate delta
        if is_flying_lap:
            # Delta calculation with exact game telemetry
            self._calculate_delta(player_dist, time_into)
        elif lap_flag != 2 or in_garage or in_pits:
            # Out-lap / Pits / Pre-start: no flying lap delta
            self._live_delta = 0.0
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

        # High-frequency continuous distance dead reckoning integration (120Hz)
        if dt > 0.0 and self._last_speed_ms > 0.0 and self._last_scoring_dist >= 0.0:
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

        if self._last_lap_flag == 2 and self._last_scoring_dist >= 0.0:
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

    def _calculate_delta(self, player_dist: float, time_into: float) -> None:
        """Calculates live delta and per-sector deltas from distance and time."""
        if not self.has_reference or time_into <= 0.0 or player_dist < 0.0:
            self._live_delta = 0.0
            self._sectors.clear_deltas()
            log_delta_debug(
                f"[DELTA_NO_REF] dist={player_dist:.1f}m, t_into={time_into:.3f}s, has_ref={self.has_reference}, "
                f"flag={self._last_lap_flag}, mode={self._ref_mode.value}"
            )
            return

        ref_time = self._get_ref_time_at_dist(player_dist)
        if ref_time is None:
            self._live_delta = 0.0
            self._sectors.clear_deltas()
            log_delta_debug(
                f"[DELTA_REF_LOOKUP_FAIL] dist={player_dist:.1f}m, t_into={time_into:.3f}s, "
                f"ref_num_points={self._ref_num_points}"
            )
            return

        raw_delta = time_into - ref_time

        # Clamp extreme deltas to +/- 999.0s
        if abs(raw_delta) < 999.0:
            # Optional EMA smoothing
            if self._ema_samples > 1:
                factor = 2.0 / (self._ema_samples + 1.0)
                self._ema_live_delta += factor * (raw_delta - self._ema_live_delta)
                self._live_delta = self._ema_live_delta
            else:
                self._live_delta = raw_delta
                self._ema_live_delta = raw_delta
        else:
            self._live_delta = 0.0

        # Save delta for freeze maintenance
        self._frozen_checkpoint_delta = self._live_delta

        # Dynamic calculation of sector deltas against ACTIVE profile
        self._sectors.compute_split_deltas(self._live_delta, self._get_ref_time_at_dist)

        log_delta_debug(
            f"[DELTA_CALC] dist={player_dist:.1f}m, t_into={time_into:.3f}s, ref_t={ref_time:.3f}s, "
            f"raw_delta={raw_delta:+.3f}s, live_delta={self._live_delta:+.3f}s, "
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
        logger.info(f"[DeltaEngine] Lap completed: lap_time={lap_time:.3f}s, flag={lap_flag}, samples={sample_count}")
        print(f"[DeltaEngine] Lap completed: {lap_time:.3f}s (flag={lap_flag}, samples={sample_count})", flush=True)

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

    def _get_profile_filepath(self) -> Optional[Path]:
        """Returns JSON filepath for (track, vehicle_class/vehicle)."""
        if not self._track_name:
            return None
        t_clean = _clean_name(self._track_name)
        v_identifier = _clean_name(self._vehicle_class) if self._vehicle_class else _clean_name(self._vehicle_name)
        if not v_identifier:
            v_identifier = "default"
        filename = f"ref_{t_clean}_{v_identifier}.json"
        return _REF_LAPS_DIR / filename

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
            self._apply_active_profile()
            print(f"[DeltaEngine] Track marks loaded for '{self._track_name}': {marks_filepath.name} ({len(placeholder.annotations)} annotations). Waiting for 1st timed lap.", flush=True)
            log_delta_debug(f"[REF_LOAD_MARKS_ONLY] marks_file='{marks_filepath.name}', marks={len(placeholder.annotations)}")
            return

        # 3. No file found for track: pristine state (0 annotations, no leak from other tracks)
        self._all_time_best_profile = None
        self._all_time_best_lap_time = 999999.0
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
    def _ever_lap_bound(self) -> Optional[float]:
        return self._all_time_best_lap_time if (self._all_time_best_lap_time or 0.0) < 999900.0 else None

    @property
    def _session_lap_bound(self) -> Optional[float]:
        return self._session_best_lap_time if (self._session_best_lap_time or 0.0) < 999900.0 else None

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
        ("PR" — personal record). Purely informational; never drives colour."""
        ever = self._ever_lap_bound
        if ever is None or not self.has_reference:
            return False
        v = self.estimated_lap_time
        return 0.0 < v and v <= ever + 0.001

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
        is_pr = ever is not None and 0.0 < expected <= ever + 0.001
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

    @property
    def my_all_time_best_lap_time_str(self) -> str:
        """My all-time best lap ('mon meilleur best ever')."""
        b = self._ever_lap_bound
        return format_lap_time(b) if b is not None else "--:--.---"

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
    def track_length(self) -> float:
        """Returns total track length in meters."""
        return self._track_length

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
