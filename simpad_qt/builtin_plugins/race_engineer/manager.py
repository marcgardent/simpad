"""
SimPad Race Engineer — Main Race Engineer Coordinator (RaceEngineer).
Manages ordered collection of Roles, lifecycle, prioritization,
audio message arbitration, and global IDLE/BUSY state.
"""

import time
import json
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Union, Tuple
from isimotor_rawudp_client import TelemInfo, FullScoringSession, CompactScoring
from .base import BaseRole, EngineerMessage, RoleStatus, AudioEngineType
from .context import EngineerContext, TelemetryTriggerPacket
from .factory import RoleFactory
from simpad_qt.core.telemetry.state_store import TelemetryStateStore, TelemetryWakeReason
from simpad_qt.core.telemetry.reference_profile import ReferenceLapProfile
from simpad_qt.core.telemetry_channels import ChannelRequirement, TelemetryChannel
from .params import ParamScalarValue
from simpad_qt.core.utils.audio import AudioAnnouncer

logger = logging.getLogger(__name__)

_PACKET_WAKE_REASONS = {
    TelemInfo: TelemetryWakeReason.PHYSICS_TICK,
    FullScoringSession: TelemetryWakeReason.GRID_UPDATE,
    CompactScoring: TelemetryWakeReason.SCORING_UPDATE,
}

_SCORING_STORE_UPDATERS = {
    FullScoringSession: lambda store, s, now: store.update_full_scoring(s, now),
    CompactScoring: lambda store, s, now: store.update_compact_scoring(s, now),
}


@dataclass
class _ChannelAggregation:
    preferred_hz: int
    required: bool
    reasons: List[str] = field(default_factory=list)


class RaceEngineer:
    """
    Main coordinator for virtual race engineer.
    Manages role execution by descending priority, audio arbitration, and global state.
    """

    def __init__(
        self,
        audio_engine: Optional[AudioEngineType] = None,
        auto_load_builtin_roles: bool = True,
        config_path: Optional[Path] = None,
        auto_load_config: bool = True,
    ):
        self.enabled: bool = True
        self.audio_engine = audio_engine if audio_engine is not None else AudioAnnouncer
        self.config_path = Path(config_path) if config_path is not None else None
        self._roles: List[BaseRole] = []
        self._last_processed_time: float = 0.0

        if auto_load_builtin_roles:
            self._roles = RoleFactory.create_all_roles(audio_engine=self.audio_engine)
            if auto_load_config and self.config_path and self.config_path.exists():
                self.load_from_file(self.config_path)
            else:
                self._sort_roles()

    def _sort_roles(self) -> None:
        """Sorts role list by descending priority."""
        self._roles.sort(key=lambda r: r.priority, reverse=True)

    def get_roles(self) -> List[BaseRole]:
        """Returns role list ordered by priority."""
        return list(self._roles)

    def get_role(self, role_id: str) -> Optional[BaseRole]:
        """Searches for a role by identifier."""
        for r in self._roles:
            if r.role_id == role_id:
                return r
        return None

    def add_role(self, role: BaseRole) -> None:
        """Adds a custom role and reorders by priority."""
        # Replace if already present
        self._roles = [r for r in self._roles if r.role_id != role.role_id]
        role.audio_engine = self.audio_engine
        self._roles.append(role)
        self._sort_roles()

    def remove_role(self, role_id: str) -> bool:
        """Removes a role from engineer."""
        before = len(self._roles)
        self._roles = [r for r in self._roles if r.role_id != role_id]
        return len(self._roles) < before

    def set_role_enabled(self, role_id: str, enabled: bool, auto_save: bool = True) -> None:
        """Enables or disables a specific role."""
        role = self.get_role(role_id)
        if role:
            role.enabled = enabled
            if not enabled:
                role.reset()
            if auto_save and self.config_path:
                self.save_to_file()

    # Sub-plugin alias methods
    get_subplugins = get_roles
    get_subplugin = get_role
    add_subplugin = add_role
    remove_subplugin = remove_role
    set_subplugin_enabled = set_role_enabled

    def move_role_up(self, role_id: str, auto_save: bool = True) -> bool:
        """
        Increases priority of a role by swapping with role above.
        """
        for i, r in enumerate(self._roles):
            if r.role_id == role_id and i > 0:
                # Swap priorities
                prev_role = self._roles[i - 1]
                # Ensure strict priority difference
                if r.priority <= prev_role.priority:
                    new_prio = prev_role.priority + 10
                    r.priority = new_prio
                else:
                    r.priority, prev_role.priority = prev_role.priority, r.priority

                self._sort_roles()
                if auto_save and self.config_path:
                    self.save_to_file()
                return True
        return False

    def move_role_down(self, role_id: str, auto_save: bool = True) -> bool:
        """
        Decreases priority of a role by swapping with role below.
        """
        for i, r in enumerate(self._roles):
            if r.role_id == role_id and i < len(self._roles) - 1:
                next_role = self._roles[i + 1]
                if r.priority >= next_role.priority:
                    new_prio = max(0, next_role.priority - 10)
                    r.priority = new_prio
                else:
                    r.priority, next_role.priority = next_role.priority, r.priority

                self._sort_roles()
                if auto_save and self.config_path:
                    self.save_to_file()
                return True
        return False

    def reorder_roles(self, ordered_role_ids: List[str], auto_save: bool = True) -> None:
        """
        Reassigns priorities across all roles according to provided order.
        First element receives highest priority (e.g. 100, 90, 80...).
        """
        base_priority = max(100, (len(ordered_role_ids) + len(self._roles)) * 10)
        for index, r_id in enumerate(ordered_role_ids):
            role = self.get_role(r_id)
            if role:
                role.priority = base_priority - (index * 10)
        self._sort_roles()
        if auto_save and self.config_path:
            self.save_to_file()

    def is_any_role_busy(self) -> bool:
        """Indicates whether at least one active role is in BUSY state."""
        return any(r.enabled and r.is_busy() for r in self._roles)

    def get_busy_roles(self) -> List[BaseRole]:
        """Returns list of currently busy roles."""
        return [r for r in self._roles if r.enabled and r.is_busy()]

    # =========================================================================
    # Aggregation of Sub-Plugin Requirements (Channels & Sounds)
    # =========================================================================

    def get_channel_requirements(self) -> List[ChannelRequirement]:
        """
        Aggregates all telemetry channel requirements declared by active sub-plugins.
        Merges identical channels by selecting maximum required sampling rate.
        """
        channel_map: Dict[TelemetryChannel, _ChannelAggregation] = {}

        for role in self._roles:
            if not role.enabled:
                continue

            reqs = role.get_channel_requirements()
            for req in reqs:
                ch = req.channel
                if ch not in channel_map:
                    channel_map[ch] = _ChannelAggregation(
                        preferred_hz=req.preferred_hz,
                        required=req.required,
                        reasons=[f"[{role.name}] {req.reason}"] if req.reason else [f"[{role.name}]"],
                    )
                else:
                    channel_map[ch].preferred_hz = max(channel_map[ch].preferred_hz, req.preferred_hz)
                    channel_map[ch].required = channel_map[ch].required or req.required
                    if req.reason:
                        channel_map[ch].reasons.append(f"[{role.name}] {req.reason}")

        aggregated: List[ChannelRequirement] = []
        for ch, data in channel_map.items():
            aggregated.append(
                ChannelRequirement(
                    channel=ch,
                    preferred_hz=data.preferred_hz,
                    required=data.required,
                    reason="; ".join(data.reasons),
                )
            )
        return aggregated

    def get_all_sound_requirements(self, only_enabled: bool = False) -> Dict[str, str]:
        """
        Aggregates all speech phrases required by sub-plugins.
        Returns a dictionary {phrase_key: text_to_synthesize}.
        """
        aggregated_sounds: Dict[str, str] = {}
        for role in self._roles:
            if only_enabled and not role.enabled:
                continue
            role_sounds = role.get_sound_requirements()
            for key, text in role_sounds.items():
                if key not in aggregated_sounds:
                    aggregated_sounds[key] = text
        return aggregated_sounds

    def get_missing_sounds(self, sound_dir: Optional[Path] = None, only_enabled: bool = False) -> Dict[str, str]:
        """
        Checks disk for existence of .wav files required by sub-plugins
        and returns dictionary of missing phrases to generate.
        """
        from simpad_qt.core.utils.audio_baker import DEFAULT_SOUND_DIR
        target_dir = Path(sound_dir or DEFAULT_SOUND_DIR)
        all_required = self.get_all_sound_requirements(only_enabled=only_enabled)
        missing: Dict[str, str] = {}
        for key, text in all_required.items():
            wav_file = target_dir / f"{key}.wav"
            if not wav_file.exists():
                missing[key] = text
        return missing

    def generate_missing_sounds(
        self,
        sound_dir: Optional[Path] = None,
        model_path: Optional[Path] = None,
        force: bool = False,
    ) -> Tuple[int, int]:
        """
        Generates via Piper TTS all missing audio files declared by sub-plugins.
        Returns tuple (num_generated, num_already_present).
        """
        try:
            from simpad_qt.core.utils.audio_baker import AudioBaker, DEFAULT_SOUND_DIR, DEFAULT_MODEL_PATH
            target_dir = Path(sound_dir or DEFAULT_SOUND_DIR)
            model = Path(model_path or DEFAULT_MODEL_PATH)
            required_phrases = self.get_all_sound_requirements(only_enabled=False)
            return AudioBaker.bake_batch(
                phrases=required_phrases,
                output_dir=target_dir,
                model_path=model,
                force=force,
            )
        except Exception as e:
            logger.error(f"[RaceEngineer] Failed to generate TTS audio: {e}", exc_info=True)
            return 0, 0

    def _get_active_reference_profile(self) -> Optional[ReferenceLapProfile]:
        """Resolves active reference lap profile from Core ReferenceLapManager."""
        try:
            from simpad_qt.core.reference_lap import ReferenceLapManager
            ref_mgr = ReferenceLapManager.get_instance()
            if ref_mgr:
                prof = ref_mgr.get_active_profile()
                if prof:
                    return prof
        except Exception:
            pass

        try:
            from simpad_qt.core.telemetry.lmu_parser import LMUParser
            delta_eng = LMUParser._delta_engine
            if delta_eng:
                return delta_eng.all_time_best_profile or delta_eng.current_profile
        except Exception:
            pass
        return None

    def update(
        self,
        telemetry: Optional[TelemInfo] = None,
        scoring: Optional[Union[FullScoringSession, CompactScoring]] = None,
        store: Optional[TelemetryStateStore] = None,
        wake_reason: Optional[TelemetryWakeReason] = None,
        trigger_packet: Optional[TelemetryTriggerPacket] = None,
    ) -> List[EngineerMessage]:
        """
        Main evaluation tick called upon incoming telemetry/scoring packets.
        Synchronizes state, evaluates all roles by descending priority, arbitrates audio,
        and returns list of emitted messages.
        """
        if not self.enabled:
            return []

        now = time.time()
        self._last_processed_time = now

        active_store = store or TelemetryStateStore.get_instance()
        if telemetry is not None:
            active_store.update_telemetry(telemetry, now)
        if scoring is not None:
            updater = _SCORING_STORE_UPDATERS.get(type(scoring))
            if updater:
                updater(active_store, scoring, now)

        if wake_reason is None:
            if trigger_packet is not None:
                wake_reason = _PACKET_WAKE_REASONS.get(type(trigger_packet), TelemetryWakeReason.MANUAL_EVALUATION)
            elif telemetry is not None:
                wake_reason = TelemetryWakeReason.PHYSICS_TICK
            elif scoring is not None:
                wake_reason = _PACKET_WAKE_REASONS.get(type(scoring), TelemetryWakeReason.SCORING_UPDATE)
            else:
                wake_reason = TelemetryWakeReason.MANUAL_EVALUATION

        context = EngineerContext(
            telemetry=telemetry,
            scoring=scoring,
            timestamp=now,
            audio_engine=self.audio_engine,
            reference_profile=self._get_active_reference_profile(),
            store=active_store,
            wake_reason=wake_reason,
            trigger_packet=trigger_packet,
        )

        emitted_messages: List[EngineerMessage] = []

        # Evaluation in strict priority order
        for role in self._roles:
            if not role.enabled:
                continue

            try:
                msg = role.update(context)
                if msg:
                    emitted_messages.append(msg)
            except Exception as e:
                logger.error(f"[RaceEngineer] Error executing role '{role.role_id}': {e}", exc_info=True)

        return emitted_messages

    def reset_all(self) -> None:
        """Resets all roles."""
        for role in self._roles:
            role.reset()

    def get_status_summary(self) -> Dict[str, Union[bool, List[str], List[Dict[str, Union[str, int, float, bool, List[str], None]]]]]:
        """Returns complete state summary for UI."""
        busy_roles = [r.role_id for r in self._roles if r.enabled and r.is_busy()]
        return {
            "enabled": self.enabled,
            "is_busy": len(busy_roles) > 0,
            "busy_roles": busy_roles,
            "roles": [r.get_state_summary() for r in self._roles],
        }

    def set_master_enabled(self, enabled: bool, auto_save: bool = True) -> None:
        """Enables or disables Race Engineer globally."""
        self.enabled = enabled
        if auto_save and self.config_path:
            self.save_to_file()

    def save_configuration(self) -> Dict[str, Union[bool, List[str], Dict[str, Dict[str, ParamScalarValue]]]]:
        """Exports role configuration (activations, parameters)."""
        roles_cfg: Dict[str, Dict[str, ParamScalarValue]] = {}
        for r in self._roles:
            cfg = dict(r.get_config())
            cfg.pop("priority", None)
            roles_cfg[r.role_id] = cfg
        return {
            "enabled": self.enabled,
            "roles": roles_cfg,
            "order": [r.role_id for r in self._roles],
        }

    def load_configuration(self, config: Dict[str, Union[bool, List[str], Dict[str, Dict[str, ParamScalarValue]]]]) -> None:
        """Restores exported configuration."""
        if "enabled" in config:
            self.enabled = bool(config["enabled"])

        roles_config = config.get("roles", {})
        for role_id, r_cfg in roles_config.items():
            role = self.get_role(role_id)
            if role and isinstance(r_cfg, dict):
                role.set_config(r_cfg)

        order = config.get("order")
        if order and isinstance(order, list):
            self.reorder_roles(order, auto_save=False)
        else:
            self._sort_roles()

    def save_to_file(self, filepath: Optional[Path] = None) -> bool:
        """Saves current role configuration to JSON file."""
        target_path = filepath or self.config_path
        if not target_path:
            return False
        try:
            target_path = Path(target_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(self.save_configuration(), f, indent=2)
            logger.info(f"[RaceEngineer] Configuration saved to '{target_path}'.")
            return True
        except Exception as e:
            logger.error(f"[RaceEngineer] Error saving configuration to '{target_path}': {e}")
            return False

    def load_from_file(self, filepath: Optional[Path] = None) -> bool:
        """Loads role configuration from JSON file."""
        target_path = filepath or self.config_path
        if not target_path:
            return False
        target_path = Path(target_path)
        if not target_path.exists():
            return False
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            if isinstance(config, dict):
                self.load_configuration(config)
                logger.info(f"[RaceEngineer] Configuration loaded from '{target_path}'.")
                return True
            return False
        except Exception as e:
            logger.error(f"[RaceEngineer] Error loading configuration from '{target_path}': {e}")
            return False
