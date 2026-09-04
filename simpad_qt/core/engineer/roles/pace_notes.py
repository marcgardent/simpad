"""
SimPad Race Engineer — Pace Notes & Driving Markers Role (PaceNotesRole).
Announces voice markers from reference lap (Brake, Turn-In, Turns T1..T30, Gear shifts).
SOLID architecture (SRP, OCP, DIP).
"""

import time
import logging
from typing import Optional, Dict, Any, Set, List
from ..base import BaseRole, EngineerMessage, RoleStatus
from ..context import EngineerContext
from ..registry import RoleRegistry
from ..params import RoleParam, BoolParam, FloatRangeParam
from ...telemetry.reference_profile import (
    ReferenceLapProfile,
    TrackAnnotation,
    AnnotationType,
    clean_name_identifier,
)
from ...telemetry.lmu_parser import LMUParser

logger = logging.getLogger(__name__)


@RoleRegistry.register(
    "pace_notes",
    name="Pace Notes & Track Markers",
    description="Announces driving voice markers (Brake, Turn-in, Turns T1..T30, Gears) configured on track.",
    default_priority=80,
)
class PaceNotesRole(BaseRole):
    """
    Co-driver / track engineer role for braking, turn-in, turns, and gear markers.
    Anticipates markers based on vehicle speed for optimal trigger timing.
    """

    def __init__(
        self,
        role_id: str = "pace_notes",
        name: str = "Pace Notes & Track Markers",
        description: str = "Announces driving voice markers from reference lap.",
        priority: int = 80,
        enabled: bool = True,
        audio_engine: Optional[Any] = None,
        enable_brake: bool = True,
        enable_turn_in: bool = True,
        enable_turn: bool = True,
        enable_gear: bool = True,
        anticipation_time_sec: float = 0.8,
        min_lead_distance_m: float = 15.0,
        max_lead_distance_m: float = 75.0,
    ):
        super().__init__(
            role_id=role_id,
            name=name,
            description=description,
            priority=priority,
            enabled=enabled,
            audio_engine=audio_engine,
        )
        self.enable_brake = bool(enable_brake)
        self.enable_turn_in = bool(enable_turn_in)
        self.enable_turn = bool(enable_turn)
        self.enable_gear = bool(enable_gear)
        self.anticipation_time_sec = float(anticipation_time_sec)
        self.min_lead_distance_m = float(min_lead_distance_m)
        self.max_lead_distance_m = float(max_lead_distance_m)

        # Internal state
        self._triggered_ann_ids: Set[str] = set()
        self._last_laps_completed: int = -1
        self._last_announcement_time: float = 0.0
        self._last_announced_label: str = "None"
        self._last_announced_dist: float = -1.0
        self._last_ann_signature: List[Any] = []
        self._custom_profile: Optional[ReferenceLapProfile] = None

    def get_parameters(self) -> List[RoleParam]:
        """Declares list of configurable parameters for UI form."""
        return [
            BoolParam(
                name="enable_brake",
                label="Braking Announcements (Brake)",
                default=True,
                description="Enable voice announcement 'Brake' at braking markers",
            ),
            BoolParam(
                name="enable_turn_in",
                label="Turn-in Announcements (Turn-in)",
                default=True,
                description="Enable voice announcement 'Turn' at turn-in/apex markers",
            ),
            BoolParam(
                name="enable_turn",
                label="Turn Number Announcements (Turn 1..30)",
                default=True,
                description="Enable voice announcement of numbered turns 'Turn N'",
            ),
            BoolParam(
                name="enable_gear",
                label="Gear Announcements (Gear 1..8)",
                default=True,
                description="Enable voice announcement of recommended gear 'Gear N'",
            ),
            FloatRangeParam(
                name="anticipation_time_sec",
                label="Anticipation Time",
                min_val=0.2,
                max_val=3.0,
                step=0.1,
                unit="s",
                default=0.8,
                description="Anticipation delay proportional to vehicle speed",
            ),
            FloatRangeParam(
                name="min_lead_distance_m",
                label="Min Lead Distance",
                min_val=5.0,
                max_val=50.0,
                step=1.0,
                unit="m",
                default=15.0,
                description="Minimum anticipation distance at low speed",
            ),
            FloatRangeParam(
                name="max_lead_distance_m",
                label="Max Lead Distance",
                min_val=20.0,
                max_val=150.0,
                step=5.0,
                unit="m",
                default=75.0,
                description="Maximum anticipation distance at high speed",
            ),
        ]

    def set_reference_profile(self, profile: Optional[ReferenceLapProfile]) -> None:
        """Allows manual injection of a reference profile."""
        self._custom_profile = profile
        self.reset()

    def get_reference_profile(self, context: Optional[EngineerContext] = None) -> Optional[ReferenceLapProfile]:
        """Retrieves active reference profile with strict per-track isolation."""
        scoring_track = ""
        if context and context.scoring:
            scoring_track = str(context.scoring.track_name).strip()

        if self._custom_profile is not None:
            ref_track = getattr(self._custom_profile, "track_name", "")
            # If scoring packet explicitly indicates a different track, invalidate stale profile
            if scoring_track and ref_track and clean_name_identifier(scoring_track) != clean_name_identifier(ref_track):
                logger.warning(f"[PaceNotesRole] Invalidating custom profile for '{ref_track}' because active circuit is '{scoring_track}'")
                self._custom_profile = None
            else:
                return self._custom_profile

        if context:
            ctx_prof = context.get_reference_profile()
            if ctx_prof and ctx_prof.annotations:
                return ctx_prof

        delta_eng = getattr(LMUParser, "_delta_engine", None)
        if delta_eng:
            # 1. Current profile if it contains annotations
            if delta_eng.current_profile and delta_eng.current_profile.annotations:
                prof = delta_eng.current_profile
                ref_track = getattr(prof, "track_name", "")
                if not (scoring_track and ref_track and clean_name_identifier(scoring_track) != clean_name_identifier(ref_track)):
                    return prof

            # 2. Direct fallback to track reference/marks profile on disk (independent of delta mode)
            prof = delta_eng.all_time_best_profile or delta_eng.current_profile
            if prof and prof.annotations:
                ref_track = getattr(prof, "track_name", "")
                if not (scoring_track and ref_track and clean_name_identifier(scoring_track) != clean_name_identifier(ref_track)):
                    return prof

        return None

    def get_channel_requirements(self) -> List[Any]:
        try:
            from simpad_qt.core.telemetry_channels import TelemetryChannel, ChannelRequirement
            return [
                ChannelRequirement(
                    channel=TelemetryChannel.TELEMETRY,
                    preferred_hz=100,
                    required=True,
                    reason="Lap distance (lap_dist) and speed for marker anticipation",
                ),
                ChannelRequirement(
                    channel=TelemetryChannel.COMPACT_SCORING,
                    preferred_hz=10,
                    required=False,
                    reason="Lap length and track validation",
                ),
            ]
        except ImportError:
            return []

    def get_sound_requirements(self) -> Dict[str, str]:
        sounds = {
            "brake": "Brake",
            "turn": "Turn",
        }
        for i in range(1, 31):
            sounds[f"turn_{i}"] = f"Turn {i}"
        for i in range(1, 9):
            sounds[f"gear_{i}"] = f"Gear {i}"
        return sounds

    def reset(self) -> None:
        """Resets triggered markers and role state."""
        self._triggered_ann_ids.clear()
        self._last_laps_completed = -1
        self._last_announcement_time = 0.0
        self._last_announced_label = "None"
        self._last_announced_dist = -1.0
        self._last_ann_signature = []

    def is_busy(self) -> bool:
        """Indicates if a voice announcement was emitted recently (< 1.2s)."""
        return (time.time() - self._last_announcement_time) < 1.2

    def _compute_lead_distance(self, speed_mps: float) -> float:
        """Calculates optimal anticipation distance in meters based on vehicle speed."""
        dist = speed_mps * self.anticipation_time_sec
        return max(self.min_lead_distance_m, min(self.max_lead_distance_m, dist))

    def on_physics_tick(self, state: Any, context: EngineerContext) -> Optional[EngineerMessage]:
        """Physics tick evaluation (100-120Hz TelemInfo). Real-time lap distance and speed for pace note trigger."""
        return self._evaluate_pace_notes(state, context)

    def on_scoring_update(self, state: Any, context: EngineerContext) -> Optional[EngineerMessage]:
        """Scoring update evaluation (CompactScoring 10Hz). Lap transition and track length sync."""
        return self._evaluate_pace_notes(state, context)

    def update(self, context: EngineerContext) -> Optional[EngineerMessage]:
        """Polymorphic entry point for direct/manual evaluations."""
        return self._evaluate_pace_notes(context.state_store, context)

    def _evaluate_pace_notes(self, state: Any, context: EngineerContext) -> Optional[EngineerMessage]:
        """
        Evaluates player position relative to track markers on each tick.
        """
        if not self.enabled:
            return None

        # Retrieve player vehicle and position info
        player_veh = context.get_player_vehicle()
        if not player_veh:
            return None

        if context.is_player_in_garage() or context.is_player_in_pits():
            return None

        # Reset triggered markers on new lap
        laps_comp = player_veh.total_laps
        if self._last_laps_completed >= 0 and laps_comp != self._last_laps_completed:
            self._triggered_ann_ids.clear()
        self._last_laps_completed = laps_comp

        profile = self.get_reference_profile(context)
        if not profile or not profile.annotations:
            return None

        # Dynamic detection if marker list or positions changed in real-time
        curr_ann_signature = [(a.id, round(a.distance, 1), a.type.value, a.gear) for a in profile.annotations]
        if curr_ann_signature != self._last_ann_signature:
            self._last_ann_signature = curr_ann_signature
            self._triggered_ann_ids.clear()

        track_len = context.get_track_length()
        if (track_len <= 0.0 or track_len == 5000.0) and profile.track_length > 0.0:
            track_len = profile.track_length

        player_dist = player_veh.lap_dist % track_len
        player_speed = context.get_player_speed_mps()

        # If player is nearly stopped (< 2 m/s), do not anticipate
        if player_speed < 2.0:
            return None

        lead_dist = self._compute_lead_distance(player_speed)
        now = context.timestamp

        # Prevent overlapping two announcements instantly (< 0.35s to allow Brake -> Gear sequence)
        if (now - self._last_announcement_time) < 0.35:
            return None

        # Find closest marker in anticipation window [0, lead_dist]
        candidates = []
        for ann in profile.annotations:
            if ann.id in self._triggered_ann_ids:
                continue

            # Filter according to user configuration
            if ann.type == AnnotationType.BRAKE and not self.enable_brake:
                continue
            if ann.type == AnnotationType.TURN_IN and not self.enable_turn_in:
                continue
            if ann.type == AnnotationType.TURN and not self.enable_turn:
                continue
            if ann.type == AnnotationType.GEAR and not self.enable_gear:
                continue

            marker_dist = ann.distance % track_len
            delta_dist = (marker_dist - player_dist) % track_len

            if 0.0 <= delta_dist <= lead_dist:
                candidates.append((delta_dist, ann))

        if not candidates:
            return None

        # Sort by proximity
        candidates.sort(key=lambda item: item[0])
        _, target_ann = candidates[0]

        # Trigger announcement
        phrase_key = profile.get_annotation_phrase_key(target_ann)
        display_label = profile.get_annotation_display_label(target_ann)

        self._triggered_ann_ids.add(target_ann.id)
        self._last_announcement_time = now
        self._last_announced_label = display_label
        self._last_announced_dist = target_ann.distance

        self.emit_sound(phrase_key, interrupt=False)

        return EngineerMessage(
            phrase_key=phrase_key,
            priority=self.priority,
            interrupt=False,
            text_override=f"Marker: {display_label} at {target_ann.distance:.0f}m",
            role_id=self.role_id,
            timestamp=now,
        )

    def get_state_summary(self) -> Dict[str, Any]:
        """Returns serializable summary for graphical interface."""
        summary = super().get_state_summary()
        profile = self.get_reference_profile()
        num_markers = len(profile.annotations) if (profile and profile.annotations) else 0
        summary.update({
            "num_markers": num_markers,
            "triggered_count": len(self._triggered_ann_ids),
            "last_announced_label": self._last_announced_label,
            "last_announced_dist": self._last_announced_dist,
            "anticipation_time_sec": self.anticipation_time_sec,
        })
        return summary

    def get_config(self) -> Dict[str, Any]:
        """Returns exportable configuration dictionary."""
        config = super().get_config()
        config.update({
            "anticipation_time_sec": self.anticipation_time_sec,
            "min_lead_distance_m": self.min_lead_distance_m,
            "max_lead_distance_m": self.max_lead_distance_m,
        })
        return config

    def set_config(self, config: Dict[str, Any]) -> None:
        """Applies external configuration dictionary."""
        super().set_config(config)
        if "anticipation_time_sec" in config:
            self.anticipation_time_sec = float(config["anticipation_time_sec"])
        if "min_lead_distance_m" in config:
            self.min_lead_distance_m = float(config["min_lead_distance_m"])
        if "max_lead_distance_m" in config:
            self.max_lead_distance_m = float(config["max_lead_distance_m"])
