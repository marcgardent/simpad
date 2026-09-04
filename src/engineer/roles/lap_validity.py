"""
SimPad Race Engineer — LMU Race Control, Lap Validity & Track Limits Role.
Monitors LMU official Race Control flags (mCountLapFlag), infraction steps (track_limits_steps),
and race penalties (num_penalties).
Strictly event-driven and synchronized with the official WEC rule thresholds.
"""

import time
from enum import Enum
from typing import Optional, Dict, Any, List, Union

from src.engineer.base import BaseRole, EngineerMessage, RoleStatus
from src.engineer.context import EngineerContext, get_vehicle_attr
from src.engineer.registry import RoleRegistry
from src.engineer.params import RoleParam, FloatRangeParam, BoolParam


class IncidentState(str, Enum):
    IDLE = "IDLE"                    # Green / Normal / Nominal (Flag=2)
    INVESTIGATION = "INVESTIGATION"  # Yellow / Slow-down window (Flag=1)
    PENALTY = "PENALTY"              # Red / Lap deleted / Sanction (Flag=0 or Steps/Penalties)


@RoleRegistry.register(
    role_id="lap_validity",
    name="Lap Validity (Clean / Dirty Lap & Track Limits)",
    description="Monitors LMU Race Control validation, infraction steps, and penalties.",
    default_priority=50,
)
class LapValidityRole(BaseRole):
    """
    Role responsible for lap validity, actionable slow-down prompts, and official LMU penalties.
    """

    def __init__(
        self,
        role_id: str = "lap_validity",
        name: str = "Lap Validity (Clean / Dirty Lap & Track Limits)",
        description: str = "",
        priority: int = 50,
        enabled: bool = True,
        audio_engine: Optional[Any] = None,
        busy_duration_sec: float = 1.8,
        announce_investigation: bool = True,
        announce_cleared: bool = True,
        announce_penalty: bool = True,
        use_actionable_prompt: bool = True,
        investigation_debounce_sec: float = 0.0,
    ):
        super().__init__(
            role_id=role_id,
            name=name,
            description=description,
            priority=priority,
            enabled=enabled,
            audio_engine=audio_engine,
        )
        self._last_lap_flag: Optional[int] = None
        self._last_steps: Optional[int] = None
        self._last_penalties: Optional[int] = None
        self._last_incident_state: IncidentState = IncidentState.IDLE
        self._is_lap_dirty: bool = False
        self._last_lap_num: Optional[int] = None
        self._last_event_time: float = 0.0
        self._last_event_name: str = "IDLE"
        self._investigation_start_time: float = 0.0
        self._investigation_announced: bool = False

        self.busy_duration_sec = float(busy_duration_sec)
        self.announce_investigation = bool(announce_investigation)
        self.announce_cleared = bool(announce_cleared)
        self.announce_penalty = bool(announce_penalty)
        self.use_actionable_prompt = bool(use_actionable_prompt)
        self.investigation_debounce_sec = float(investigation_debounce_sec)

    def get_parameters(self) -> List[RoleParam]:
        return [
            FloatRangeParam(
                name="busy_duration_sec",
                label="Audio Lock Duration",
                min_val=0.5,
                max_val=5.0,
                step=0.1,
                unit="s",
                default=1.8,
                description="BUSY state duration during audio speech playback",
            ),
            FloatRangeParam(
                name="investigation_debounce_sec",
                label="Cut Alert Grace Period",
                min_val=0.0,
                max_val=3.0,
                step=0.1,
                unit="s",
                default=2.0,
                description="Grace period allowing the driver to naturally lift before shouting 'Give time back' (suppresses alerts if cleared in green)",
            ),
            BoolParam(
                name="announce_investigation",
                label="Investigation Alert (Give Time Back)",
                default=True,
                description="Immediate alert upon yellow status to lift throttle and clear violation",
            ),
            BoolParam(
                name="announce_cleared",
                label="Incident Cleared Announcement (Cleared / No Penalty)",
                default=True,
                description="Confirmation announcement when incident is cleared without penalty",
            ),
            BoolParam(
                name="announce_penalty",
                label="Penalty / Lap Invalidated Announcement",
                default=True,
                description="Voice announcement when lap is deleted or penalty is applied",
            ),
            BoolParam(
                name="use_actionable_prompt",
                label="Actionable Directives ('Give time back')",
                default=True,
                description="Uses actionable prompts ('Give time back') instead of passive notification",
            ),
        ]

    def get_channel_requirements(self) -> List[Any]:
        try:
            from simpad_qt.core.telemetry_channels import TelemetryChannel, ChannelRequirement
            return [
                ChannelRequirement(
                    channel=TelemetryChannel.TELEMETRY,
                    preferred_hz=100,
                    required=True,
                    reason="Real-time monitoring of lap flags (mCountLapFlag) and track limit infractions",
                ),
                ChannelRequirement(
                    channel=TelemetryChannel.COMPACT_SCORING,
                    preferred_hz=10,
                    required=False,
                    reason="Timing line crossing detection and sectors",
                ),
            ]
        except ImportError:
            return []

    def get_sound_requirements(self) -> Dict[str, str]:
        return {
            "clean_lap": "Clean lap",
            "dirty_lap": "Dirty lap",
            "give_time_back": "Cut track, give time back",
            "under_investigation": "Under investigation, lift",
            "incident_cleared": "Incident cleared",
            "time_cleared": "Time given back, cleared",
            "no_penalty": "No penalty",
            "lap_deleted": "Lap deleted",
            "penalty_applied": "Penalty applied",
        }

    def is_busy(self) -> bool:
        """Returns True briefly during audio message playback duration."""
        return (time.time() - self._last_event_time) < self.busy_duration_sec

    def _normalize_incident_state(self, val: Any) -> Optional[IncidentState]:
        """Normalizes raw telemetry/API value to IncidentState."""
        if val is None:
            return None

        if isinstance(val, IncidentState):
            return val

        if isinstance(val, bool):
            return IncidentState.INVESTIGATION if val else IncidentState.IDLE

        if isinstance(val, (int, float)):
            ival = int(val)
            if ival == 0:
                return IncidentState.IDLE
            elif ival == 1:
                return IncidentState.INVESTIGATION
            elif ival >= 2:
                return IncidentState.PENALTY
            return IncidentState.IDLE

        if isinstance(val, str):
            s = val.strip().lower()
            if s in ("green", "idle", "none", "clean", "valid", "0", "false", "ok"):
                return IncidentState.IDLE
            elif s in ("yellow", "investigation", "under_investigation", "warning", "cut", "give_time_back", "1"):
                return IncidentState.INVESTIGATION
            elif s in ("orange", "red", "penalty", "penalized", "dirty", "invalid", "invalidated", "2", "3"):
                return IncidentState.PENALTY

        return None

    def _extract_lap_number(self, context: EngineerContext) -> Optional[int]:
        """Extracts lap number or lap count to reset status at the beginning of lap."""
        if context.telemetry:
            if hasattr(context.telemetry, "laps_completed"):
                return int(context.telemetry.laps_completed)
            if hasattr(context.telemetry, "total_laps"):
                return int(context.telemetry.total_laps)
        if context.scoring:
            player_veh = context.get_player_vehicle()
            if player_veh:
                tot = get_vehicle_attr(player_veh, "total_laps", None)
                if tot is not None:
                    return int(tot)
        return None

    def update(self, context: EngineerContext) -> Optional[EngineerMessage]:
        if not self.enabled:
            return None

        now = time.time()

        # 1. Handle lap transition (Start/Finish line crossing)
        current_lap_num = self._extract_lap_number(context)
        if current_lap_num is not None:
            if self._last_lap_num is not None and current_lap_num != self._last_lap_num:
                # New lap started -> Reset lap invalidation
                self._is_lap_dirty = False
                self._last_incident_state = IncidentState.IDLE
                self._investigation_announced = False
                self._investigation_start_time = 0.0
                try:
                    from src.telemetry.track_limits_logger import TrackLimitsLogger
                    TrackLimitsLogger.get_instance().log_spotter_decision(
                        action="NEW_LAP_RESET",
                        reason=f"Crossed start/finish line into Lap {current_lap_num}",
                        details="Lap validity reset to CLEAN",
                    )
                except Exception:
                    pass
            self._last_lap_num = current_lap_num

        # 2. Extract official validity flag (0=Dirty/Delete, 1=Under Investigation/Cut, 2=Valid/Clean)
        current_flag: Optional[int] = None
        if context.telemetry and hasattr(context.telemetry, "lap_flag") and context.telemetry.lap_flag is not None:
            try:
                current_flag = int(context.telemetry.lap_flag)
            except (ValueError, TypeError):
                pass

        player_veh = context.get_player_vehicle() if context.scoring else None
        if current_flag is None and player_veh is not None:
            raw_flag = get_vehicle_attr(player_veh, "count_lap_flag", None)
            if raw_flag is not None:
                try:
                    current_flag = int(raw_flag)
                except (ValueError, TypeError):
                    pass

        # 3. Extract LMU steps & penalties
        current_steps: int = 0
        if context.telemetry and hasattr(context.telemetry, "track_limits_steps"):
            try:
                current_steps = int(context.telemetry.track_limits_steps)
            except (ValueError, TypeError):
                pass
        elif player_veh is not None:
            raw_steps = get_vehicle_attr(player_veh, "track_limits_steps", 0)
            try:
                current_steps = int(raw_steps)
            except (ValueError, TypeError):
                pass

        current_penalties: int = 0
        if context.telemetry and hasattr(context.telemetry, "num_penalties"):
            try:
                current_penalties = int(context.telemetry.num_penalties)
            except (ValueError, TypeError):
                pass
        elif player_veh is not None:
            raw_pens = get_vehicle_attr(player_veh, "num_penalties", 0)
            try:
                current_penalties = int(raw_pens)
            except (ValueError, TypeError):
                pass

        steps_per_point: int = 3
        steps_per_penalty: int = 12
        if context.telemetry and getattr(context.telemetry, "track_limits_steps_per_point", 0) > 0:
            steps_per_point = int(context.telemetry.track_limits_steps_per_point)
            steps_per_penalty = int(getattr(context.telemetry, "track_limits_steps_per_penalty", 12))
        elif context.scoring and hasattr(context.scoring, "lmu") and context.scoring.lmu:
            if getattr(context.scoring.lmu, "track_limits_steps_per_point", 0) > 0:
                steps_per_point = int(context.scoring.lmu.track_limits_steps_per_point)
            if getattr(context.scoring.lmu, "track_limits_steps_per_penalty", 0) > 0:
                steps_per_penalty = int(context.scoring.lmu.track_limits_steps_per_penalty)

        # 4. Extract raw incident state if present
        raw_incident: Any = None
        if context.telemetry:
            for attr in ("track_cut_state", "incident_state", "cut_state", "investigation_state", "offtrack_state"):
                if hasattr(context.telemetry, attr):
                    val = getattr(context.telemetry, attr)
                    if val is not None:
                        raw_incident = val
                        break

        if raw_incident is None and player_veh is not None:
            for attr in ("track_cut_state", "incident_state", "cut_state", "investigation_state", "mTrackCutState", "mIncidentState"):
                val = get_vehicle_attr(player_veh, attr, None)
                if val is not None:
                    raw_incident = val
                    break

        norm_incident = self._normalize_incident_state(raw_incident)

        # Infallible incident state resolution:
        if norm_incident == IncidentState.IDLE and (current_flag != 0 or current_flag is None):
            current_incident_state = IncidentState.IDLE
        elif current_flag == 1 or norm_incident == IncidentState.INVESTIGATION:
            current_incident_state = IncidentState.INVESTIGATION
        elif current_flag == 0 or norm_incident == IncidentState.PENALTY:
            current_incident_state = IncidentState.PENALTY
        elif current_flag == 2:
            current_incident_state = IncidentState.IDLE
        elif norm_incident is not None:
            current_incident_state = norm_incident
        else:
            current_incident_state = self._last_incident_state

        # Silent initialization on very first received frame
        if self._last_lap_flag is None and self._last_event_time == 0.0:
            self._last_lap_flag = current_flag
            self._last_steps = current_steps
            self._last_penalties = current_penalties
            if current_flag == 0 or current_incident_state == IncidentState.PENALTY:
                self._is_lap_dirty = True
            self._last_incident_state = current_incident_state
            if current_incident_state == IncidentState.INVESTIGATION:
                self._investigation_announced = True
            return None

        # 5. Step increment detection (LMU recorded an infraction step)
        if self._last_steps is not None and current_steps > self._last_steps:
            delta_steps = current_steps - self._last_steps
            self._is_lap_dirty = True
            curr_strikes = current_steps // steps_per_point if steps_per_point > 0 else 0
            max_strikes = steps_per_penalty // steps_per_point if steps_per_point > 0 else 0
            try:
                from src.telemetry.track_limits_logger import TrackLimitsLogger
                TrackLimitsLogger.get_instance().log_spotter_decision(
                    action="STEP_INCREMENTED",
                    reason=f"LMU recorded infraction (+{delta_steps} steps)",
                    details=f"Total Steps: {current_steps}, Strike {curr_strikes}/{max_strikes}",
                )
            except Exception:
                pass

        # 6. Official penalty count increment detection
        if self._last_penalties is not None and current_penalties > self._last_penalties:
            self._last_penalties = current_penalties
            self._last_event_time = now
            self._last_event_name = "PENALTY_APPLIED"
            try:
                from src.telemetry.track_limits_logger import TrackLimitsLogger
                TrackLimitsLogger.get_instance().log_spotter_decision(
                    action="PENALTY_APPLIED",
                    reason="Official penalty issued by Race Control (num_penalties incremented)",
                    details=f"Active Penalties: {current_penalties}",
                )
            except Exception:
                pass
            if self.announce_penalty:
                self.emit_sound("penalty_applied", interrupt=True)
                return EngineerMessage(
                    phrase_key="penalty_applied",
                    priority=self.priority + 20,
                    interrupt=True,
                    role_id=self.role_id,
                )

        message: Optional[EngineerMessage] = None

        # 7. Two-level state machine (Investigation & Lap Validity)
        if current_incident_state is not None:
            if current_incident_state != self._last_incident_state:
                prev_state = self._last_incident_state
                self._last_incident_state = current_incident_state

                # A. Transition to INVESTIGATION
                if current_incident_state == IncidentState.INVESTIGATION:
                    self._investigation_start_time = now
                    self._investigation_announced = False
                    try:
                        from src.telemetry.track_limits_logger import TrackLimitsLogger
                        TrackLimitsLogger.get_instance().log_spotter_decision(
                            action="INVESTIGATION_OPENED",
                            reason="Investigation state opened",
                            details=f"Debounce: {self.investigation_debounce_sec}s",
                        )
                    except Exception:
                        pass

                    if self.investigation_debounce_sec <= 0.0 and self.announce_investigation:
                        self._investigation_announced = True
                        phrase_key = "give_time_back" if self.use_actionable_prompt else "under_investigation"
                        self._last_event_time = now
                        self._last_event_name = "INVESTIGATION"
                        message = EngineerMessage(
                            phrase_key=phrase_key,
                            priority=self.priority + 10,
                            interrupt=True,
                            role_id=self.role_id,
                        )
                        self.emit_sound(phrase_key, interrupt=True)

                # B. Transition INVESTIGATION -> IDLE (Cleared / Time given back)
                elif prev_state == IncidentState.INVESTIGATION and current_incident_state == IncidentState.IDLE:
                    if self._investigation_announced or self.investigation_debounce_sec <= 0.0:
                        if self.announce_cleared:
                            if not self._is_lap_dirty:
                                phrase_key = "time_cleared" if self.use_actionable_prompt else "incident_cleared"
                                self._last_event_name = "TIME_CLEARED_CLEAN"
                            else:
                                phrase_key = "no_penalty"
                                self._last_event_name = "TIME_CLEARED_DIRTY"

                            self._last_event_time = now
                            try:
                                from src.telemetry.track_limits_logger import TrackLimitsLogger
                                TrackLimitsLogger.get_instance().log_spotter_decision(
                                    action="TIME_CLEARED",
                                    reason="Incident cleared without further penalty",
                                    details=f"Announced: {phrase_key}, LapDirty={self._is_lap_dirty}",
                                )
                            except Exception:
                                pass
                            message = EngineerMessage(
                                phrase_key=phrase_key,
                                priority=self.priority,
                                interrupt=False,
                                role_id=self.role_id,
                            )
                            self.emit_sound(phrase_key, interrupt=False)
                    else:
                        try:
                            from src.telemetry.track_limits_logger import TrackLimitsLogger
                            TrackLimitsLogger.get_instance().log_spotter_decision(
                                action="SUPPRESSED_GREEN",
                                reason="Incident resolved in green before grace period elapsed - audio suppressed",
                                details=f"Duration: {now - self._investigation_start_time:.2f}s, LapDirty={self._is_lap_dirty}",
                            )
                        except Exception:
                            pass

                    self._investigation_start_time = 0.0
                    self._investigation_announced = False

                # C. Transition to PENALTY (Sanction confirmed / Lap deleted)
                elif current_incident_state == IncidentState.PENALTY:
                    self._investigation_start_time = 0.0
                    self._investigation_announced = False

                    if not self._is_lap_dirty:
                        self._is_lap_dirty = True
                        phrase_key = "lap_deleted" if self.use_actionable_prompt else "dirty_lap"
                        self._last_event_name = "LAP_DELETED"
                        self._last_event_time = now
                        try:
                            from src.telemetry.track_limits_logger import TrackLimitsLogger
                            TrackLimitsLogger.get_instance().log_spotter_decision(
                                action="LAP_DELETED",
                                reason="Lap time deleted / invalidated",
                                details=f"Phrase: {phrase_key}",
                            )
                        except Exception:
                            pass
                        if self.announce_penalty:
                            message = EngineerMessage(
                                phrase_key=phrase_key,
                                priority=self.priority,
                                interrupt=False,
                                role_id=self.role_id,
                            )
                            self.emit_sound(phrase_key, interrupt=False)
                    elif prev_state != IncidentState.PENALTY:
                        phrase_key = "penalty_applied"
                        self._last_event_name = "PENALTY_APPLIED"
                        self._last_event_time = now
                        try:
                            from src.telemetry.track_limits_logger import TrackLimitsLogger
                            TrackLimitsLogger.get_instance().log_spotter_decision(
                                action="PENALTY_APPLIED",
                                reason="Incident escalated to penalty on already deleted lap",
                                details=f"Phrase: {phrase_key}",
                            )
                        except Exception:
                            pass
                        if self.announce_penalty:
                            message = EngineerMessage(
                                phrase_key=phrase_key,
                                priority=self.priority,
                                interrupt=False,
                                role_id=self.role_id,
                            )
                            self.emit_sound(phrase_key, interrupt=False)

            # Ongoing investigation debounce check
            elif current_incident_state == IncidentState.INVESTIGATION and not self._investigation_announced:
                if (now - self._investigation_start_time) >= self.investigation_debounce_sec:
                    if self.announce_investigation:
                        self._investigation_announced = True
                        phrase_key = "give_time_back" if self.use_actionable_prompt else "under_investigation"
                        self._last_event_time = now
                        self._last_event_name = "INVESTIGATION"
                        try:
                            from src.telemetry.track_limits_logger import TrackLimitsLogger
                            TrackLimitsLogger.get_instance().log_spotter_decision(
                                action="INVESTIGATION_PROMPT",
                                reason=f"Grace period elapsed ({self.investigation_debounce_sec}s) - shouting directive",
                                details=f"Phrase: {phrase_key}",
                            )
                        except Exception:
                            pass
                        message = EngineerMessage(
                            phrase_key=phrase_key,
                            priority=self.priority + 10,
                            interrupt=True,
                            role_id=self.role_id,
                        )
                        self.emit_sound(phrase_key, interrupt=True)

        self._last_lap_flag = current_flag
        self._last_steps = current_steps
        self._last_penalties = current_penalties

        return message

    def emit_sound(self, phrase_key: str, interrupt: bool = False) -> None:
        """Plays sound and logs event in track_limits_debug.log."""
        super().emit_sound(phrase_key, interrupt=interrupt)
        try:
            from src.telemetry.track_limits_logger import TrackLimitsLogger
            TrackLimitsLogger.get_instance().log_spotter_action(
                phrase_key=phrase_key,
                interrupt=interrupt,
                context_info=f"LapDirty={self._is_lap_dirty}, IncidentState={self._last_incident_state.value}",
            )
        except Exception:
            pass

    def reset(self) -> None:
        self._last_lap_flag = None
        self._last_steps = None
        self._last_penalties = None
        self._last_incident_state = IncidentState.IDLE
        self._is_lap_dirty = False
        self._last_lap_num = None
        self._last_event_time = 0.0
        self._last_event_name = "IDLE"
        self._investigation_start_time = 0.0
        self._investigation_announced = False

    def get_state_summary(self) -> Dict[str, Any]:
        summary = super().get_state_summary()
        flag_str = "Unknown"
        if self._last_lap_flag == 2:
            flag_str = "Invalid (Dirty)" if self._is_lap_dirty else "Valid (Clean)"
        elif self._last_lap_flag in (0, 1):
            flag_str = "Invalid (Dirty)"

        summary.update({
            "lap_flag": self._last_lap_flag,
            "lap_status_text": flag_str,
            "is_lap_dirty": self._is_lap_dirty,
            "incident_state": self._last_incident_state.value,
            "last_event": self._last_event_name,
            "is_busy": self.is_busy(),
        })
        return summary


