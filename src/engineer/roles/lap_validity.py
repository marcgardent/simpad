"""
SimPad Race Engineer — Rôle de Détection et Validation de Tour (Clean / Dirty Lap).
Surveille les transitions d'état du drapeau de tour LMU (mCountLapFlag).
"""

import time
from src.engineer.base import BaseRole, EngineerMessage, RoleStatus
from src.engineer.context import EngineerContext
from src.engineer.registry import RoleRegistry
from src.engineer.params import RoleParam, FloatRangeParam


@RoleRegistry.register(
    role_id="lap_validity",
    name="Lap Validity (Clean / Dirty Lap)",
    description="Surveille la validation des tours (vert = Clean Lap, orange/rouge = Dirty Lap) et émet les annonces vocales.",
    default_priority=50,
)
class LapValidityRole(BaseRole):
    """
    Rôle chargé de valider la légalité du tour en cours :
    - Transition 0 ou 1 -> 2 : Tour propre validé ("clean_lap").
    - Transition 2 -> 0 ou 1 : Tour invalidé ("dirty_lap").
    """

    def __init__(
        self,
        role_id: str = "lap_validity",
        name: str = "Lap Validity (Clean / Dirty Lap)",
        description: str = "",
        priority: int = 50,
        enabled: bool = True,
        audio_engine: Optional[Any] = None,
        busy_duration_sec: float = 1.8,
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
        self.busy_duration_sec = float(busy_duration_sec)

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
                description="Durée d'état BUSY pendant l'émission des annonces Clean / Dirty Lap",
            ),
        ]

    def is_busy(self) -> bool:
        """Est occupé brièvement pendant la durée d'énonciation du message audio."""
        return (time.time() - self._last_event_time) < self.busy_duration_sec

    def update(self, context: EngineerContext) -> Optional[EngineerMessage]:
        if not self.enabled:
            return None

        # Extraction du flag de tour depuis la télémétrie ou le scoring
        current_flag: Optional[int] = None
        if context.telemetry and hasattr(context.telemetry, "lap_flag"):
            current_flag = context.telemetry.lap_flag
        elif context.scoring:
            player_veh = context.get_player_vehicle()
            if player_veh:
                raw_flag = player_veh.get("mCountLapFlag", player_veh.get("countLapFlag", None))
                if raw_flag is not None:
                    current_flag = int(raw_flag)

        if current_flag is None:
            return None

        message: Optional[EngineerMessage] = None

        # Première initialisation
        if self._last_lap_flag is None:
            self._last_lap_flag = current_flag
            return None

        # Détection de transition
        if self._last_lap_flag != current_flag:
            now = time.time()

            # Transition vers Clean Lap (flag 2 depuis 0 ou 1)
            if self._last_lap_flag in (0, 1) and current_flag == 2:
                self._last_event_time = now
                self._last_event_name = "CLEAN_LAP"
                message = EngineerMessage(
                    phrase_key="clean_lap",
                    priority=self.priority,
                    interrupt=False,
                    role_id=self.role_id,
                )
                self.emit_sound("clean_lap", interrupt=False)

            # Transition vers Dirty Lap (flag 0 ou 1 depuis 2)
            elif self._last_lap_flag == 2 and current_flag in (0, 1):
                self._last_event_time = now
                self._last_event_name = "DIRTY_LAP"
                message = EngineerMessage(
                    phrase_key="dirty_lap",
                    priority=self.priority,
                    interrupt=False,
                    role_id=self.role_id,
                )
                self.emit_sound("dirty_lap", interrupt=False)

            self._last_lap_flag = current_flag

        return message

    def reset(self) -> None:
        self._last_lap_flag = None
        self._last_event_time = 0.0
        self._last_event_name = "IDLE"

    def get_state_summary(self) -> Dict[str, Any]:
        summary = super().get_state_summary()
        flag_str = "Unknown"
        if self._last_lap_flag == 2:
            flag_str = "Valid (Clean)"
        elif self._last_lap_flag in (0, 1):
            flag_str = "Invalid (Dirty)"

        summary.update({
            "lap_flag": self._last_lap_flag,
            "lap_status_text": flag_str,
            "last_event": self._last_event_name,
            "is_busy": self.is_busy(),
        })
        return summary
