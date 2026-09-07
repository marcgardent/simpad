"""
SimPulse Race Engineer — Evaluation context for race engineer roles.
Provides unified, clean, and optimized access to telemetry and scoring data (LMU).
"""

from __future__ import annotations
import math
import time
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Union

from isimotor_rawudp_client import (
    TelemInfo,
    CompactScoring,
    FullScoringSession,
    VehicleScoring,
    TelemVect3,
)

from .base import AudioEngineType
from simpulse.core.telemetry.state_store import TelemetryStateStore
from simpulse_sdk.models.reference_profile import ReferenceLapProfileView
from simpulse.core.telemetry_channels import TelemetryRawPacket

TelemetryTriggerPacket = Union[TelemInfo, FullScoringSession, CompactScoring, TelemetryRawPacket]


def _unwrap_slot(value):
    """Returns the payload of ``value`` whether it's a raw PacketSlot (a real
    TelemetryStateStore's ``.delta``/``.reference_profile``, wrapped) or
    already the unwrapped payload (the consolidated TelemetryView the
    PluginManager dispatcher actually hands non-raw-ingest plugins carries
    these as plain ``Optional[...]`` fields, no PacketSlot). ``store=`` on
    this context is used with either at different call sites, so callers must
    go through this instead of assuming one shape."""
    if value is None:
        return None
    return value.data if hasattr(value, "data") else value

_SCORING_STORE_SYNC = {
    FullScoringSession: lambda st, sc, ts: st.update_full_scoring(sc, ts),
    CompactScoring: lambda st, sc, ts: st.update_compact_scoring(sc, ts),
}

_PLAYER_VEHICLE_EXTRACTORS = {
    FullScoringSession: lambda sc: sc.player_vehicle,
}

_GARAGE_CHECKERS = {
    CompactScoring: lambda sc: bool(sc.in_garage_stall),
    FullScoringSession: lambda sc: (
        True if (sc.game_phase == 0 or not sc.in_realtime)
        else (bool(sc.player_vehicle.in_garage_stall) if sc.player_vehicle is not None else False)
    ),
}


@dataclass
class EngineerContext:
    """
    Unified telemetry & scoring context passed to each role during evaluation.
    Encapsulates all necessary data for intelligent situational decisions.
    """
    telemetry: Optional[TelemInfo] = None
    scoring: Optional[Union[FullScoringSession, CompactScoring]] = None
    timestamp: float = field(default_factory=time.time)
    audio_engine: Optional[AudioEngineType] = None
    reference_profile: Optional[ReferenceLapProfileView] = None
    store: Optional[TelemetryStateStore] = None
    trigger_packet: Optional[TelemetryTriggerPacket] = None

    @property
    def state_store(self) -> TelemetryStateStore:
        """Returns active TelemetryStateStore instance, ensuring telemetry & scoring sync."""
        if self.store is not None:
            return self.store
        st = TelemetryStateStore.get_instance()
        if self.telemetry is not None:
            st.update_telemetry(self.telemetry, self.timestamp)
        if self.scoring is not None:
            sync_fn = _SCORING_STORE_SYNC.get(type(self.scoring))
            if sync_fn:
                sync_fn(st, self.scoring, self.timestamp)
        return st

    def _resolve_state_store(self) -> Optional[TelemetryStateStore]:
        """
        Returns the unified store this context should consult for vehicle/grid state.

        Sources are authoritative only when this context actually carries them:
          - an explicitly injected ``store``,
          - or a ``scoring`` event (ingested on demand).
        A standalone context (no scoring / no store) must NOT read the global
        TelemetryStateStore singleton to avoid cross-test residue leaking into role
        evaluations — it may carry a reference_profile instead (used below).
        """
        if self.store is not None:
            return self.store
        if self.scoring is not None and self.state_store is not None:
            return self.state_store
        return None

    @property
    def wheels_on_track(self) -> int:
        """Authoritative wheels on track from state store."""
        return self.state_store.wheels_on_track

    @property
    def is_on_track(self) -> bool:
        """Authoritative on-track boolean from state store."""
        return self.state_store.is_on_track

    @property
    def lap_flag(self) -> int:
        """Authoritative count_lap_flag from state store."""
        return self.state_store.lap_flag

    @property
    def is_lap_valid(self) -> bool:
        """Authoritative is_lap_valid from state store."""
        return self.state_store.is_lap_valid

    @property
    def is_lap_invalid(self) -> bool:
        """Authoritative is_lap_invalid from state store."""
        return self.state_store.is_lap_invalid

    @property
    def lap_timing_status(self) -> str:
        """Authoritative lap timing status ('timing_in_progress' or 'time_deleted')."""
        return self.state_store.lap_timing_status

    @property
    def lap_status_text(self) -> str:
        """Authoritative lap status description ('Valid' or 'Invalid')."""
        return self.state_store.lap_status_text

    @property
    def last_validity_event(self) -> str:
        """Last validity transition event ('TIMING_IN_PROGRESS', 'TIME_DELETED', 'IDLE')."""
        return self.state_store.last_validity_event

    @property
    def last_validity_event_time(self) -> float:
        """Timestamp of last validity transition."""
        return self.state_store.last_validity_event_time

    @property
    def validity_transition(self) -> Optional[str]:
        """Pending validity transition from state store."""
        return self.state_store.validity_transition

    @property
    def num_penalties(self) -> int:
        """Authoritative active penalties from state store."""
        return self.state_store.num_penalties

    @property
    def track_limits_steps(self) -> int:
        """Authoritative track limits steps from state store."""
        return self.state_store.track_limits_steps

    @property
    def in_realtime(self) -> bool:
        """Authoritative in_realtime boolean from state store."""
        return self.state_store.in_realtime

    @property
    def in_garage(self) -> bool:
        """Authoritative in_garage boolean."""
        return self.is_player_in_garage()

    @property
    def speed_kmh(self) -> float:
        """Authoritative speed in km/h."""
        return self.state_store.speed_kmh

    @property
    def throttle_pct(self) -> float:
        """Authoritative throttle percentage (0-100%)."""
        return self.state_store.throttle_pct

    @property
    def brake_pct(self) -> float:
        """Authoritative brake percentage (0-100%)."""
        return self.state_store.brake_pct

    # ------------------------------------------------------------------ #
    # Unified scoring façade (roles NEVER read the raw scoring packets)
    # ------------------------------------------------------------------ #

    @property
    def active_session(self) -> Optional[int]:
        """Authoritative session code from the unified timing state.
        Returns None when this context has no scoring source (never reads the global
        singleton residue of unrelated contexts).
        """
        store = self._resolve_state_store()
        if store is None:
            return None
        # BaseTimingState is fed by CompactScoring (10 Hz) and also re-derived from a
        # FullScoringSession when only Full is available; it is the common session source.
        base = store.timing if store.timing is not None else store.grid
        if base is None:
            return None
        return int(getattr(base, "session", 0))

    @property
    def grid_available(self) -> bool:
        """True when this context's full-grid state (leaderboard) is available."""
        store = self._resolve_state_store()
        return store is not None and store.grid is not None

    @property
    def scoring_available(self) -> bool:
        """True when any scoring timing state is available for this context."""
        store = self._resolve_state_store()
        if store is None:
            return False
        return (store.timing is not None and bool(store.timing.track_name)) or store.grid is not None

    @property
    def has_scoring_packet(self) -> bool:
        """True when consolidated scoring state is present (view-safe; no raw slot access)."""
        return self.scoring_available

    def get_session_type(self) -> int:
        """
        Returns session code from the unified scoring state (LMU / rF2):
        0 = TestDay, 1..4 = Practice, 5..8 = Qualifying, 9 = Warmup,
        10..13 = Race. Returns -1 when unavailable.
        """
        sess = self.active_session
        return sess if sess is not None else -1

    def is_qualifying_session(self) -> bool:
        """Indicates whether active session is a qualifying session (session between 5 and 8 inclusive)."""
        return self.get_session_type() in (5, 6, 7, 8)

    def is_private_qualifying(self) -> bool:
        """
        Indicates whether active session is in private qualifying.
        In Le Mans Ultimate, qualifying sessions (session 5-8) are isolated
        (ghost/invisible cars, no physical contact possible).
        """
        return self.is_qualifying_session()

    def get_track_name(self) -> str:
        """Returns active track name from the unified state (timing/grid/delta) or reference profile.

        Sources are authoritative only when this context carries them (explicit store or an
        incoming scoring event); a standalone context relies on its injected reference profile
        and never reads the global store residue of unrelated evaluations.
        """
        resolved = self._resolve_state_store()
        if resolved is not None:
            if resolved.timing is not None and getattr(resolved.timing, "track_name", ""):
                name = str(resolved.timing.track_name).strip()
                if name:
                    return name
            if resolved.grid is not None and getattr(resolved.grid, "track_name", ""):
                name = str(resolved.grid.track_name).strip()
                if name:
                    return name
            delta = _unwrap_slot(resolved.delta)
            if delta is not None and delta.track_name:
                return str(delta.track_name).strip()

        if self.reference_profile is not None and self.reference_profile.track_name:
            ref_name = str(self.reference_profile.track_name).strip()
            if ref_name:
                return ref_name
        return ""
    def get_reference_profile(self) -> Optional[ReferenceLapProfileView]:
        """
        Returns active reference lap profile if it matches current track.
        Sanctioned SDK path only: `self.reference_profile` is injected once per
        tick by RaceEngineerManager._get_active_reference_profile() (the sole
        authorized Core entry point). No fallback into ReferenceLapManager here
        — a standalone/unit-test context without an injected profile simply has
        none, rather than reaching into the global Core singleton/its residue.
        """
        if self.reference_profile is None:
            return None

        scoring_track = self.get_track_name()
        ref_track = self.reference_profile.track_name
        if scoring_track and ref_track:
            t1 = "".join(c for c in scoring_track if c.isalnum()).lower()
            t2 = "".join(c for c in ref_track if c.isalnum()).lower()
            if t1 and t2 and t1 != t2:
                return None
        return self.reference_profile

    def get_reference_speed_mps(
        self,
        track_dist: float,
        profile: Optional[ReferenceLapProfileView] = None,
    ) -> Optional[float]:
        """Returns reference lap speed at given track position (m/s)."""
        ref_prof = profile or self.get_reference_profile()
        if not ref_prof or ref_prof.num_points < 2:
            return None
        val = ref_prof.get_value_at_dist(track_dist)
        return float(val.get("speed_ms", 0.0))

    def is_speed_in_normal_domain(
        self,
        speed_mps: float,
        track_dist: float,
        profile: Optional[ReferenceLapProfileView] = None,
        tolerance_kmh: float = 30.0,
    ) -> bool:
        """
        Checks if given speed is within 'normal racing domain'
        relative to reference lap at exact track position.
        """
        ref_prof = profile or self.get_reference_profile()
        if not ref_prof or ref_prof.num_points < 2:
            return True

        val = ref_prof.get_value_at_dist(track_dist)
        ref_speed_mps = float(val.get("speed_ms", 0.0))
        ref_speed_kmh = ref_speed_mps * 3.6
        actual_speed_kmh = speed_mps * 3.6

        # If reference lap has no valid speed at this location
        if ref_speed_kmh <= 1.0:
            return True

        delta_kmh = abs(actual_speed_kmh - ref_speed_kmh)
        return delta_kmh <= float(tolerance_kmh)

    def is_vehicle_in_normal_domain(
        self,
        veh: Optional[VehicleScoring],
        profile: Optional[ReferenceLapProfileView] = None,
        tolerance_kmh: float = 30.0,
    ) -> bool:
        """
        Determines if vehicle is driving within its 'normal' speed domain
        based on track position.
        """
        if veh is None:
            return True
        track_len = self.get_track_length()
        lap_dist = veh.lap_dist % track_len

        speed_mps = self.extract_vehicle_speed_mps(veh)
        return self.is_speed_in_normal_domain(
            speed_mps=speed_mps,
            track_dist=lap_dist,
            profile=profile,
            tolerance_kmh=tolerance_kmh,
        )

    def is_player_in_normal_domain(
        self,
        profile: Optional[ReferenceLapProfileView] = None,
        tolerance_kmh: float = 30.0,
    ) -> bool:
        """Determines if player vehicle is driving within normal speed domain."""
        player_veh = self.get_player_vehicle()
        if not player_veh:
            return True
        track_len = self.get_track_length()
        lap_dist = player_veh.lap_dist % track_len
        player_speed = self.get_player_speed_mps()
        return self.is_speed_in_normal_domain(
            speed_mps=player_speed,
            track_dist=lap_dist,
            profile=profile,
            tolerance_kmh=tolerance_kmh,
        )

    def has_traffic_domain_anomaly(
        self,
        player_veh: Optional[VehicleScoring],
        opp_veh: Optional[VehicleScoring],
        profile: Optional[ReferenceLapProfileView] = None,
        tolerance_kmh: float = 30.0,
    ) -> bool:
        """
        Checks filter condition for traffic roles:
        At least one vehicle (player OR opponent) must be out of normal domain.
        """
        ref_prof = profile or self.get_reference_profile()
        if not ref_prof or ref_prof.num_points < 2:
            return True

        player_in = self.is_vehicle_in_normal_domain(player_veh, profile=ref_prof, tolerance_kmh=tolerance_kmh)
        opp_in = self.is_vehicle_in_normal_domain(opp_veh, profile=ref_prof, tolerance_kmh=tolerance_kmh)

        return (not player_in) or (not opp_in)

    def get_track_length(self) -> float:
        """Returns total track length in meters (unified timing/grid/delta state first)."""
        store = self._resolve_state_store()
        if store is not None:
            # Unified scoring models expose track_length (disambiguated from car lap distance).
            base = store.grid if store.grid is not None else store.timing
            if base is not None and getattr(base, "track_length", 0.0) > 500.0:
                return float(base.track_length)
            delta = _unwrap_slot(store.delta)
            if delta is not None and delta.track_length > 500.0:
                return float(delta.track_length)
        if self.reference_profile is not None and self.reference_profile.track_length > 500.0:
            return float(self.reference_profile.track_length)
        return 5000.0  # Fallback default

    def get_player_lap_dist(self) -> float:
        """Authoritative continuous player lap distance in meters (from state store / delta dead-reckoning)."""
        player_veh = self.get_player_vehicle()
        if player_veh is not None and player_veh.lap_dist > 0.0:
            return float(player_veh.lap_dist)
        return self.state_store.lap_dist

    def get_player_total_laps(self) -> int:
        """Authoritative player total laps completed."""
        player_veh = self.get_player_vehicle()
        if player_veh is not None:
            return int(player_veh.total_laps)
        return self.state_store.total_laps

    def _grid_player_vehicle(self) -> Optional[VehicleScoring]:
        """Returns the player vehicle from the unified grid state (full scoring)."""
        store = self._resolve_state_store()
        if store is None:
            return None
        grid = store.grid
        if grid is None:
            return None
        if grid.player_vehicle is not None:
            return grid.player_vehicle
        # Fallback: locate player flag inside the full grid vehicle list.
        for v in grid.vehicles:
            if getattr(v, "is_player", False) or getattr(v, "control", 0) == 0:
                return v
        return None

    def _grid_vehicles(self) -> List[VehicleScoring]:
        """Returns the complete vehicle list of the unified grid state (empty when no grid)."""
        store = self._resolve_state_store()
        if store is None or store.grid is None:
            return []
        return list(store.grid.vehicles)

    def get_player_vehicle(self) -> Optional[VehicleScoring]:
        """Extracts player vehicle from the unified full-grid state (never the raw packet)."""
        return self._grid_player_vehicle()

    def is_player_in_pits(self) -> bool:
        """Indicates whether player vehicle is currently in pitlane (between entry and exit)."""
        player = self._grid_player_vehicle()
        if not player:
            return False
        return self.is_vehicle_in_pits(player)

    def is_player_in_garage(self) -> bool:
        """Indicates whether player is in garage stall or menus (unified state)."""
        player = self._grid_player_vehicle()
        if player is not None:
            return bool(player.in_garage_stall)
        return self.state_store.in_garage

    @classmethod
    def is_vehicle_in_pits(cls, veh: Optional[VehicleScoring]) -> bool:
        """
        Indicates whether a given vehicle is in pitlane.
        Checks in_pits flag and pit_state (2=entering, 3=stopped, 4=exiting).
        """
        if veh is None:
            return False
        return veh.in_pits or veh.pit_state in (2, 3, 4)

    @classmethod
    def is_vehicle_in_garage(cls, veh: Optional[VehicleScoring]) -> bool:
        """Indicates whether a given vehicle is in its garage / pit stall."""
        if veh is None:
            return False
        return veh.in_garage_stall

    def get_track_opponents(self) -> List[VehicleScoring]:
        """
        Returns list of active opponent vehicles ON TRACK (excluding pits and garage).
        Ensures no pitlane vehicle interferes with on-track spotter or traffic calculations.
        """
        return self.get_opponent_vehicles(include_pits=False, include_garage=False)

    def get_pit_opponents(self) -> List[VehicleScoring]:
        """
        Returns list of active opponent vehicles IN PITLANE (excluding garage).
        Enables distinct handling of pitlane traffic.
        """
        if not self.grid_available:
            return []

        pit_opponents: List[VehicleScoring] = []
        for v in self._grid_vehicles():
            if v.is_player or v.control == 0:
                continue
            if v.in_garage_stall:
                continue
            if not self.is_vehicle_in_pits(v):
                continue
            if v.finish_status != 0:
                continue
            pit_opponents.append(v)
        return pit_opponents

    def get_opponent_vehicles(
        self,
        include_pits: bool = False,
        include_garage: bool = False,
    ) -> List[VehicleScoring]:
        """
        Returns list of active opponent vehicles.
        Excludes player, vehicles in garage (unless include_garage=True),
        and cars in pits (unless include_pits=True).
        Unified grid state (2-5 Hz) is the only source; gated by availability.
        """
        if not self.grid_available:
            return []

        opponents: List[VehicleScoring] = []
        for v in self._grid_vehicles():
            if v.is_player or v.control == 0:
                continue
            if not include_garage and v.in_garage_stall:
                continue
            if not include_pits and self.is_vehicle_in_pits(v):
                continue
            if v.finish_status != 0:
                continue
            opponents.append(v)
        return opponents

    @classmethod
    def extract_vehicle_speed_mps(cls, veh: Optional[VehicleScoring]) -> float:
        """Returns scalar speed in m/s of vehicle."""
        if veh is None:
            return 0.0
        return float(veh.speed_mps)

    def get_player_speed_mps(self) -> float:
        """Returns instantaneous player speed in m/s."""
        if self.telemetry is not None:
            return float(self.telemetry.speed_mps)
        player_veh = self.get_player_vehicle()
        if player_veh is not None:
            return float(player_veh.speed_mps)
        return self.state_store.speed_kmh / 3.6

    def compute_distance_behind(
        self,
        player_veh: VehicleScoring,
        opp_veh: VehicleScoring,
        track_length: Optional[float] = None,
    ) -> float:
        """
        Calculates relative distance along track spline.
        - Value > 0: Opponent is BEHIND player (in meters).
        - Value < 0: Opponent is AHEAD OF player (in meters).
        Handles finish line wraparound.
        """
        l_track = track_length or self.get_track_length()
        p_dist = player_veh.lap_dist % l_track
        o_dist = opp_veh.lap_dist % l_track

        delta = (p_dist - o_dist) % l_track
        if delta < l_track / 2.0:
            return delta  # Opponent behind
        else:
            return delta - l_track  # Opponent ahead (negative value)

    @classmethod
    def compute_euclidean_distance(cls, veh_a: Optional[VehicleScoring], veh_b: Optional[VehicleScoring]) -> float:
        """Calculates 3D Euclidean distance between two vehicles."""
        if veh_a is None or veh_b is None:
            return float("inf")
        pa = veh_a.pos
        pb = veh_b.pos
        if pa.x == 0.0 and pa.y == 0.0 and pa.z == 0.0:
            return float("inf")
        if pb.x == 0.0 and pb.y == 0.0 and pb.z == 0.0:
            return float("inf")
        return math.dist(pa.as_tuple(), pb.as_tuple())

