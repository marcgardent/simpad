"""
SimPad Race Engineer — Rôle Pace Notes & Repères de Pilotage (PaceNotesRole).
Annonce les repères vocaux du tour de référence (Brake, Turn-In, Virages T1..T30, Rapports de boîte).
Architecture SOLID (SRP, OCP, DIP).
"""

import time
import logging
from typing import Optional, Dict, Any, Set, List
from src.engineer.base import BaseRole, EngineerMessage, RoleStatus
from src.engineer.context import EngineerContext
from src.engineer.registry import RoleRegistry
from src.engineer.params import RoleParam, BoolParam, FloatRangeParam
from src.telemetry.reference_profile import (
    ReferenceLapProfile,
    TrackAnnotation,
    AnnotationType,
)
from src.telemetry.lmu_parser import LMUParser

logger = logging.getLogger(__name__)


@RoleRegistry.register(
    "pace_notes",
    name="Pace Notes & Track Markers",
    description="Annonce les repères vocaux de pilotage (Frein, Braquage, Virages T1..T30, Rapports) configurés sur le circuit.",
    default_priority=80,
)
class PaceNotesRole(BaseRole):
    """
    Rôle de co-pilote / ingénieur de piste pour les repères de freinage, braquage, virages et vitesses.
    Anticipe les marqueurs en fonction de la vitesse du véhicule pour un déclenchement optimal.
    """

    def __init__(
        self,
        role_id: str = "pace_notes",
        name: str = "Pace Notes & Track Markers",
        description: str = "Annonce les repères vocaux de pilotage du tour de référence.",
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

        # État interne
        self._triggered_ann_ids: Set[str] = set()
        self._last_laps_completed: int = -1
        self._last_announcement_time: float = 0.0
        self._last_announced_label: str = "None"
        self._last_announced_dist: float = -1.0
        self._last_ann_signature: List[Any] = []
        self._custom_profile: Optional[ReferenceLapProfile] = None

    def get_parameters(self) -> List[RoleParam]:
        """Déclare la liste des paramètres configurables pour le formulaire de l'IHM."""
        return [
            BoolParam(
                name="enable_brake",
                label="Annonces Frein (Brake)",
                default=True,
                description="Activer l'annonce vocale 'Brake' aux repères de freinage",
            ),
            BoolParam(
                name="enable_turn_in",
                label="Annonces Braquage (Turn-in)",
                default=True,
                description="Activer l'annonce vocale 'Turn' aux repères de braquage/corde",
            ),
            BoolParam(
                name="enable_turn",
                label="Annonces Virages (Turn 1..30)",
                default=True,
                description="Activer l'annonce vocale des virages numérotés 'Turn N'",
            ),
            BoolParam(
                name="enable_gear",
                label="Annonces Rapports (Gear 1..8)",
                default=True,
                description="Activer l'annonce vocale du rapport conseillé 'Gear N'",
            ),
            FloatRangeParam(
                name="anticipation_time_sec",
                label="Temps d'anticipation",
                min_val=0.2,
                max_val=3.0,
                step=0.1,
                unit="s",
                default=0.8,
                description="Délai d'anticipation proportionnel à la vitesse du véhicule",
            ),
            FloatRangeParam(
                name="min_lead_distance_m",
                label="Distance min d'anticipation",
                min_val=5.0,
                max_val=50.0,
                step=1.0,
                unit="m",
                default=15.0,
                description="Distance d'anticipation minimale à basse vitesse",
            ),
            FloatRangeParam(
                name="max_lead_distance_m",
                label="Distance max d'anticipation",
                min_val=20.0,
                max_val=150.0,
                step=5.0,
                unit="m",
                default=75.0,
                description="Distance d'anticipation maximale à haute vitesse",
            ),
        ]

    def set_reference_profile(self, profile: Optional[ReferenceLapProfile]) -> None:
        """Permet d'injecter manuellement un profil de référence."""
        self._custom_profile = profile
        self.reset()

    def get_reference_profile(self) -> Optional[ReferenceLapProfile]:
        """Récupère le profil de référence actif depuis DeltaEngine ou l'instance injectée."""
        if self._custom_profile is not None:
            return self._custom_profile
        # Récupérer depuis le DeltaEngine unique de LMUParser
        delta_eng = getattr(LMUParser, "_delta_engine", None)
        return delta_eng.current_profile if delta_eng else None

    def reset(self) -> None:
        """Réinitialise les marqueurs déclenchés et l'état du rôle."""
        self._triggered_ann_ids.clear()
        self._last_laps_completed = -1
        self._last_announcement_time = 0.0
        self._last_announced_label = "None"
        self._last_announced_dist = -1.0
        self._last_ann_signature = []

    def is_busy(self) -> bool:
        """Indique si une annonce vocale a été émise très récemment (< 1.2s)."""
        return (time.time() - self._last_announcement_time) < 1.2

    def _compute_lead_distance(self, speed_mps: float) -> float:
        """Calcule la distance d'anticipation optimale en mètres selon la vitesse du véhicule."""
        dist = speed_mps * self.anticipation_time_sec
        return max(self.min_lead_distance_m, min(self.max_lead_distance_m, dist))

    def update(self, context: EngineerContext) -> Optional[EngineerMessage]:
        """
        Évalue la position du joueur par rapport aux marqueurs du circuit à chaque tick.
        """
        if not self.enabled:
            return None

        # Récupérer le véhicule joueur et les infos de position
        player_veh = context.get_player_vehicle()
        if not player_veh:
            return None

        in_garage = bool(player_veh.get("mInGarageStall", player_veh.get("inGarageStall", False)))
        in_pits = bool(player_veh.get("mInPits", player_veh.get("inPits", False)))
        if in_garage or in_pits:
            return None

        # Gérer la réinitialisation des marqueurs lors du passage au tour suivant
        laps_comp = int(player_veh.get("mTotalLaps", 0))
        if self._last_laps_completed >= 0 and laps_comp != self._last_laps_completed:
            self._triggered_ann_ids.clear()
        self._last_laps_completed = laps_comp

        profile = self.get_reference_profile()
        if not profile or not profile.annotations:
            return None

        # Détection dynamique si la liste des repères ou leurs positions ont changé en temps réel
        curr_ann_signature = [(a.id, round(a.distance, 1), a.type.value, a.gear) for a in profile.annotations]
        if curr_ann_signature != self._last_ann_signature:
            self._last_ann_signature = curr_ann_signature
            self._triggered_ann_ids.clear()

        track_len = context.get_track_length()
        if (track_len <= 0.0 or track_len == 5000.0) and profile.track_length > 0.0:
            track_len = profile.track_length

        player_dist = float(player_veh.get("mLapDist", 0.0)) % track_len
        player_speed = context.get_player_speed_mps()

        # Si le joueur est presque à l'arrêt (< 2 m/s), ne pas anticiper
        if player_speed < 2.0:
            return None

        lead_dist = self._compute_lead_distance(player_speed)
        now = context.timestamp

        # Éviter de superposer deux annonces instantanément (< 0.35s pour laisser passer Brake -> Gear)
        if (now - self._last_announcement_time) < 0.35:
            return None

        # Recherche du marqueur le plus proche dans la fenêtre d'anticipation [0, lead_dist]
        candidates = []
        for ann in profile.annotations:
            if ann.id in self._triggered_ann_ids:
                continue

            # Filtrage selon les paramètres d'activation utilisateur
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

        # Trier par proximité croissante
        candidates.sort(key=lambda item: item[0])
        _, target_ann = candidates[0]

        # Déclencher l'annonce
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
        """Retourne un résumé sérialisable pour l'interface graphique."""
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
        """Retourne la configuration exportable."""
        config = super().get_config()
        config.update({
            "anticipation_time_sec": self.anticipation_time_sec,
            "min_lead_distance_m": self.min_lead_distance_m,
            "max_lead_distance_m": self.max_lead_distance_m,
        })
        return config

    def set_config(self, config: Dict[str, Any]) -> None:
        """Applique une configuration externe."""
        super().set_config(config)
        if "anticipation_time_sec" in config:
            self.anticipation_time_sec = float(config["anticipation_time_sec"])
        if "min_lead_distance_m" in config:
            self.min_lead_distance_m = float(config["min_lead_distance_m"])
        if "max_lead_distance_m" in config:
            self.max_lead_distance_m = float(config["max_lead_distance_m"])
