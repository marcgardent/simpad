"""
SimPad Race Engineer — Rôle Traffic Spotter (FSM Haute Précision TTC).
Détecte l'approche rapide de véhicules par l'arrière (Time-To-Collision),
gère le décompte vocal (3, 2, 1), l'avertissement de bord-à-bord (Alongside)
et la confirmation de dépassement sécurisé (Clear).
"""

import time
import logging
from enum import Enum
from typing import Optional, Dict, Any, List, Tuple
from src.engineer.base import BaseRole, EngineerMessage, RoleStatus
from src.engineer.context import EngineerContext, get_vehicle_attr
from src.engineer.registry import RoleRegistry
from src.engineer.params import RoleParam, FloatRangeParam, BoolParam
from src.telemetry.reference_profile import ReferenceLapProfile

logger = logging.getLogger(__name__)


class TrafficSpotterState(str, Enum):
    """États de la machine à états finis (FSM) du Traffic Spotter."""
    IDLE = "IDLE"                # Piste dégagée / Aucune menace
    APPROACHING = "APPROACHING"  # Véhicule rapide détecté derrière (TTC <= 5s)
    COUNTDOWN = "COUNTDOWN"      # Décompte temporel actif (3s, 2s, 1s)
    OVERLAP = "OVERLAP"          # Véhicule bord à bord / Côte à côte
    CLEAR = "CLEAR"              # Véhicule passé devant & distance de sécurité atteinte


@RoleRegistry.register(
    role_id="traffic_spotter",
    name="Traffic Spotter (TTC FSM)",
    description="Machine à états surveillant le TTC et la position relative des adversaires pour annoncer l'approche, le décompte (3-2-1), l'overlap et le clear.",
    default_priority=100,
)
class TrafficSpotterRole(BaseRole):
    """
    Rôle de surveillance du trafic et de gestion des dépassements rapides par l'arrière.
    
    Machine à états :
    [IDLE] -> [APPROACHING] -> [COUNTDOWN: 3, 2, 1] -> [OVERLAP] -> [CLEAR] -> [IDLE]
    """

    NUM_PHRASE_MAP = {
        1: "one",
        2: "two",
        3: "three",
        4: "four",
        5: "five",
    }

    def __init__(
        self,
        role_id: str = "traffic_spotter",
        name: str = "Traffic Spotter (TTC FSM)",
        description: str = "",
        priority: int = 100,
        enabled: bool = True,
        audio_engine: Optional[Any] = None,
        ttc_trigger_sec: float = 5.0,
        speed_delta_min_kmh: float = 20.0,
        overlap_dist_threshold_m: float = 4.0,
        clear_dist_threshold_m: float = 10.0,
        abort_ttc_sec: float = 6.0,
        max_scan_distance_m: float = 250.0,
        phrase_mode: str = "alongside",  # "alongside" ou "overlap" ou "car"
        enable_ref_lap_filter: bool = True,
        domain_speed_tolerance_kmh: float = 30.0,
        target_memory_sec: float = 6.0,
        incoming_cooldown_sec: Optional[float] = None,
    ):
        super().__init__(
            role_id=role_id,
            name=name,
            description=description,
            priority=priority,
            enabled=enabled,
            audio_engine=audio_engine,
        )
        self.state = TrafficSpotterState.IDLE
        self.ttc_trigger_sec = float(ttc_trigger_sec)
        self.speed_delta_min_mps = float(speed_delta_min_kmh) / 3.6  # 20 km/h = 5.55 m/s
        self.overlap_dist_threshold_m = float(overlap_dist_threshold_m)
        self.clear_dist_threshold_m = float(clear_dist_threshold_m)
        self.abort_ttc_sec = float(abort_ttc_sec)
        self.max_scan_distance_m = float(max_scan_distance_m)
        self.phrase_mode = phrase_mode
        self.enable_ref_lap_filter = bool(enable_ref_lap_filter)
        self.domain_speed_tolerance_kmh = float(domain_speed_tolerance_kmh)
        if incoming_cooldown_sec is not None:
            self.target_memory_sec = float(incoming_cooldown_sec)
        else:
            self.target_memory_sec = float(target_memory_sec)
        self._custom_profile: Optional[ReferenceLapProfile] = None

        # Variables dynamiques de suivi
        self.target_vehicle_id: Optional[int] = None
        self.target_driver_name: str = ""
        self.target_vehicle_name: str = ""
        self.last_announced_sec: Optional[int] = None
        self._last_state_change_time: float = 0.0
        self._overlap_start_time: float = 0.0
        self._last_incoming_time: float = 0.0
        self._last_aborted_target_id: Optional[int] = None
        self._last_aborted_time: float = 0.0

        # Mémoire et anti-rebond par véhicule (débouncing renforcé N secondes)
        self._target_history: Dict[int, Dict[str, Any]] = {}
        self._last_spotted_target_id: Optional[int] = None
        self._last_spotted_stage: Optional[int] = None
        self._last_spotted_time: float = 0.0

        # Données de diagnostic en direct
        self._live_ttc: float = float("inf")
        self._live_distance: float = 0.0
        self._live_speed_delta_kmh: float = 0.0

    @property
    def incoming_cooldown_sec(self) -> float:
        """Alias de compatibilité pour target_memory_sec."""
        return self.target_memory_sec

    @incoming_cooldown_sec.setter
    def incoming_cooldown_sec(self, value: float) -> None:
        self.target_memory_sec = float(value)

    def _record_target_stage(self, vehicle_id: int, stage: int, now: float) -> None:
        """Enregistre le stade d'annonce atteint par un véhicule pour éviter les répétitions."""
        self._target_history[vehicle_id] = {
            "last_stage": stage,
            "last_time": now,
        }
        self._last_spotted_target_id = vehicle_id
        self._last_spotted_stage = stage
        self._last_spotted_time = now

    def _get_target_memory(self, vehicle_id: int, now: float) -> Optional[Dict[str, Any]]:
        """Récupère la mémoire d'un véhicule si elle n'a pas expiré (target_memory_sec)."""
        entry = self._target_history.get(vehicle_id)
        if not entry:
            return None
        if (now - entry["last_time"]) > self.target_memory_sec:
            self._target_history.pop(vehicle_id, None)
            return None
        return entry

    def _prune_target_history(self, now: float) -> None:
        """Nettoie les entrées d'historique expirées (> target_memory_sec)."""
        expired = [
            vid for vid, entry in self._target_history.items()
            if (now - entry["last_time"]) > self.target_memory_sec
        ]
        for vid in expired:
            del self._target_history[vid]

    def set_reference_profile(self, profile: Optional[ReferenceLapProfile]) -> None:
        """Injecte manuellement un profil de tour de référence."""
        self._custom_profile = profile
        self.reset()

    def get_reference_profile(self, context: Optional[EngineerContext] = None) -> Optional[ReferenceLapProfile]:
        """Récupère le profil de référence actif (injecté ou via le contexte/DeltaEngine)."""
        if self._custom_profile is not None:
            return self._custom_profile
        if context:
            return context.get_reference_profile()
        try:
            from src.telemetry.lmu_parser import LMUParser
            delta_eng = getattr(LMUParser, "_delta_engine", None)
            if delta_eng:
                return delta_eng.all_time_best_profile or delta_eng.current_profile
        except Exception:
            pass
        return None

    @property
    def speed_delta_min_kmh(self) -> float:
        """Delta de vitesse minimum en km/h."""
        return round(self.speed_delta_min_mps * 3.6, 1)

    @speed_delta_min_kmh.setter
    def speed_delta_min_kmh(self, value: float) -> None:
        self.speed_delta_min_mps = float(value) / 3.6

    def get_parameters(self) -> List[RoleParam]:
        """Déclare la liste des paramètres configurables du Spotter pour l'IHM."""
        return [
            BoolParam(
                name="enable_ref_lap_filter",
                label="Filtre Tour Référence",
                default=True,
                description="Exige qu'au moins un des véhicules (joueur ou adversaire) soit hors domaine de vitesse normal",
            ),
            FloatRangeParam(
                name="domain_speed_tolerance_kmh",
                label="Tolérance Vitesse Domaine",
                min_val=5.0,
                max_val=80.0,
                step=5.0,
                unit="km/h",
                default=30.0,
                description="Écart de vitesse max avec le tour de référence pour être considéré dans le domaine normal",
            ),
            FloatRangeParam(
                name="speed_delta_min_kmh",
                label="Delta Vitesse Min",
                min_val=5.0,
                max_val=80.0,
                step=1.0,
                unit="km/h",
                default=20.0,
                description="Delta de vitesse positif minimum requis pour déclencher l'alerte d'approche",
            ),
            FloatRangeParam(
                name="ttc_trigger_sec",
                label="Seuil Déclenchement TTC",
                min_val=2.0,
                max_val=10.0,
                step=0.5,
                unit="s",
                default=5.0,
                description="Temps avant collision (Time-To-Collision) déclenchant le spotter",
            ),
            FloatRangeParam(
                name="target_memory_sec",
                label="Mémoire / Anti-rebond Cible",
                min_val=1.0,
                max_val=30.0,
                step=0.5,
                unit="s",
                default=6.0,
                description="Durée de mémorisation de la dernière cible pour éviter les annonces répétées non progressives",
            ),
            FloatRangeParam(
                name="overlap_dist_threshold_m",
                label="Distance Seuil Overlap",
                min_val=1.0,
                max_val=15.0,
                step=0.5,
                unit="m",
                default=4.0,
                description="Distance relative bord-à-bord (Alongside / Overlap)",
            ),
            FloatRangeParam(
                name="clear_dist_threshold_m",
                label="Distance Seuil Clear",
                min_val=2.0,
                max_val=30.0,
                step=1.0,
                unit="m",
                default=10.0,
                description="Distance de sécurité après dépassement pour annoncer Clear",
            ),
            FloatRangeParam(
                name="max_scan_distance_m",
                label="Distance Max de Scan",
                min_val=50.0,
                max_val=500.0,
                step=10.0,
                unit="m",
                default=250.0,
                description="Rayon de détection arrière sur la spline de piste",
            ),
        ]

    def is_busy(self) -> bool:
        """Le rôle est occupé dès qu'il suit activement une voiture (hors IDLE)."""
        return self.state != TrafficSpotterState.IDLE

    def update(self, context: EngineerContext) -> Optional[EngineerMessage]:
        if not self.enabled or not context.scoring or context.is_private_qualifying():
            if self.state != TrafficSpotterState.IDLE:
                self.reset()
            return None

        player_veh = context.get_player_vehicle()
        if not player_veh:
            if self.state != TrafficSpotterState.IDLE:
                self.reset()
            return None

        # Si le joueur est dans la pitlane ou au garage, désactiver le spotter de piste
        # pour éviter toute fausse alerte causée par les voitures passant à pleine vitesse sur la piste
        if context.is_player_in_pits() or context.is_player_in_garage():
            if self.state != TrafficSpotterState.IDLE:
                self.reset()
            return None

        now = context.timestamp if (context and context.timestamp is not None) else time.time()
        self._prune_target_history(now)

        player_speed = context.get_player_speed_mps()
        track_length = context.get_track_length()
        opponents = context.get_track_opponents()

        # Calcul des métriques de tous les adversaires
        opponent_metrics = self._calculate_opponent_metrics(context, player_veh, player_speed, opponents, track_length)

        # Exécution de la FSM
        return self._run_state_machine(opponent_metrics, now=now)

    def _calculate_opponent_metrics(
        self,
        context: EngineerContext,
        player_veh: Dict[str, Any],
        player_speed: float,
        opponents: List[Dict[str, Any]],
        track_length: float,
    ) -> List[Dict[str, Any]]:
        """Calcule TTC, distance relative et delta de vitesse pour chaque adversaire."""
        metrics = []
        ref_prof = self.get_reference_profile(context)
        has_valid_ref = bool(ref_prof and getattr(ref_prof, "num_points", 0) >= 2)

        for opp in opponents:
            opp_id = get_vehicle_attr(opp, "id", -1)
            opp_speed = context.extract_vehicle_speed_mps(opp)
            dist_behind = context.compute_distance_behind(player_veh, opp, track_length)
            speed_delta = opp_speed - player_speed
            speed_delta_kmh = speed_delta * 3.6

            # TTC valide physiquement si l'adversaire est derrière et se rapproche
            if dist_behind > 0.0 and speed_delta > 0.5:
                ttc = dist_behind / speed_delta
            else:
                ttc = float("inf")

            # Évaluation du domaine de vitesse normal (tour de référence)
            domain_anomaly = True
            if self.enable_ref_lap_filter and has_valid_ref:
                domain_anomaly = context.has_traffic_domain_anomaly(
                    player_veh,
                    opp,
                    profile=ref_prof,
                    tolerance_kmh=self.domain_speed_tolerance_kmh,
                )
            elif self.enable_ref_lap_filter and not has_valid_ref:
                logger.debug(
                    "[TrafficSpotter] Filtre domaine activé mais aucun profil de référence — filtre bypassé"
                )

            metrics.append({
                "vehicle": opp,
                "id": opp_id,
                "driver_name": get_vehicle_attr(opp, "driver_name", "Opponent"),
                "vehicle_name": get_vehicle_attr(opp, "vehicle_name", ""),
                "dist_behind": dist_behind,
                "speed_delta_mps": speed_delta,
                "speed_delta_kmh": speed_delta_kmh,
                "ttc": ttc,
                "opp_speed": opp_speed,
                "domain_anomaly": domain_anomaly,
            })
        return metrics

    def _run_state_machine(self, metrics: List[Dict[str, Any]], now: Optional[float] = None) -> Optional[EngineerMessage]:
        """Exécute les transitions de la FSM selon les métriques calculées."""
        if now is None:
            now = time.time()

        # =========================================================================
        # 1. ÉTAT IDLE / TRACK CLEAR
        # =========================================================================
        if self.state == TrafficSpotterState.IDLE:
            self._live_ttc = float("inf")
            self._live_distance = 0.0
            self._live_speed_delta_kmh = 0.0

            # Trouver le véhicule le plus menaçant (TTC le plus court <= seuil)
            # avec filtre du tour de référence
            threats = [
                m for m in metrics
                if 0.0 < m["dist_behind"] <= self.max_scan_distance_m
                and m["speed_delta_mps"] >= self.speed_delta_min_mps
                and m["ttc"] <= self.ttc_trigger_sec
                and m.get("domain_anomaly", True)
            ]

            if threats:
                threats.sort(key=lambda m: m["ttc"])
                target = threats[0]
                target_id = target["id"]

                self.target_vehicle_id = target_id
                self.target_driver_name = target["driver_name"]
                self.target_vehicle_name = target["vehicle_name"]
                self._last_state_change_time = now

                self._live_ttc = target["ttc"]
                self._live_distance = target["dist_behind"]
                self._live_speed_delta_kmh = target["speed_delta_kmh"]

                # Vérifier dans l'historique si ce véhicule a déjà été annoncé dans la fenêtre target_memory_sec
                hist = self._get_target_memory(target_id, now)
                last_stage = hist.get("last_stage") if hist else None

                if last_stage is None:
                    # Première détection pour cette cible -> Entrée standard en APPROACHING ("incoming")
                    self.state = TrafficSpotterState.APPROACHING
                    self.last_announced_sec = 5
                    self._record_target_stage(target_id, 5, now)
                    self._last_incoming_time = now

                    phrase = "incoming" if self.phrase_mode in ("alongside", "incoming") else "traffic_5"
                    msg = EngineerMessage(
                        phrase_key=phrase,
                        priority=self.priority,
                        interrupt=False,
                        role_id=self.role_id,
                    )
                    self.emit_sound(phrase, interrupt=False)
                    return msg
                else:
                    # Véhicule déjà en mémoire dans les N dernières secondes
                    # Déterminer si le véhicule a progressé vers un stade plus proche
                    if target["ttc"] <= 1.0:
                        current_stage = 1
                    elif target["ttc"] <= 2.0:
                        current_stage = 2
                    elif target["ttc"] <= 3.0:
                        current_stage = 3
                    else:
                        current_stage = 5

                    if current_stage < last_stage:
                        # Progression constatée -> annonce directe du nouveau stade
                        self._record_target_stage(target_id, current_stage, now)
                        self.last_announced_sec = current_stage

                        if current_stage <= 3:
                            self.state = TrafficSpotterState.COUNTDOWN
                            phrase = self.NUM_PHRASE_MAP.get(current_stage, "one")
                        else:
                            self.state = TrafficSpotterState.APPROACHING
                            phrase = "incoming" if self.phrase_mode in ("alongside", "incoming") else "traffic_5"

                        msg = EngineerMessage(
                            phrase_key=phrase,
                            priority=self.priority,
                            interrupt=False,
                            role_id=self.role_id,
                        )
                        self.emit_sound(phrase, interrupt=False)
                        return msg
                    else:
                        # Pas de progression : reprise du suivi en silence sans répéter "incoming" ou le décompte
                        self.state = TrafficSpotterState.APPROACHING if last_stage > 3 else TrafficSpotterState.COUNTDOWN
                        self.last_announced_sec = last_stage
                        return None

            return None

        # =========================================================================
        # RECHERCHE DE LA CIBLE COURANTE DANS LES METRICS
        # =========================================================================
        target_metric = next((m for m in metrics if m["id"] == self.target_vehicle_id), None)

        if not target_metric:
            # Cible disparue (abandon, stands, déconnexion)
            self._last_aborted_target_id = self.target_vehicle_id
            self._last_aborted_time = now
            self._reset_active_tracking()
            return None

        dist_behind = target_metric["dist_behind"]
        ttc = target_metric["ttc"]
        speed_delta_mps = target_metric["speed_delta_mps"]
        self._live_ttc = ttc
        self._live_distance = dist_behind
        self._live_speed_delta_kmh = target_metric["speed_delta_kmh"]

        # =========================================================================
        # 2. ÉTAT APPROACHING / COUNTDOWN
        # =========================================================================
        if self.state in (TrafficSpotterState.APPROACHING, TrafficSpotterState.COUNTDOWN):
            # Annulation / Reset si l'adversaire ralentit nettement ou s'écarte sans spammer
            is_slowing_down = (speed_delta_mps <= 1.0) or (ttc > self.abort_ttc_sec)
            if is_slowing_down and dist_behind > 15.0:
                logger.debug(f"[TrafficSpotter] Abort approach: TTC={ttc:.1f}s, Dist={dist_behind:.1f}m, Delta={speed_delta_mps*3.6:.1f}km/h")
                self._last_aborted_target_id = self.target_vehicle_id
                self._last_aborted_time = now
                self._reset_active_tracking()
                return None

            # Détection Overlap / Biais bord à bord
            # La voiture est bord à bord quand la distance spline est proche de 0
            if (
                abs(dist_behind) <= self.overlap_dist_threshold_m
                or (dist_behind <= 0.0 and dist_behind > -self.clear_dist_threshold_m)
            ):
                self.state = TrafficSpotterState.OVERLAP
                self._overlap_start_time = now
                self._last_state_change_time = now

                target_id = self.target_vehicle_id
                hist = self._get_target_memory(target_id, now) if target_id is not None else None
                last_stage = hist.get("last_stage") if hist else None

                # STAGE_OVERLAP = 0
                if last_stage is None or 0 < last_stage:
                    if target_id is not None:
                        self._record_target_stage(target_id, 0, now)
                    self.last_announced_sec = 0

                    overlap_phrase = self.phrase_mode if self.phrase_mode in ("alongside", "overlap", "car") else "alongside"
                    msg = EngineerMessage(
                        phrase_key=overlap_phrase,
                        priority=self.priority,
                        interrupt=True,
                        role_id=self.role_id,
                    )
                    self.emit_sound(overlap_phrase, interrupt=True)
                    return msg
                return None

            # Décompte temporel (3s, 2s, 1s)
            for sec in (3, 2, 1):
                if ttc <= float(sec) and (self.last_announced_sec is None or self.last_announced_sec > sec):
                    self.state = TrafficSpotterState.COUNTDOWN
                    self.last_announced_sec = sec
                    self._last_state_change_time = now

                    target_id = self.target_vehicle_id
                    hist = self._get_target_memory(target_id, now) if target_id is not None else None
                    last_stage = hist.get("last_stage") if hist else None

                    if last_stage is None or sec < last_stage:
                        if target_id is not None:
                            self._record_target_stage(target_id, sec, now)

                        num_phrase = self.NUM_PHRASE_MAP.get(sec, "one")
                        msg = EngineerMessage(
                            phrase_key=num_phrase,
                            priority=self.priority,
                            interrupt=False,
                            role_id=self.role_id,
                        )
                        self.emit_sound(num_phrase, interrupt=False)
                        return msg

            return None

        # =========================================================================
        # 3. ÉTAT OVERLAP
        # =========================================================================
        elif self.state == TrafficSpotterState.OVERLAP:
            if self._overlap_start_time <= 0.0:
                self._overlap_start_time = now

            # Sécurité timeout si overlap bloqué > 15s (voiture accidentée ou disparue)
            if (now - self._overlap_start_time) > 15.0:
                self._reset_active_tracking()
                return None

            # Condition CLEAR : La voiture est passée devant (distance < -10m)
            if dist_behind <= -self.clear_dist_threshold_m:
                passed_target_id = self.target_vehicle_id

                # Vérifier si une autre voiture arrive derrière immédiatement
                other_threats = [
                    m for m in metrics
                    if m["id"] != self.target_vehicle_id
                    and 0.0 < m["dist_behind"] <= 80.0
                    and m["ttc"] <= 4.0
                ]

                if other_threats:
                    if passed_target_id is not None:
                        self._record_target_stage(passed_target_id, -1, now)

                    # Enchaînement direct sur la prochaine voiture sans dire Clear
                    other_threats.sort(key=lambda m: m["ttc"])
                    next_target = other_threats[0]
                    next_id = next_target["id"]

                    self.target_vehicle_id = next_id
                    self.target_driver_name = next_target["driver_name"]
                    self.target_vehicle_name = next_target["vehicle_name"]

                    hist_next = self._get_target_memory(next_id, now)
                    self.last_announced_sec = hist_next.get("last_stage") if hist_next else 4
                    self.state = TrafficSpotterState.APPROACHING
                    self._last_state_change_time = now
                    return None

                # Piste dégagée derrière -> Annonce CLEAR
                self.state = TrafficSpotterState.CLEAR
                self._last_state_change_time = now

                hist = self._get_target_memory(passed_target_id, now) if passed_target_id is not None else None
                last_stage = hist.get("last_stage") if hist else None

                if passed_target_id is not None:
                    self._record_target_stage(passed_target_id, -1, now)

                # STAGE_CLEAR = -1
                if last_stage is None or -1 < last_stage:
                    self.last_announced_sec = -1

                    clear_phrase = "clear" if self.phrase_mode != "car" else "car_clear"
                    msg = EngineerMessage(
                        phrase_key=clear_phrase,
                        priority=self.priority,
                        interrupt=True,
                        role_id=self.role_id,
                    )
                    self.emit_sound(clear_phrase, interrupt=True)
                    return msg

                return None

            return None

        # =========================================================================
        # 4. ÉTAT CLEAR -> RETOUR IMMÉDIAT À IDLE
        # =========================================================================
        elif self.state == TrafficSpotterState.CLEAR:
            self._reset_active_tracking()
            return None

        return None

    def _reset_active_tracking(self) -> None:
        """Réinitialise les variables de suivi FSM sans effacer la mémoire d'anti-rebond."""
        self.state = TrafficSpotterState.IDLE
        self.target_vehicle_id = None
        self.target_driver_name = ""
        self.target_vehicle_name = ""
        self.last_announced_sec = None
        self._last_state_change_time = 0.0
        self._overlap_start_time = 0.0
        self._live_ttc = float("inf")
        self._live_distance = 0.0
        self._live_speed_delta_kmh = 0.0

    def reset(self, clear_history: bool = True) -> None:
        """Réinitialise l'état complet du rôle et optionnellement la mémoire."""
        self._reset_active_tracking()
        if clear_history:
            self._target_history.clear()
            self._last_spotted_target_id = None
            self._last_spotted_stage = None
            self._last_spotted_time = 0.0
            self._last_aborted_target_id = None
            self._last_aborted_time = 0.0

    def get_config(self) -> Dict[str, Any]:
        cfg = super().get_config()
        cfg.update({
            "ttc_trigger_sec": self.ttc_trigger_sec,
            "speed_delta_min_kmh": self.speed_delta_min_mps * 3.6,
            "overlap_dist_threshold_m": self.overlap_dist_threshold_m,
            "clear_dist_threshold_m": self.clear_dist_threshold_m,
            "abort_ttc_sec": self.abort_ttc_sec,
            "max_scan_distance_m": self.max_scan_distance_m,
            "phrase_mode": self.phrase_mode,
            "enable_ref_lap_filter": self.enable_ref_lap_filter,
            "domain_speed_tolerance_kmh": self.domain_speed_tolerance_kmh,
            "target_memory_sec": self.target_memory_sec,
        })
        return cfg

    def set_config(self, config: Dict[str, Any]) -> None:
        super().set_config(config)
        if "ttc_trigger_sec" in config:
            self.ttc_trigger_sec = float(config["ttc_trigger_sec"])
        if "speed_delta_min_kmh" in config:
            self.speed_delta_min_mps = float(config["speed_delta_min_kmh"]) / 3.6
        if "overlap_dist_threshold_m" in config:
            self.overlap_dist_threshold_m = float(config["overlap_dist_threshold_m"])
        if "clear_dist_threshold_m" in config:
            self.clear_dist_threshold_m = float(config["clear_dist_threshold_m"])
        if "abort_ttc_sec" in config:
            self.abort_ttc_sec = float(config["abort_ttc_sec"])
        if "max_scan_distance_m" in config:
            self.max_scan_distance_m = float(config["max_scan_distance_m"])
        if "phrase_mode" in config:
            self.phrase_mode = str(config["phrase_mode"])
        if "enable_ref_lap_filter" in config:
            self.enable_ref_lap_filter = bool(config["enable_ref_lap_filter"])
        if "domain_speed_tolerance_kmh" in config:
            self.domain_speed_tolerance_kmh = float(config["domain_speed_tolerance_kmh"])
        if "target_memory_sec" in config:
            self.target_memory_sec = float(config["target_memory_sec"])
        elif "incoming_cooldown_sec" in config:
            self.target_memory_sec = float(config["incoming_cooldown_sec"])

    def get_state_summary(self) -> Dict[str, Any]:
        summary = super().get_state_summary()
        ttc_str = f"{self._live_ttc:.1f}s" if self._live_ttc < 99.0 else "--"
        dist_str = f"{self._live_distance:.1f}m" if self.state != TrafficSpotterState.IDLE else "--"
        delta_str = f"+{self._live_speed_delta_kmh:.0f} km/h" if self.state != TrafficSpotterState.IDLE else "--"

        summary.update({
            "fsm_state": self.state.value,
            "target_id": self.target_vehicle_id,
            "target_driver": self.target_driver_name or "None",
            "target_car": self.target_vehicle_name or "None",
            "live_ttc": self._live_ttc,
            "live_ttc_str": ttc_str,
            "live_distance": self._live_distance,
            "live_distance_str": dist_str,
            "live_speed_delta_kmh": self._live_speed_delta_kmh,
            "live_speed_delta_str": delta_str,
            "last_announced_sec": self.last_announced_sec,
            "enable_ref_lap_filter": self.enable_ref_lap_filter,
            "domain_speed_tolerance_kmh": self.domain_speed_tolerance_kmh,
            "target_memory_sec": self.target_memory_sec,
            "is_busy": self.is_busy(),
        })
        return summary

