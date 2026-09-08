"""
SimPulse SDK — Lap Delta & Timing Models.
Defines strongly-typed LapDeltaPacket, SectorInfo, and DeltaReferenceMode.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List
from warnings import deprecated

from simpulse_sdk.models.timing import TimeStatus


class DeltaReferenceMode(str, Enum):
    """Reference modes for delta calculation."""
    ALL_TIME_BEST = "all_time_best"
    SESSION_BEST = "session_best"
    STINT_BEST = "stint_best"
    LAST_LAP = "last_lap"

    def __str__(self) -> str:
        return self.value


class SplitStatus(str, Enum):
    """Colour of a single frozen sector-split box (S1/S2/S3).

    Single closed vocabulary — see core.telemetry.sector_colors.sector_split_status,
    the only place allowed to decide it. ``str`` mixin keeps every historical
    ``== "purple"`` comparison and dict-keyed lookup working unchanged; ``__str__``
    is overridden so f-strings/logging still print the plain value, not
    ``SplitStatus.PURPLE``.
    """
    DEFAULT = "default"
    PINK = "pink"
    PURPLE = "purple"

    def __str__(self) -> str:
        return self.value


class LapColorStatus(str, Enum):
    """Colour of a just-completed lap time (see DeltaEngine._handle_lap_transition)."""
    DEFAULT = "default"
    PURPLE = "purple"
    GREEN = "green"
    YELLOW = "yellow"
    INVALID = "invalid"

    def __str__(self) -> str:
        return self.value


class ExpectedStatus(str, Enum):
    """Colour of the projected/expected lap time — see
    core.telemetry.sector_colors.expected_status for the priority rule."""
    WHITE = "white"
    PINK = "pink"
    PURPLE = "purple"
    GREEN = "green"
    YELLOW = "yellow"
    INVALID = "invalid"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class SectorInfo:
    """Strongly-typed sector checkpoint information."""
    time: str = "--"
    status: SplitStatus = SplitStatus.DEFAULT
    delta: float = 0.0
    delta_str: str = "--"
    is_current: bool = False


@dataclass(frozen=True)
class LapDeltaPacket:
    """
    Strongly-typed data packet representing authoritative lap timing, delta, and sector states.
    Dispatched to all IDeltaSubscriber plugins and UI components.
    """
    live_delta: float = 0.0
    display_delta: float = 0.0
    delta_str: str = "--:--.---"
    has_reference: bool = False
    reference_mode: DeltaReferenceMode = DeltaReferenceMode.ALL_TIME_BEST
    ref_lap_time: float = 0.0
    ref_lap_time_str: str = "--:--.---"
    estimated_lap_time: float = 0.0
    estimated_lap_time_str: str = "--:--.---"
    expected_status: ExpectedStatus = ExpectedStatus.WHITE   # colour of the projected/expected lap
    # THE unified timing/colour model (see TIME_STATUS_SPEC.md) — replaces every
    # expected_sectorN_*/expected_lap_is_pr/sector1_status/etc. field below once
    # the migration reaches Step 4. Until then both are populated in parallel.
    time_status: TimeStatus = field(default_factory=TimeStatus)
    current_sector: int = 1
    # DEPRECATED (renamed to `_xxx`, see the @deprecated properties below) —
    # use `time_status.sectorN`/`time_status.lap` instead (TIME_STATUS_SPEC.md
    # Step 1: renamed first so every read site lights up in the IDE/linter
    # ahead of Step 3's migration, behaviour unchanged in the meantime).
    _sector1_delta: float = 0.0
    _sector2_delta: float = 0.0
    _sector3_delta: float = 0.0
    _sector1_time: str = "--"
    _sector1_status: SplitStatus = SplitStatus.DEFAULT
    _sector2_time: str = "--"
    _sector2_status: SplitStatus = SplitStatus.DEFAULT
    _sector3_time: str = "--"
    _sector3_status: SplitStatus = SplitStatus.DEFAULT
    sectors_list: List[SectorInfo] = field(default_factory=list)
    # DEPRECATED — reference split + live splitN delta, session-scoped colour
    # only (never pink); beating the all-time-best split was surfaced via the
    # *_is_pr flags. See DeltaEngine._expected_sector / time_status.sectorN.
    _expected_sector1_time: str = "--"
    _expected_sector1_status: ExpectedStatus = ExpectedStatus.WHITE
    _expected_sector1_is_pr: bool = False
    _expected_sector2_time: str = "--"
    _expected_sector2_status: ExpectedStatus = ExpectedStatus.WHITE
    _expected_sector2_is_pr: bool = False
    _expected_sector3_time: str = "--"
    _expected_sector3_status: ExpectedStatus = ExpectedStatus.WHITE
    _expected_sector3_is_pr: bool = False
    _expected_lap_is_pr: bool = False
    # Reference lap times for display: mine this session, best-of-session (any
    # other car). "My all-time best" is NOT here — it's a static value read
    # from a JSON file, not live telemetry; see VehicleSensors.reference_profile
    # (pushed only when it actually changes, not recomputed per packet).
    # DEPRECATED — use time_status.lap instead.
    _my_session_best_lap_time_str: str = "--:--.---"
    _session_best_lap_time_str: str = "--:--.---"
    last_lap_time: float = 0.0
    last_lap_time_str: str = "--:--.---"
    # DEPRECATED — use time_status.lap.target / time_status.lap.is_personal_record_target.
    _last_lap_status: LapColorStatus = LapColorStatus.DEFAULT
    _last_lap_is_pr: bool = False  # completed lap beat my all-time best ("PR" tag, no colour)
    is_lap_freeze_active: bool = False
    lap_flag: int = 2
    is_pit_lap: bool = False
    track_name: str = ""
    track_length: float = 0.0
    player_dist: float = 0.0
    vehicle_name: str = ""
    vehicle_class: str = ""
    timestamp: float = field(default_factory=time.time)

    # ── Deprecated flat-field aliases (TIME_STATUS_SPEC.md Step 1) ───────────
    # Read-only: LapDeltaPacket is frozen and built exclusively by
    # ReferenceLapManager._build_delta_packet(), which passes the `_xxx`
    # kwargs directly — no setter needed here (unlike VehicleSensors).
    @property
    @deprecated("Use .time_status.sector1.delta_time instead")
    def sector1_delta(self) -> float:
        return self._sector1_delta

    @property
    @deprecated("Use .time_status.sector2.delta_time instead")
    def sector2_delta(self) -> float:
        return self._sector2_delta

    @property
    @deprecated("Use .time_status.sector3.delta_time instead")
    def sector3_delta(self) -> float:
        return self._sector3_delta

    @property
    @deprecated("Use .time_status.sector1.expected_time_str (while frozen) instead")
    def sector1_time(self) -> str:
        return self._sector1_time

    @property
    @deprecated("Use .time_status.sector1.target instead")
    def sector1_status(self) -> SplitStatus:
        return self._sector1_status

    @property
    @deprecated("Use .time_status.sector2.expected_time_str (while frozen) instead")
    def sector2_time(self) -> str:
        return self._sector2_time

    @property
    @deprecated("Use .time_status.sector2.target instead")
    def sector2_status(self) -> SplitStatus:
        return self._sector2_status

    @property
    @deprecated("Use .time_status.sector3.expected_time_str (while frozen) instead")
    def sector3_time(self) -> str:
        return self._sector3_time

    @property
    @deprecated("Use .time_status.sector3.target instead")
    def sector3_status(self) -> SplitStatus:
        return self._sector3_status

    @property
    @deprecated("Use .time_status.sector1.expected_time_str instead")
    def expected_sector1_time(self) -> str:
        return self._expected_sector1_time

    @property
    @deprecated("Use .time_status.sector1.target instead")
    def expected_sector1_status(self) -> ExpectedStatus:
        return self._expected_sector1_status

    @property
    @deprecated("Use .time_status.sector1.is_personal_record_target instead")
    def expected_sector1_is_pr(self) -> bool:
        return self._expected_sector1_is_pr

    @property
    @deprecated("Use .time_status.sector2.expected_time_str instead")
    def expected_sector2_time(self) -> str:
        return self._expected_sector2_time

    @property
    @deprecated("Use .time_status.sector2.target instead")
    def expected_sector2_status(self) -> ExpectedStatus:
        return self._expected_sector2_status

    @property
    @deprecated("Use .time_status.sector2.is_personal_record_target instead")
    def expected_sector2_is_pr(self) -> bool:
        return self._expected_sector2_is_pr

    @property
    @deprecated("Use .time_status.sector3.expected_time_str instead")
    def expected_sector3_time(self) -> str:
        return self._expected_sector3_time

    @property
    @deprecated("Use .time_status.sector3.target instead")
    def expected_sector3_status(self) -> ExpectedStatus:
        return self._expected_sector3_status

    @property
    @deprecated("Use .time_status.sector3.is_personal_record_target instead")
    def expected_sector3_is_pr(self) -> bool:
        return self._expected_sector3_is_pr

    @property
    @deprecated("Use .time_status.lap.is_personal_record_target instead")
    def expected_lap_is_pr(self) -> bool:
        return self._expected_lap_is_pr

    @property
    @deprecated("Use .time_status.wall_of_fame.my_best_session.total_str instead")
    def my_session_best_lap_time_str(self) -> str:
        return self._my_session_best_lap_time_str

    @property
    @deprecated("Use .time_status.wall_of_fame.paddock_session_best.total_str instead")
    def session_best_lap_time_str(self) -> str:
        return self._session_best_lap_time_str

    @property
    @deprecated("Use .time_status.lap.target instead")
    def last_lap_status(self) -> LapColorStatus:
        return self._last_lap_status

    @property
    @deprecated("Use .time_status.lap.is_personal_record_target instead")
    def last_lap_is_pr(self) -> bool:
        return self._last_lap_is_pr
