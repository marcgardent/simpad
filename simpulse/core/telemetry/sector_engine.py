"""
SimPulse Telemetry — Sector Engine.

Factors out of ``DeltaEngine`` everything about tracking the player's S1/S2/S3
sector boxes: which sector is "current", the one-way forward-step guard that
keeps a stale/echoed packet from blinking a neighbouring box, the S1/S2
checkpoint capture (time + distance at the timing loop), the stable HUD
display strings/colours, the session-wide best splits, and the per-sector
delta split (against the active reference).

``DeltaEngine`` owns one ``SectorEngine`` instance and keeps thin,
name-compatible delegators for its previous private attributes/methods so
existing callers (tests included) keep working unchanged. New code should
prefer the nicer aggregate view: ``SectorEngine.snapshot()`` /
``DeltaEngine.sectors`` (a ``List[SectorInfo]``) instead of the historical
flat ``sector1_*``/``sector2_*``/``sector3_*`` trio.
"""

from typing import Callable, List, Optional

from simpulse_sdk.models.delta import SectorInfo

from .sector_colors import sector_split_status

LogFn = Callable[[str], None]


def _sector_time_str(seconds: float) -> str:
    """Canonical MM:ss.mmm sector display ('--' when the split is unknown)."""
    from simpulse_sdk import format_sector_time as _fmt
    return _fmt(seconds, missing="--")


def _sector_status(val: float, best_val: float, session_best: Optional[float] = None) -> str:
    """Colour of a displayed sector split time — single shared green/purple rule."""
    return sector_split_status(val, personal_best=best_val, session_best=session_best, source="delta")


def _delta_str(delta: float) -> str:
    return f"{delta:+.3f}" if delta != 0.0 else "--"


class SectorEngine:
    """
    Tracks the player's current sector and the S1/S2/S3 HUD boxes for one
    active lap/session. Pure state + arithmetic — no scoring-packet parsing,
    no disk I/O; ``DeltaEngine`` feeds it already-extracted scalars.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Full reset (session/track change)."""
        self.last_current_sector: int = 1
        self.sector_primed: bool = False

        self.session_split_best_s1: float = 0.0
        self.session_split_best_s2: float = 0.0
        self.session_split_best_s3: float = 0.0

        self.last_sector1_time: str = "--"
        self.last_sector1_status: str = "default"
        self.last_sector2_time: str = "--"
        self.last_sector2_status: str = "default"
        self.last_sector3_time: str = "--"
        self.last_sector3_status: str = "default"

        self.reset_lap_capture(clear_primed=False)

    def reset_lap_capture(self, clear_primed: bool = False) -> None:
        """Clears S1/S2 checkpoint capture and sector deltas.

        Shared by the three call sites that used to duplicate this block:
        session reset, lap-line crossing, and track/vehicle change (which
        additionally re-arms the current-sector guard via ``clear_primed``).
        """
        self.s1_captured: bool = False
        self.s2_captured: bool = False
        self.player_s1_time: float = 0.0
        self.player_s1_dist: float = 0.0
        self.player_s2_time: float = 0.0
        self.player_s2_dist: float = 0.0
        self.sector1_delta: float = 0.0
        self.sector2_delta: float = 0.0
        self.sector3_delta: float = 0.0
        if clear_primed:
            self.sector_primed = False

    def clear_deltas(self) -> None:
        """Zeroes the three sector deltas only (e.g. on reference-mode switch)."""
        self.sector1_delta = 0.0
        self.sector2_delta = 0.0
        self.sector3_delta = 0.0

    def handle_transition(
        self,
        curr_sec: int,
        *,
        time_into: float = 0.0,
        player_dist: float = 0.0,
        lap_crossed: Optional[bool] = None,
        fallback_time: float = 0.0,
        fallback_dist: float = 0.0,
        log: Optional[LogFn] = None,
    ) -> None:
        """Memorizes exact time/distance when crossing S1/S2 splits.

        Guard clause — display stability of the current sector (fixes the
        one-frame flicker where a non-current sector box briefly lights up as
        "current"):

        The authoritative ``current_sector`` is written here by every
        scoring/physics packet that reports a sector id. isiMotor keeps
        several lane states while a split is reached (``sector == 0`` on
        inter-loop gaps) and Compact/Full scoring packets can even disagree
        for a few milliseconds around a timing line. The raw ``mSector``/
        ``sector`` value is therefore *not* a monotonic run counter by
        itself. We only ever advance the HUD sector by a single forward step
        along the lap (1 -> 2 -> 3 -> 1). Repeat samples are no-ops and any
        backward/jumped echo (2->1, 3->2, 1->3 while still inside the same
        sector) is rejected so it cannot light up a neighbouring box for one
        10 Hz packet.

        The 3 -> 1 wrap additionally requires ``lap_crossed`` (the scoring
        packet that reports sector 1 must have completed a lap); a stale
        FullScoring echo that "returns" to S1 while the active lap still
        shows S3 is dropped.
        """
        if curr_sec not in (1, 2, 3):
            return
        prev_sec = self.last_current_sector
        if curr_sec == prev_sec:
            self.sector_primed = True
            return  # repeated packet: nothing to advance
        # First authoritative observation (join mid-session, session reset...): accept
        # it whatever sector it reports so the HUD catches up immediately.
        if not self.sector_primed:
            self.sector_primed = True
            self._advance(curr_sec, time_into=time_into, player_dist=player_dist,
                          fallback_time=fallback_time, fallback_dist=fallback_dist, log=log)
            return
        is_forward_step = (curr_sec == ((prev_sec % 3) + 1)) if prev_sec in (1, 2, 3) else True
        is_wrap_qualified = not (prev_sec == 3 and curr_sec == 1) or lap_crossed is not False
        if not is_forward_step or not is_wrap_qualified:
            if log:
                log(
                    f"[SECTOR_JITTER_IGNORED] packet reported S{curr_sec} while HUD was on "
                    f"S{prev_sec} (lap_crossed={lap_crossed}); rejected (would blink a "
                    f"non-current box for 1 frame)"
                )
            return
        self._advance(curr_sec, time_into=time_into, player_dist=player_dist,
                      fallback_time=fallback_time, fallback_dist=fallback_dist, log=log)

    def _advance(
        self,
        curr_sec: int,
        *,
        time_into: float,
        player_dist: float,
        fallback_time: float,
        fallback_dist: float,
        log: Optional[LogFn] = None,
    ) -> None:
        """Latches the current sector and records the S1/S2 split crossing once."""
        effective_time = time_into if time_into > 0.0 else fallback_time
        effective_dist = player_dist if player_dist > 0.0 else fallback_dist
        if curr_sec == 2 and not self.s1_captured and effective_time > 0.0:
            self.player_s1_time = effective_time
            self.player_s1_dist = effective_dist
            self.s1_captured = True
            if log:
                log(f"[SECTOR_CUT_S1] t_into={effective_time:.3f}s, dist={effective_dist:.1f}m")
        elif curr_sec == 3 and not self.s2_captured and effective_time > 0.0:
            self.player_s2_time = effective_time
            self.player_s2_dist = effective_dist
            self.s2_captured = True
            if log:
                log(f"[SECTOR_CUT_S2] t_into={effective_time:.3f}s, dist={effective_dist:.1f}m")
        self.last_current_sector = curr_sec

    def update_session_bests(self, vehicles_src: list) -> None:
        """Recomputes the session-wide best S1/S2/S3 splits from every car listed
        in a whole-session packet (Full/dict scoring; Compact carries none and
        this is simply not called, keeping the last observed values frozen).
        """
        if not vehicles_src:
            return

        def _veh_bests(v):
            if isinstance(v, dict):
                return (
                    float(v.get("mBestSector1", v.get("bestSector1", 0.0))),
                    float(v.get("mBestSector2", v.get("bestSector2", 0.0))),
                    float(v.get("mBestLapTime", v.get("bestLapTime", 0.0))),
                )
            return (
                float(getattr(v, "best_sector1", 0.0) or 0.0),
                float(getattr(v, "best_sector2", 0.0) or 0.0),
                float(getattr(v, "best_lap_time", 0.0) or 0.0),
            )

        sess_s1 = sess_s2 = sess_s3 = 0.0
        for v in vehicles_src:
            bs1, bs2, blap = _veh_bests(v)
            if 0.0 < bs1 < 999900.0:
                sess_s1 = bs1 if sess_s1 == 0.0 else min(sess_s1, bs1)
            if bs2 > 0.0 and bs1 > 0.0 and bs2 > bs1:
                indiv = bs2 - bs1
                sess_s2 = indiv if sess_s2 == 0.0 else min(sess_s2, indiv)
            if blap > 0.0 and bs2 > 0.0 and blap > bs2:
                indiv3 = blap - bs2
                sess_s3 = indiv3 if sess_s3 == 0.0 else min(sess_s3, indiv3)
        if sess_s1:
            self.session_split_best_s1 = sess_s1
        if sess_s2:
            self.session_split_best_s2 = sess_s2
        if sess_s3:
            self.session_split_best_s3 = sess_s3

    def refresh_display_times(
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
        paddock_known: bool = False,
        paddock_cum_s1: float = 999900.0,
        paddock_cum_s2: float = 999900.0,
    ) -> None:
        """
        Keeps the HUD per-sector times stable across packets.

        isiMotor exposes both current-lap cumulative timing splits (cur_*) and the
        splits of the previous fully completed lap (last_*). While a split of the
        current lap has not been crossed yet (cur_* == 0.0) we keep showing the last
        completed split so the sector boxes never flick back to '--' in the middle of
        a lap. Once crossed inside the current lap, cur_* freezes at the split value
        and becomes the displayed time.

        All values arrive at 10 Hz (CompactScoring or FullScoringSession) which is
        faster than a human can read a whole sector, so this refresh is visually crisp.
        """
        session_best_s1 = self.session_split_best_s1
        session_best_s2 = self.session_split_best_s2
        session_best_s3 = self.session_split_best_s3

        # S1: current lap when already crossed, otherwise the last completed lap split.
        s1_cur = cur_sector1 if cur_sector1 > 0.0 else last_sector1

        # -- Sector 1 box --
        if s1_cur > 0.0:
            self.last_sector1_time = _sector_time_str(s1_cur)
            self.last_sector1_status = _sector_status(s1_cur, best_sector1, session_best_s1)
            if cur_sector1 > 0.0 and paddock_known and paddock_cum_s1 < 999900.0:
                # new lap crossing: violet when better/equal paddock best S1
                if s1_cur <= paddock_cum_s1 + 0.001:
                    self.last_sector1_status = "purple"

        # -- Sector 2 box (standalone: cumulated S1+S2 minus S1) --
        # Compose exclusively from the current lap once its split is crossed, otherwise
        # fall back to the previous lap splits. Never mix current & last references.
        indiv_s2 = 0.0
        if cur_sector2 > 0.0 and cur_sector1 > 0.0 and cur_sector2 > cur_sector1:
            indiv_s2 = cur_sector2 - cur_sector1
        elif last_sector2 > 0.0 and last_sector1 > 0.0 and last_sector2 > last_sector1:
            indiv_s2 = last_sector2 - last_sector1
        if indiv_s2 > 0.0:
            self.last_sector2_time = _sector_time_str(indiv_s2)
            best_indiv_s2 = (best_sector2 - best_sector1) if (best_sector2 > 0.0 and best_sector1 > 0.0) else 0.0
            self.last_sector2_status = _sector_status(indiv_s2, best_indiv_s2, session_best_s2)
            if cur_sector2 > 0.0 and paddock_known and paddock_cum_s2 < 999900.0:
                # new S2 crossing: violet (better-or-equal paddock cumulative S2)
                if cur_sector2 <= paddock_cum_s2 + 0.001:
                    self.last_sector2_status = "purple"

        # -- Sector 3 box (standalone remainder of the last completed lap) --
        s3_cum_base = last_sector2
        if last_lap_time > 0.0 and s3_cum_base > 0.0 and last_lap_time > s3_cum_base:
            indiv_s3 = last_lap_time - s3_cum_base
            best_indiv_s3 = (best_lap_time - best_sector2) if (best_lap_time > 0.0 and best_sector2 > 0.0) else 0.0
            self.last_sector3_time = _sector_time_str(indiv_s3)
            self.last_sector3_status = _sector_status(indiv_s3, best_indiv_s3, session_best_s3)

    def compute_split_deltas(
        self,
        live_delta: float,
        get_ref_time_at_dist: Callable[[float], Optional[float]],
    ) -> None:
        """Dynamic per-sector delta split against the active reference profile.

        ``live_delta`` is the delta at the player's current distance (already
        computed by the caller); this only breaks it down into the S1/S2/S3
        pieces using the reference time at the S1/S2 checkpoint distances.
        """
        ref_s1 = get_ref_time_at_dist(self.player_s1_dist) if self.s1_captured else None
        ref_s2 = get_ref_time_at_dist(self.player_s2_dist) if self.s2_captured else None

        delta_s1_end = (self.player_s1_time - ref_s1) if (self.s1_captured and ref_s1 is not None) else 0.0
        delta_s2_end = (self.player_s2_time - ref_s2) if (self.s2_captured and ref_s2 is not None) else 0.0

        if self.last_current_sector == 1:
            self.sector1_delta = live_delta
            self.sector2_delta = 0.0
            self.sector3_delta = 0.0
        elif self.last_current_sector == 2:
            self.sector1_delta = delta_s1_end
            self.sector2_delta = live_delta - delta_s1_end
            self.sector3_delta = 0.0
        elif self.last_current_sector == 3:
            self.sector1_delta = delta_s1_end
            self.sector2_delta = delta_s2_end - delta_s1_end
            self.sector3_delta = live_delta - delta_s2_end

    def snapshot(self) -> List[SectorInfo]:
        """Nicer aggregate view of the 3 sector boxes, in S1/S2/S3 order.

        Prefer this over the flat ``sector1_*``/``sector2_*``/``sector3_*``
        trio when building a packet/UI model — one list, one shape per box.
        """
        cur = self.last_current_sector
        return [
            SectorInfo(
                time=self.last_sector1_time,
                status=self.last_sector1_status,
                delta=self.sector1_delta,
                delta_str=_delta_str(self.sector1_delta),
                is_current=(cur == 1),
            ),
            SectorInfo(
                time=self.last_sector2_time,
                status=self.last_sector2_status,
                delta=self.sector2_delta,
                delta_str=_delta_str(self.sector2_delta),
                is_current=(cur == 2),
            ),
            SectorInfo(
                time=self.last_sector3_time,
                status=self.last_sector3_status,
                delta=self.sector3_delta,
                delta_str=_delta_str(self.sector3_delta),
                is_current=(cur == 3),
            ),
        ]
