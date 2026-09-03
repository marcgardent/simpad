"""
SimPad Race Engineer — Rôle de Détection, Investigation et Validation de Tour (Clean / Dirty Lap & Track Limits).
Surveille les transitions d'état du drapeau de tour (mCountLapFlag) et les enquêtes de sortie de piste (Track Limits / Investigation).
Architecture State-of-the-art :
- Gestion d'état à deux niveaux : Statut global du tour (Clean vs Dirty) et Statut d'incident (Green, Yellow, Orange/Red).
- Annonces d'action immédiate ("Cut track, give time back") pendant la fenêtre de ralentissement.
- Annonces contextuelles à la résolution :
  * Si tour propre : "Incident cleared" / "Time given back, cleared"
  * Si tour déjà invalidé : "No penalty" (évite d'annoncer à tort un Clean Lap)
  * Si sanction : "Lap deleted" ou "Penalty applied"
"""

import time
from enum import Enum
from typing import Optional, Dict, Any, List, Union

from src.engineer.base import BaseRole, EngineerMessage, RoleStatus
from src.engineer.context import EngineerContext, get_vehicle_attr
from src.engineer.registry import RoleRegistry
from src.engineer.params import RoleParam, FloatRangeParam, BoolParam


class IncidentState(str, Enum):
    IDLE = "IDLE"                    # Vert / Normal / Nominal
    INVESTIGATION = "INVESTIGATION"  # Jaune / Alerte / Give time back
    PENALTY = "PENALTY"              # Orange / Rouge / Sanction confirmée


@RoleRegistry.register(
    role_id="lap_validity",
    name="Lap Validity (Clean / Dirty Lap & Track Limits)",
    description="Surveille la validation des tours et les enquêtes de limites de piste (vert = Clean, jaune = Investigation, orange/rouge = Dirty/Penalty).",
    default_priority=50,
)
class LapValidityRole(BaseRole):
    """
    Rôle chargé de la validité du tour et de l'aide active sur les limites de piste.
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
        self._last_incident_state: IncidentState = IncidentState.IDLE
        self._is_lap_dirty: bool = False
        self._last_lap_num: Optional[int] = None
        self._last_event_time: float = 0.0
        self._last_event_name: str = "IDLE"

        self.busy_duration_sec = float(busy_duration_sec)
        self.announce_investigation = bool(announce_investigation)
        self.announce_cleared = bool(announce_cleared)
        self.announce_penalty = bool(announce_penalty)
        self.use_actionable_prompt = bool(use_actionable_prompt)

    def get_parameters(self) -> List[RoleParam]:
        return [
            FloatRangeParam(
                name="busy_duration_sec",
                label="Durée Verrou Audio",
                min_val=0.5,
                max_val=5.0,
                step=0.1,
                unit="s",
                default=1.8,
                description="Durée d'état BUSY pendant l'émission des annonces audio",
            ),
            BoolParam(
                name="announce_investigation",
                label="Alerte Investigation (Give Time Back)",
                default=True,
                description="Alerte immédiate au passage au jaune pour lever le pied et effacer l'infraction",
            ),
            BoolParam(
                name="announce_cleared",
                label="Annonce Incident Blanchi (Cleared / No Penalty)",
                default=True,
                description="Annonce de confirmation quand l'incident est effacé sans pénalité",
            ),
            BoolParam(
                name="announce_penalty",
                label="Annonce Pénalité / Tour Invalidé",
                default=True,
                description="Annonce vocale en cas d'invalidation de tour ou de pénalité de temps",
            ),
            BoolParam(
                name="use_actionable_prompt",
                label="Consignes Directives ('Give time back')",
                default=True,
                description="Utilise des consignes d'action directive ('Give time back') au lieu d'une simple notification passive",
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
                    reason="Surveillance en temps réel des drapeaux de tour (mCountLapFlag) et infractions limites de piste",
                ),
                ChannelRequirement(
                    channel=TelemetryChannel.COMPACT_SCORING,
                    preferred_hz=10,
                    required=False,
                    reason="Détection du franchissement de la ligne de chronométrage et secteurs",
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
        """Est occupé brièvement pendant la durée d'énonciation du message audio."""
        return (time.time() - self._last_event_time) < self.busy_duration_sec

    def _normalize_incident_state(self, val: Any) -> Optional[IncidentState]:
        """Normalise une valeur brute de télémétrie/API en IncidentState."""
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
        """Extrait le numéro ou décompte de tours pour réinitialiser le statut en début de tour."""
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

        # 1. Gestion du changement de tour (Passage de la ligne Start/Finish)
        current_lap_num = self._extract_lap_number(context)
        if current_lap_num is not None:
            if self._last_lap_num is not None and current_lap_num != self._last_lap_num:
                # Nouveau tour démarré -> Réinitialisation de l'invalidation de tour
                self._is_lap_dirty = False
                self._last_incident_state = IncidentState.IDLE
            self._last_lap_num = current_lap_num

        # 2. Extraction du flag de validité officiel (0=Dirty/Delete, 1=Under Investigation/Cut, 2=Valid/Clean)
        current_flag: Optional[int] = None
        if context.telemetry and hasattr(context.telemetry, "lap_flag"):
            current_flag = context.telemetry.lap_flag
        elif context.scoring:
            player_veh = context.get_player_vehicle()
            if player_veh:
                raw_flag = get_vehicle_attr(player_veh, "count_lap_flag", None)
                if raw_flag is not None:
                    current_flag = int(raw_flag)

        # 3. Extraction de l'état d'incident brut (Track limits steps ou state string)
        raw_incident: Any = None
        tl_steps = 0
        if context.telemetry:
            for attr in ("track_cut_state", "incident_state", "cut_state", "investigation_state", "offtrack_state"):
                if hasattr(context.telemetry, attr):
                    raw_incident = getattr(context.telemetry, attr)
                    break
            if hasattr(context.telemetry, "track_limits_steps"):
                tl_steps = int(getattr(context.telemetry, "track_limits_steps", 0))

        if raw_incident is None and context.scoring:
            player_veh = context.get_player_vehicle()
            if player_veh:
                for attr in ("track_cut_state", "incident_state", "cut_state", "investigation_state", "mTrackCutState", "mIncidentState"):
                    val = get_vehicle_attr(player_veh, attr, None)
                    if val is not None:
                        raw_incident = val
                        break
                val_steps = get_vehicle_attr(player_veh, "track_limits_steps", None)
                if val_steps is not None:
                    tl_steps = int(val_steps)

        # 4. Normalisation de l'état d'incident
        norm_incident = self._normalize_incident_state(raw_incident)

        # Détermination infaillible de l'état d'incident :
        if tl_steps > 0 or current_flag == 1 or norm_incident == IncidentState.INVESTIGATION:
            current_incident_state = IncidentState.INVESTIGATION
        elif current_flag == 0 or norm_incident == IncidentState.PENALTY:
            current_incident_state = IncidentState.PENALTY
        elif current_flag == 2 or norm_incident == IncidentState.IDLE:
            current_incident_state = IncidentState.IDLE
        elif norm_incident is not None:
            current_incident_state = norm_incident
        else:
            current_incident_state = IncidentState.IDLE

        # Initialisation silencieuse sur la toute première trame reçue
        if self._last_lap_flag is None and self._last_event_time == 0.0:
            self._last_lap_flag = current_flag
            if current_flag == 0:
                self._is_lap_dirty = True
            self._last_incident_state = current_incident_state
            return None

        message: Optional[EngineerMessage] = None

        # 5. Machine d'état à deux niveaux (Investigation & Validité du tour)
        if current_incident_state is not None:
            if current_incident_state != self._last_incident_state:
                prev_state = self._last_incident_state
                self._last_incident_state = current_incident_state

                # A. Passage à INVESTIGATION (ex: Flag 2 -> 1, Flag 0 -> 1, ou Steps > 0)
                # Fonctionne TOUJOURS de la même manière, même si le tour est déjà delete !
                if current_incident_state == IncidentState.INVESTIGATION:
                    if self.announce_investigation:
                        phrase_key = "give_time_back" if self.use_actionable_prompt else "under_investigation"
                        self._last_event_time = now
                        self._last_event_name = "INVESTIGATION"
                        message = EngineerMessage(
                            phrase_key=phrase_key,
                            priority=self.priority + 10,  # Priorité absolue / Interruption radio
                            interrupt=True,
                            role_id=self.role_id,
                        )
                        self.emit_sound(phrase_key, interrupt=True)

                # B. Passage INVESTIGATION -> IDLE (Incident blanchi / temps rendu / Steps -> 0 / Flag -> 2)
                elif prev_state == IncidentState.INVESTIGATION and current_incident_state == IncidentState.IDLE:
                    if self.announce_cleared:
                        if not self._is_lap_dirty:
                            # Le tour est propre : confirmation que le chrono et l'incident sont sauvés
                            phrase_key = "time_cleared" if self.use_actionable_prompt else "incident_cleared"
                            self._last_event_name = "INCIDENT_CLEARED_CLEAN"
                        else:
                            # Le tour était DÉJÀ delete : aucune pénalité de course, mais on n'annonce PAS "Clean lap" !
                            phrase_key = "no_penalty"
                            self._last_event_name = "INCIDENT_CLEARED_DIRTY"

                        self._last_event_time = now
                        message = EngineerMessage(
                            phrase_key=phrase_key,
                            priority=self.priority,
                            interrupt=False,
                            role_id=self.role_id,
                        )
                        self.emit_sound(phrase_key, interrupt=False)

                # C. Passage à PENALTY (Sanction / Délai expiré / Cut sévère / Flag -> 0)
                elif current_incident_state == IncidentState.PENALTY:
                    if not self._is_lap_dirty:
                        # Première invalidation du tour en cours
                        self._is_lap_dirty = True
                        phrase_key = "lap_deleted" if self.use_actionable_prompt else "dirty_lap"
                        self._last_event_name = "LAP_DELETED"
                    else:
                        # Le tour était DÉJÀ delete : pénalité de temps ou drive through
                        phrase_key = "penalty_applied"
                        self._last_event_name = "PENALTY_APPLIED"

                    if self.announce_penalty:
                        self._last_event_time = now
                        message = EngineerMessage(
                            phrase_key=phrase_key,
                            priority=self.priority,
                            interrupt=False,
                            role_id=self.role_id,
                        )
                        self.emit_sound(phrase_key, interrupt=False)

        # 6. Mémorisation du flag courant
        if current_flag is not None:
            if current_flag == 0:
                self._is_lap_dirty = True
            self._last_lap_flag = current_flag

        return message

    def emit_sound(self, phrase_key: str, interrupt: bool = False) -> None:
        """Émet le son et trace l'événement dans track_limits_debug.log."""
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
        self._last_incident_state = IncidentState.IDLE
        self._is_lap_dirty = False
        self._last_lap_num = None
        self._last_event_time = 0.0
        self._last_event_name = "IDLE"

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

