"""
SimPad Race Engineer — LMU Lap Validity & Timing Role.
Pure stateless detection directly from the telemetry/scoring packet flags:
- "timing_in_progress" (Flag 2 from 0 or 1)
- "time_deleted" (Flag 0 or 1 from 2)
"""

import time
from typing import Optional, Dict, List, Union

from simpad_qt.builtin_plugins.race_engineer.base import BaseRole, EngineerMessage, RoleStatus, AudioEngineType
from simpad_qt.builtin_plugins.race_engineer.context import EngineerContext
from simpad_qt.builtin_plugins.race_engineer.registry import RoleRegistry
from simpad_qt.builtin_plugins.race_engineer.params import RoleParam, FloatRangeParam, ParamScalarValue
from simpad_qt.core.telemetry_channels import TelemetryChannel, ChannelRequirement
from simpad_qt.core.telemetry.state_store import TelemetryStateStore


@RoleRegistry.register(
    role_id="lap_validity",
    name="Lap Validity (Timing in progress / Time deleted)",
    description="Monitors official LMU lap validation flag: 'Timing in progress' vs 'Time deleted'.",
    default_priority=50,
)
class LapValidityRole(BaseRole):
    """
    100% Stateless Lap Validity Role:
    - Transition to flag 2 -> "timing_in_progress"
    - Transition to flag 0 or 1 -> "time_deleted"
    """

    def __init__(
        self,
        role_id: str = "lap_validity",
        name: str = "Lap Validity (Timing in progress / Time deleted)",
        description: str = "",
        priority: int = 50,
        enabled: bool = True,
        audio_engine: Optional[AudioEngineType] = None,
        busy_duration_sec: float = 1.8,
        **kwargs: ParamScalarValue,
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
        self._last_event_time: float = 0.0
        self._last_event_name: str = "IDLE"
        self._was_in_garage: bool = False
        self.busy_duration_sec = float(busy_duration_sec)

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
        ]

    def get_channel_requirements(self) -> List[ChannelRequirement]:
        return [
            ChannelRequirement(
                channel=TelemetryChannel.TELEMETRY,
                preferred_hz=100,
                required=True,
                reason="Real-time monitoring of lap flags (mCountLapFlag)",
            ),
            ChannelRequirement(
                channel=TelemetryChannel.COMPACT_SCORING,
                preferred_hz=10,
                required=False,
                reason="Scoring timing line crossing and lap flags",
            ),
        ]

    def get_sound_requirements(self) -> Dict[str, str]:
        return {
            "timing_in_progress": "Timing in progress",
            "time_deleted": "Time deleted",
            "give_time_back": "Cut track, give time back",
        }

    def is_busy(self) -> bool:
        """Returns True briefly during audio message playback duration."""
        return (time.time() - self._last_event_time) < self.busy_duration_sec

    def on_physics_tick(self, state: TelemetryStateStore, context: EngineerContext) -> Optional[EngineerMessage]:
        return self._evaluate_validity(state, context)

    def on_scoring_update(self, state: TelemetryStateStore, context: EngineerContext) -> Optional[EngineerMessage]:
        return self._evaluate_validity(state, context)

    def on_grid_update(self, state: TelemetryStateStore, context: EngineerContext) -> Optional[EngineerMessage]:
        return self._evaluate_validity(state, context)

    def update(self, context: EngineerContext) -> Optional[EngineerMessage]:
        return self._evaluate_validity(context.state_store, context)

    def _evaluate_validity(self, state: TelemetryStateStore, context: EngineerContext) -> Optional[EngineerMessage]:
        if not self.enabled:
            return None

        # Access central TelemetryStateStore
        state_store: TelemetryStateStore
        if context is not None:
            state_store = context.state_store
        elif isinstance(state, TelemetryStateStore):
            state_store = state
        else:
            from simpad_qt.core.telemetry.state_store import TelemetryStateStore
            state_store = TelemetryStateStore.get_instance()

        # Consume authoritative transition processed directly by the state store
        transition = state_store.consume_validity_transition()
        self._last_lap_flag = state_store.lap_flag
        if not transition:
            return None

        now = context.timestamp if (context and context.timestamp is not None) else time.time()
        self._last_event_time = now
        self._last_event_name = transition.upper()

        message = EngineerMessage(
            phrase_key=transition,
            priority=self.priority,
            interrupt=False,
            role_id=self.role_id,
        )
        self.emit_sound(transition, interrupt=False)
        return message

    def emit_sound(self, phrase_key: str, interrupt: bool = False) -> None:
        """Plays sound and logs event in track_limits_debug.log."""
        super().emit_sound(phrase_key, interrupt=interrupt)
        try:
            from simpad_qt.core.telemetry.track_limits_logger import TrackLimitsLogger
            TrackLimitsLogger.get_instance().log_spotter_action(
                phrase_key=phrase_key,
                interrupt=interrupt,
                context_info=f"Flag={self._last_lap_flag}",
            )
        except Exception:
            pass

    def reset(self) -> None:
        self._last_lap_flag = None
        self._last_event_time = 0.0
        self._last_event_name = "IDLE"
        self._was_in_garage = False
        from simpad_qt.core.telemetry.state_store import TelemetryStateStore
        TelemetryStateStore.get_instance().reset()

    def get_state_summary(self) -> Dict[str, Union[str, int, float, bool, List[str], None]]:
        summary = super().get_state_summary()
        from simpad_qt.core.telemetry.state_store import TelemetryStateStore
        st = TelemetryStateStore.get_instance()
        summary.update({
            "lap_flag": st.lap_flag,
            "lap_status_text": st.lap_status_text,
            "is_lap_valid": st.is_lap_valid,
            "is_lap_invalid": st.is_lap_invalid,
            "last_event": self._last_event_name if self._last_event_name != "IDLE" else st.last_validity_event,
            "is_busy": self.is_busy(),
        })
        return summary


# Sub-plugin alias
LapValiditySubplugin = LapValidityRole
