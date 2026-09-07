"""
SimPulse Qt6 Core — Reference Lap & Delta Management Subsystem.

Provides:
- Strongly-typed LapDeltaPacket data packets for timing, sectors, and live deltas.
- ReferenceLapManager central QObject managing multi-reference lap profiles (All-Time Best, Session Best, Stint Best, Last Lap).
- 100 Hz live delta interpolation and sector checkpoint tracking.
- Track annotations management (Brake, Turn-in, Turns T1..T30, Gears G1..G8).
- Qt Signals for lap records, sector completions, and profile updates.
"""

from __future__ import annotations
import time
import logging
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Union, TYPE_CHECKING

from PySide6.QtCore import QObject, Signal
from isimotor_rawudp_client import FullScoringSession, CompactScoring

if TYPE_CHECKING:
    from simpulse.core.config import ConfigManager
    from simpulse_sdk.models.view import TelemetryView

from simpulse.core.telemetry.reference_profile import (
    ReferenceLapProfile,
    TrackAnnotation,
    AnnotationType,
    DEFAULT_REF_LAPS_DIR,
    get_marks_filepath,
    find_marks_filepath_for_track,
    find_telemetry_filepath_for_track,
    clean_name_identifier,
)
from simpulse.core.telemetry.delta_engine import (
    DeltaEngine,
    DeltaReferenceMode,
    format_lap_time,
)
# Canonical types (single source of truth — do not redefine locally, the SDK
# contracts (IDeltaSubscriber.on_delta_frame etc.) type-hint against these).
from simpulse_sdk.models.delta import LapDeltaPacket
from simpulse_sdk.models.scoring import BaseTimingState, FullGridScoringState

logger = logging.getLogger("simpulse.core.reference_lap")

ScoringPacketType = Union[FullScoringSession, CompactScoring, Dict[str, Union[str, int, float, bool, None]]]


class ReferenceLapManager(QObject):
    """
    Core Reference Lap & Delta Management Service (Qt6 Pure).
    Authoritatively orchestrates DeltaEngine, spatial reference interpolation, and track annotations.
    """

    # Qt Signals
    delta_updated = Signal(object)                  # LapDeltaPacket
    reference_profile_changed = Signal(object)      # Optional[ReferenceLapProfile]
    lap_completed = Signal(object)                  # LapDeltaPacket
    sector_completed = Signal(int, float, float, str)  # sector_num, sector_time, delta, status
    annotations_changed = Signal(list)              # List[TrackAnnotation]

    _instance: Optional[ReferenceLapManager] = None

    def __init__(self, config_manager: Optional[ConfigManager] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        ReferenceLapManager._instance = self
        self.config_manager = config_manager
        self.delta_engine = DeltaEngine()

        self._last_emitted_packet = LapDeltaPacket()
        self._last_laps_completed_count: int = -1
        self._last_completed_sector: int = 1

        # Apply configuration if available
        if self.config_manager and self.config_manager.config:
            app_cfg = self.config_manager.config.app
            if app_cfg:
                self.set_reference_mode(app_cfg.delta_reference_mode)
                self.delta_engine.freeze_duration = app_cfg.delta_freeze_duration
                self.delta_engine.ema_samples = app_cfg.delta_ema_samples

    @classmethod
    def get_instance(cls) -> ReferenceLapManager:
        """Singleton accessor fallback for components outside of direct Qt injection."""
        if cls._instance is None:
            cls._instance = ReferenceLapManager()
        return cls._instance

    # =========================================================================
    # Profile & State Accessors
    # =========================================================================

    @property
    def current_profile(self) -> Optional[ReferenceLapProfile]:
        return self.delta_engine.current_profile

    @property
    def all_time_best_profile(self) -> Optional[ReferenceLapProfile]:
        return self.delta_engine.all_time_best_profile

    @property
    def session_best_profile(self) -> Optional[ReferenceLapProfile]:
        return self.delta_engine.session_best_profile

    @property
    def stint_best_profile(self) -> Optional[ReferenceLapProfile]:
        return self.delta_engine.stint_best_profile

    @property
    def last_lap_profile(self) -> Optional[ReferenceLapProfile]:
        return self.delta_engine.last_lap_profile

    @property
    def has_reference(self) -> bool:
        return self.delta_engine.has_reference

    @property
    def reference_mode(self) -> DeltaReferenceMode:
        return self.delta_engine.reference_mode

    @property
    def latest_packet(self) -> LapDeltaPacket:
        return self._last_emitted_packet

    def get_active_profile(self) -> Optional[ReferenceLapProfile]:
        """Return active profile or All-Time best profile."""
        return self.delta_engine.current_profile or self.delta_engine.all_time_best_profile

    def get_value_at_dist(self, player_dist: float) -> Dict[str, float]:
        """O(1) Spatial telemetry query at distance in meters."""
        prof = self.get_active_profile()
        if prof:
            return prof.get_value_at_dist(player_dist)
        return {
            "time_into": 0.0,
            "speed_ms": 0.0,
            "speed_kmh": 0.0,
            "gear": 0.0,
            "throttle": 0.0,
            "brake": 0.0,
            "steering": 0.0,
        }

    def get_annotations(self) -> List[TrackAnnotation]:
        """Return current track annotations."""
        prof = self.get_active_profile()
        if prof and prof.annotations:
            return list(prof.annotations)
        return []

    # =========================================================================
    # Mutations & Configuration
    # =========================================================================

    def set_reference_mode(self, mode: str | DeltaReferenceMode) -> None:
        """Switch active reference profile mode (All-Time Best, Session Best, Stint Best, Last Lap)."""
        if isinstance(mode, str):
            try:
                mode = DeltaReferenceMode(mode.lower())
            except ValueError:
                mode = DeltaReferenceMode.ALL_TIME_BEST
        self.delta_engine.reference_mode = mode
        if self.config_manager and self.config_manager.config and self.config_manager.config.app:
            self.config_manager.config.app.delta_reference_mode = mode.value
            self.config_manager.save()
        self.reference_profile_changed.emit(self.current_profile)

    def set_freeze_duration(self, duration: float) -> None:
        self.delta_engine.freeze_duration = max(0.0, float(duration))
        if self.config_manager and self.config_manager.config and self.config_manager.config.app:
            self.config_manager.config.app.delta_freeze_duration = self.delta_engine.freeze_duration
            self.config_manager.save()

    def set_ema_samples(self, samples: int) -> None:
        self.delta_engine.ema_samples = max(0, int(samples))
        if self.config_manager and self.config_manager.config and self.config_manager.config.app:
            self.config_manager.config.app.delta_ema_samples = self.delta_engine.ema_samples
            self.config_manager.save()

    def add_annotation(
        self,
        ann_type: AnnotationType,
        distance: float,
        gear: Optional[int] = None,
        label: Optional[str] = None,
        color: Optional[List[int]] = None,
        auto_save: bool = True,
    ) -> Optional[TrackAnnotation]:
        """Add track annotation to active profile and auto-persist."""
        prof = self.get_active_profile()
        if prof:
            ann = prof.add_annotation(ann_type, distance, gear=gear, label=label, color=color, auto_save=auto_save)
            self.annotations_changed.emit(prof.annotations)
            return ann
        return None

    def remove_annotation(self, annotation_id: str, auto_save: bool = True) -> bool:
        prof = self.get_active_profile()
        if prof:
            ok = prof.remove_annotation(annotation_id, auto_save=auto_save)
            if ok:
                self.annotations_changed.emit(prof.annotations)
            return ok
        return False

    def move_annotation(self, annotation_id: str, new_distance: float, auto_save: bool = True) -> bool:
        prof = self.get_active_profile()
        if prof:
            ok = prof.move_annotation(annotation_id, new_distance, auto_save=auto_save)
            if ok:
                self.annotations_changed.emit(prof.annotations)
            return ok
        return False

    # =========================================================================
    # Telemetry Ingestion & Packet Building
    # =========================================================================

    def update_physics(
        self,
        veh_speed_ms: float,
        throttle: float = 0.0,
        brake: float = 0.0,
        steering: float = 0.0,
        gear: int = 0,
        dt: float = 0.0,
        elapsed_time: float = 0.0,
        lap_start_et: float = 0.0,
    ) -> LapDeltaPacket:
        """Update physics in DeltaEngine and return authoritative LapDeltaPacket."""
        prev_has_ref = self.delta_engine.has_reference
        self.delta_engine.update_physics(
            veh_speed_ms=veh_speed_ms,
            throttle=throttle,
            brake=brake,
            steering=steering,
            gear=gear,
            dt=dt,
            elapsed_time=elapsed_time,
            lap_start_et=lap_start_et,
        )
        if self.delta_engine.has_reference != prev_has_ref:
            self.reference_profile_changed.emit(self.current_profile)

        packet = self._build_delta_packet(player_dist=self.delta_engine.last_scoring_dist)
        self._last_emitted_packet = packet
        try:
            from simpulse.core.telemetry.state_store import TelemetryStateStore
            TelemetryStateStore.get_instance().update_delta(packet)
        except Exception:
            pass
        self.delta_updated.emit(packet)
        return packet

    def update_physics_from_view(self, view: "TelemetryView") -> Optional[LapDeltaPacket]:
        """Update physics in DeltaEngine from the consolidated TelemetryView instead
        of hand-extracted raw scalars — same single-source-of-truth pattern as
        update_scoring_from_view() below. Returns None when the Store hasn't
        ingested any TelemInfo yet (view.raw_telemetry is None)."""
        if view.raw_telemetry is None:
            return None
        t = view.raw_telemetry
        return self.update_physics(
            veh_speed_ms=float(t.speed_mps),
            throttle=float(t.unfiltered_throttle),
            brake=float(t.unfiltered_brake),
            steering=float(t.unfiltered_steering),
            gear=int(t.gear),
            dt=float(t.delta_time),
            elapsed_time=float(t.elapsed_time),
            lap_start_et=float(t.lap_start_et),
        )

    def update_scoring(self, scoring_data: ScoringPacketType) -> LapDeltaPacket:
        """Process scoring packet in DeltaEngine, detect lap/sector transitions and return LapDeltaPacket."""
        prev_laps = self.delta_engine._last_laps_completed
        prev_sector = self.delta_engine.current_sector
        prev_prof = self.delta_engine.current_profile

        self.delta_engine.update_scoring(scoring_data)

        if self.delta_engine.current_profile != prev_prof:
            self.reference_profile_changed.emit(self.current_profile)

        cur_laps = self.delta_engine._last_laps_completed
        cur_sector = self.delta_engine.current_sector

        packet = self._build_delta_packet(player_dist=self.delta_engine.last_scoring_dist)
        self._last_emitted_packet = packet
        try:
            from simpulse.core.telemetry.state_store import TelemetryStateStore
            TelemetryStateStore.get_instance().update_delta(packet)
        except Exception:
            pass

        # Check lap completion
        if cur_laps > prev_laps and prev_laps >= 0:
            self.lap_completed.emit(packet)

        # Check sector transition
        if cur_sector != prev_sector:
            sec_num = prev_sector
            sec_time = self.delta_engine.sector_1_time if sec_num == 1 else self.delta_engine.sector_2_time
            sec_delta = self.delta_engine.sector1_delta if sec_num == 1 else self.delta_engine.sector2_delta
            self.sector_completed.emit(sec_num, sec_time, sec_delta, "default")

        self.delta_updated.emit(packet)
        return packet

    def update_scoring_from_view(
        self,
        timing: BaseTimingState,
        grid: Optional[FullGridScoringState] = None,
    ) -> LapDeltaPacket:
        """Process the consolidated View in DeltaEngine, detect lap/sector transitions and
        return LapDeltaPacket. Same orchestration as update_scoring(), sourced from
        TelemetryStateStore.timing/.grid (already up to date at this point — the caller
        dispatches the raw packet to the Store before calling this) instead of a raw packet.
        """
        prev_laps = self.delta_engine._last_laps_completed
        prev_sector = self.delta_engine.current_sector
        prev_prof = self.delta_engine.current_profile

        self.delta_engine.update_scoring_from_view(timing, grid)

        if self.delta_engine.current_profile != prev_prof:
            self.reference_profile_changed.emit(self.current_profile)

        cur_laps = self.delta_engine._last_laps_completed
        cur_sector = self.delta_engine.current_sector

        packet = self._build_delta_packet(player_dist=self.delta_engine.last_scoring_dist)
        self._last_emitted_packet = packet
        try:
            from simpulse.core.telemetry.state_store import TelemetryStateStore
            TelemetryStateStore.get_instance().update_delta(packet)
        except Exception:
            pass

        # Check lap completion
        if cur_laps > prev_laps and prev_laps >= 0:
            self.lap_completed.emit(packet)

        # Check sector transition
        if cur_sector != prev_sector:
            sec_num = prev_sector
            sec_time = self.delta_engine.sector_1_time if sec_num == 1 else self.delta_engine.sector_2_time
            sec_delta = self.delta_engine.sector1_delta if sec_num == 1 else self.delta_engine.sector2_delta
            self.sector_completed.emit(sec_num, sec_time, sec_delta, "default")

        self.delta_updated.emit(packet)
        return packet

    def _build_delta_packet(self, player_dist: float = 0.0) -> LapDeltaPacket:
        """Construct immutable strongly-typed LapDeltaPacket from DeltaEngine current state."""
        de = self.delta_engine
        raw_delta = de.display_delta
        delta_str = "--:--.---"
        if de.has_reference:
            if abs(raw_delta) <= 0.0001:
                delta_str = "+0.000"
            elif raw_delta < 0:
                delta_str = f"-{abs(raw_delta):.3f}"
            else:
                delta_str = f"+{raw_delta:.3f}"

        ref_time = de.ref_lap_time
        ref_time_str = format_lap_time(ref_time) if (de.has_reference and ref_time < 999900.0) else "--:--.---"

        # Nicer aggregate view (one SectorInfo per box) — see DeltaEngine.sectors / SectorEngine.
        sec_list = de.sectors

        return LapDeltaPacket(
            live_delta=de.live_delta,
            display_delta=de.display_delta,
            delta_str=delta_str,
            has_reference=de.has_reference,
            reference_mode=de.reference_mode,
            ref_lap_time=ref_time,
            ref_lap_time_str=ref_time_str,
            estimated_lap_time=de.estimated_lap_time,
            estimated_lap_time_str=de.estimated_lap_time_str,
            expected_status=de.expected_lap_status,
            current_sector=de.current_sector,
            sector1_delta=de.sector1_delta,
            sector2_delta=de.sector2_delta,
            sector3_delta=de.sector3_delta,
            sector1_time=de.sector1_time_str,
            sector1_status=de.sector1_status,
            sector2_time=de.sector2_time_str,
            sector2_status=de.sector2_status,
            sector3_time=de.sector3_time_str,
            sector3_status=de.sector3_status,
            sectors_list=sec_list,
            last_lap_time=de.last_completed_lap_time,
            last_lap_time_str=de.last_completed_lap_time_str,
            last_lap_status=de.last_completed_lap_status,
            is_lap_freeze_active=de.is_lap_freeze_active,
            lap_flag=de._last_lap_flag,
            is_pit_lap=de.is_pit_lap,
            track_name=de.track_name,
            track_length=de.track_length,
            player_dist=player_dist,
            vehicle_name=de._vehicle_name,
            vehicle_class=de._vehicle_class,
            timestamp=time.time(),
        )
