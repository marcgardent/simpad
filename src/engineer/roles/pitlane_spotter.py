"""
SimPad Race Engineer — Rôle Pitlane Spotter & Protection Unsafe Release (FSM Haute Précision).
Surveille la voie des stands pour :
1. Prévenir tout Unsafe Release (alerte lorsqu'une voiture déboule dans la Fast Lane derrière le box).
2. Confirmer la voie libre (Safe Release / Clear) pour repartir en toute sécurité.
3. Alerter sur les bouchons ou véhicules arrêtés devant dans la pitlane.
4. Signaler les véhicules bord à bord (Alongside) sortant des boxes adjacents.
"""

import time
import math
import logging
from enum import Enum
from typing import Optional, Dict, Any, List, Tuple
from src.engineer.base import BaseRole, EngineerMessage, RoleStatus
from src.engineer.context import EngineerContext, get_vehicle_attr
from src.engineer.registry import RoleRegistry
from src.engineer.params import RoleParam, FloatRangeParam, BoolParam

logger = logging.getLogger(__name__)


class PitlaneSpotterState(str, Enum):
    """États de la machine à états finis (FSM) du Pitlane Spotter."""
    IDLE = "IDLE"                            # Piste dégagée / En piste ou aucune menace en pitlane
    BOX_MONITORING = "BOX_MONITORING"        # Joueur au box / arrêt au stand / surveillance active
    UNSAFE_HAZARD = "UNSAFE_HAZARD"          # Danger ! Véhicule en approche rapide dans la Fast Lane
    RELEASE_CLEAR = "RELEASE_CLEAR"          # Voie dégagée après passage du danger (Safe Release)
    PIT_TRAFFIC_AHEAD = "PIT_TRAFFIC_AHEAD"  # Véhicule bloqué ou très lent devant dans la pitlane
    PIT_OVERLAP = "PIT_OVERLAP"              # Véhicule bord à bord / insertion côte à côte dans les stands


@RoleRegistry.register(
    role_id="pitlane_spotter",
    name="Pitlane Spotter & Unsafe Release",
    description="Machine à états haute précision protégeant contre les Unsafe Release en sortie de box et surveillant le trafic dans la voie des stands.",
    default_priority=95,
)
class PitlaneSpotterRole(BaseRole):
    """
    Rôle de surveillance avancée du trafic dans la pitlane et protection contre les Unsafe Release.
    """

    def __init__(
        self,
        role_id: str = "pitlane_spotter",
        name: str = "Pitlane Spotter & Unsafe Release",
        description: str = "",
        priority: int = 95,
        enabled: bool = True,
        audio_engine: Optional[Any] = None,
        unsafe_release_distance_m: float = 28.0,
        unsafe_release_ttc_sec: float = 2.5,
        pit_slow_ahead_distance_m: float = 35.0,
        pit_slow_speed_threshold_kmh: float = 20.0,
        enable_unsafe_release: bool = True,
        enable_pit_traffic_ahead: bool = True,
        enable_pit_overlap: bool = True,
    ):
        super().__init__(
            role_id=role_id,
            name=name,
            description=description,
            priority=priority,
            enabled=enabled,
            audio_engine=audio_engine,
        )
        self.state = PitlaneSpotterState.IDLE
        self.unsafe_release_distance_m = float(unsafe_release_distance_m)
        self.unsafe_release_ttc_sec = float(unsafe_release_ttc_sec)
        self.pit_slow_ahead_distance_m = float(pit_slow_ahead_distance_m)
        self.pit_slow_speed_threshold_mps = float(pit_slow_speed_threshold_kmh) / 3.6
        self.enable_unsafe_release = bool(enable_unsafe_release)
        self.enable_pit_traffic_ahead = bool(enable_pit_traffic_ahead)
        self.enable_pit_overlap = bool(enable_pit_overlap)

        # Variables dynamiques de suivi
        self.target_threat_id: Optional[int] = None
        self.target_threat_name: str = ""
        self._last_state_change_time: float = 0.0
        self._last_alert_time: float = 0.0
        self._was_in_box: bool = False
        self._hazard_cleared: bool = False

        # Diagnostic en direct
        self._live_hazard_dist: float = 0.0
        self._live_hazard_speed_kmh: float = 0.0
        self._live_hazard_ttc: float = float("inf")
        self._live_pit_info: str = "Track clear"

    @property
    def pit_slow_speed_threshold_kmh(self) -> float:
        return round(self.pit_slow_speed_threshold_mps * 3.6, 1)

    @pit_slow_speed_threshold_kmh.setter
    def pit_slow_speed_threshold_kmh(self, value: float) -> None:
        self.pit_slow_speed_threshold_mps = float(value) / 3.6

    def get_parameters(self) -> List[RoleParam]:
        return [
            BoolParam(
                name="enable_unsafe_release",
                label="Protection Unsafe Release",
                default=True,
                description="Alerte si une voiture arrive dans la voie rapide lors de l'arrêt ou de la sortie de box",
            ),
            FloatRangeParam(
                name="unsafe_release_distance_m",
                label="Distance Alerte Fast Lane",
                min_val=10.0,
                max_val=60.0,
                step=2.0,
                unit="m",
                default=28.0,
                description="Distance arrière maximale dans la voie rapide pour déclencher l'alerte de danger",
            ),
            FloatRangeParam(
                name="unsafe_release_ttc_sec",
                label="Seuil TTC Fast Lane",
                min_val=1.0,
                max_val=5.0,
                step=0.2,
                unit="s",
                default=2.5,
                description="Temps avant collision (TTC) déclenchant le danger de sortie de stand",
            ),
            BoolParam(
                name="enable_pit_traffic_ahead",
                label="Alerte Ralentissement Pitlane",
                default=True,
                description="Alerte sur les véhicules arrêtés ou au ralenti devant en voie des stands",
            ),
            FloatRangeParam(
                name="pit_slow_ahead_distance_m",
                label="Distance Détection Devant",
                min_val=15.0,
                max_val=80.0,
                step=5.0,
                unit="m",
                default=35.0,
                description="Distance maximale devant pour détecter un véhicule ralenti dans la pitlane",
            ),
            BoolParam(
                name="enable_pit_overlap",
                label="Alerte Côte-à-Côte Pitlane",
                default=True,
                description="Avertit lorsqu'une voiture s'insère à côté dans la pitlane (Alongside)",
            ),
        ]

    def is_busy(self) -> bool:
        """Est occupé si un danger d'unsafe release ou une alerte trafic est active."""
        return self.state in (
            PitlaneSpotterState.UNSAFE_HAZARD,
            PitlaneSpotterState.RELEASE_CLEAR,
            PitlaneSpotterState.PIT_TRAFFIC_AHEAD,
            PitlaneSpotterState.PIT_OVERLAP,
        )

    def update(self, context: EngineerContext) -> Optional[EngineerMessage]:
        if not self.enabled or not context.scoring or context.is_private_qualifying():
            if self.state != PitlaneSpotterState.IDLE:
                self.reset()
            return None

        # Si le joueur N'EST PAS dans la pitlane, le rôle reste en veille
        if not context.is_player_in_pits() and not context.is_player_in_garage():
            if self.state != PitlaneSpotterState.IDLE:
                self.reset()
            return None

        player_veh = context.get_player_vehicle()
        if not player_veh:
            if self.state != PitlaneSpotterState.IDLE:
                self.reset()
            return None

        player_speed = context.get_player_speed_mps()
        track_length = context.get_track_length()
        pit_opponents = context.get_pit_opponents()

        # Évaluer si le joueur est au box (arrêt / révision / démarrage)
        pit_state = int(get_vehicle_attr(player_veh, "pit_state", 0))
        in_garage = bool(get_vehicle_attr(player_veh, "in_garage_stall", False))
        is_stationary_or_in_box = (
            in_garage
            or pit_state in (3, 4)  # 3=stopped, 4=exiting
            or player_speed < 2.5   # Arrêté ou très lent dans le box
        )

        now = time.time()

        # =========================================================================
        # 1. CAS DU JOUEUR AU BOX / ARRÊT AU STAND (PROTECTION UNSAFE RELEASE)
        # =========================================================================
        if is_stationary_or_in_box and self.enable_unsafe_release:
            self._was_in_box = True
            return self._handle_unsafe_release_monitoring(context, player_veh, pit_opponents, track_length, now)

        # Si le joueur roule dans la pitlane après un arrêt où un danger avait été signalé
        if self._was_in_box and self.state == PitlaneSpotterState.UNSAFE_HAZARD:
            # Si le danger est passé alors que le joueur démarre
            return self._check_release_clear(now)

        # =========================================================================
        # 2. CAS DU JOUEUR EN CIRCULATION DANS LA PITLANE (SOUS PIT LIMITER)
        # =========================================================================
        self._was_in_box = False
        return self._handle_pitlane_driving_traffic(context, player_veh, player_speed, pit_opponents, track_length, now)

    def _handle_unsafe_release_monitoring(
        self,
        context: EngineerContext,
        player_veh: Any,
        pit_opponents: List[Any],
        track_length: float,
        now: float,
    ) -> Optional[EngineerMessage]:
        """Surveille les voitures qui descendent la Fast Lane par l'arrière pour prévenir l'Unsafe Release."""
        threats = []

        for opp in pit_opponents:
            opp_speed = context.extract_vehicle_speed_mps(opp)
            dist_behind = context.compute_distance_behind(player_veh, opp, track_length)
            euc_dist = context.compute_euclidean_distance(player_veh, opp)
            dist_effective = min(dist_behind, euc_dist) if dist_behind > 0 else euc_dist

            # Une voiture est une menace si elle arrive par l'arrière dans la voie rapide
            # avec une vitesse significative (> 20 km/h) et à portée
            if 0.0 < dist_behind <= self.unsafe_release_distance_m or (0.0 < euc_dist <= self.unsafe_release_distance_m and dist_behind >= -2.0):
                speed_delta = max(0.1, opp_speed)
                ttc = dist_effective / speed_delta if speed_delta > 0.5 else float("inf")

                if opp_speed >= self.pit_slow_speed_threshold_mps and (dist_effective <= self.unsafe_release_distance_m or ttc <= self.unsafe_release_ttc_sec):
                    threats.append({
                        "id": get_vehicle_attr(opp, "id", -1),
                        "name": get_vehicle_attr(opp, "driver_name", "Opponent"),
                        "speed_mps": opp_speed,
                        "dist": dist_effective,
                        "ttc": ttc,
                        "opp": opp,
                    })

        if threats:
            threats.sort(key=lambda t: t["ttc"])
            target = threats[0]

            self.target_threat_id = target["id"]
            self.target_threat_name = target["name"]
            self._live_hazard_dist = target["dist"]
            self._live_hazard_speed_kmh = target["speed_mps"] * 3.6
            self._live_hazard_ttc = target["ttc"]
            self._live_pit_info = f"UNSAFE HAZARD: {target['name']} ({self._live_hazard_speed_kmh:.0f} km/h, {self._live_hazard_dist:.0f}m behind)"

            if self.state != PitlaneSpotterState.UNSAFE_HAZARD:
                self.state = PitlaneSpotterState.UNSAFE_HAZARD
                self._last_state_change_time = now
                self._last_alert_time = now
                self._hazard_cleared = False

                # Annonce immédiate et interruptive de danger
                msg = EngineerMessage(
                    phrase_key="car",
                    priority=self.priority,
                    interrupt=True,
                    role_id=self.role_id,
                )
                self.emit_sound("car", interrupt=True)
                return msg

            return None

        # Si aucune menace n'est détectée
        self._live_hazard_dist = 0.0
        self._live_hazard_speed_kmh = 0.0
        self._live_hazard_ttc = float("inf")

        # Si on était en alerte de danger et que la voie vient de se libérer -> Safe Release !
        if self.state == PitlaneSpotterState.UNSAFE_HAZARD:
            self.state = PitlaneSpotterState.RELEASE_CLEAR
            self._last_state_change_time = now
            self._live_pit_info = "Fast Lane CLEAR (Safe to release)"

            msg = EngineerMessage(
                phrase_key="clear",
                priority=self.priority,
                interrupt=True,
                role_id=self.role_id,
            )
            self.emit_sound("clear", interrupt=True)
            return msg

        elif self.state == PitlaneSpotterState.RELEASE_CLEAR:
            if (now - self._last_state_change_time) > 2.0:
                self.state = PitlaneSpotterState.BOX_MONITORING
            return None

        self.state = PitlaneSpotterState.BOX_MONITORING
        self._live_pit_info = "Box monitoring — Fast lane clear"
        return None

    def _check_release_clear(self, now: float) -> Optional[EngineerMessage]:
        """Confirme que la voie est libre au moment du redémarrage."""
        self.state = PitlaneSpotterState.RELEASE_CLEAR
        self._last_state_change_time = now
        self._live_pit_info = "Pitlane Clear"
        msg = EngineerMessage(
            phrase_key="clear",
            priority=self.priority,
            interrupt=False,
            role_id=self.role_id,
        )
        self.emit_sound("clear", interrupt=False)
        return msg

    def _handle_pitlane_driving_traffic(
        self,
        context: EngineerContext,
        player_veh: Dict[str, Any],
        player_speed: float,
        pit_opponents: List[Dict[str, Any]],
        track_length: float,
        now: float,
    ) -> Optional[EngineerMessage]:
        """Gère le trafic lors de la circulation dans la pitlane sous limiteur de vitesse."""
        # 1. Détection de voiture ralentie / bloquée DEVANT dans la pitlane
        if self.enable_pit_traffic_ahead:
            slow_ahead = []
            for opp in pit_opponents:
                dist_behind = context.compute_distance_behind(player_veh, opp, track_length)
                euc_dist = context.compute_euclidean_distance(player_veh, opp)
                # dist_behind < 0 signifie devant
                if (-self.pit_slow_ahead_distance_m <= dist_behind < -2.0) or (0.0 < euc_dist <= self.pit_slow_ahead_distance_m and dist_behind < 0):
                    opp_speed = context.extract_vehicle_speed_mps(opp)
                    if opp_speed < self.pit_slow_speed_threshold_mps:
                        dist_ahead = abs(dist_behind) if dist_behind < 0 else euc_dist
                        slow_ahead.append((dist_ahead, opp_speed, opp))

            if slow_ahead:
                slow_ahead.sort(key=lambda x: x[0])
                closest_dist, closest_speed, closest_opp = slow_ahead[0]
                driver_name = get_vehicle_attr(closest_opp, "driver_name", "Car")
                self._live_pit_info = f"Slow car ahead in pits: {driver_name} ({closest_dist:.0f}m)"

                if self.state != PitlaneSpotterState.PIT_TRAFFIC_AHEAD:
                    self.state = PitlaneSpotterState.PIT_TRAFFIC_AHEAD
                    self._last_state_change_time = now

                    if (now - self._last_alert_time) > 6.0:
                        self._last_alert_time = now
                        msg = EngineerMessage(
                            phrase_key="car",
                            priority=self.priority,
                            interrupt=False,
                            role_id=self.role_id,
                        )
                        self.emit_sound("car", interrupt=False)
                        return msg
                return None

        # 2. Détection de véhicule bord à bord (Overlap) en pitlane
        if self.enable_pit_overlap:
            alongside_cars = []
            for opp in pit_opponents:
                dist_behind = context.compute_distance_behind(player_veh, opp, track_length)
                euc_dist = context.compute_euclidean_distance(player_veh, opp)
                if abs(dist_behind) <= 5.0 or euc_dist <= 5.5:
                    alongside_cars.append(opp)

            if alongside_cars:
                alongside_name = get_vehicle_attr(alongside_cars[0], "driver_name", "Car")
                self._live_pit_info = f"Car alongside in pitlane: {alongside_name}"
                if self.state != PitlaneSpotterState.PIT_OVERLAP:
                    self.state = PitlaneSpotterState.PIT_OVERLAP
                    self._last_state_change_time = now

                    if (now - self._last_alert_time) > 4.0:
                        self._last_alert_time = now
                        msg = EngineerMessage(
                            phrase_key="alongside",
                            priority=self.priority,
                            interrupt=True,
                            role_id=self.role_id,
                        )
                        self.emit_sound("alongside", interrupt=True)
                        return msg
                return None

        # Si la circulation est fluide et sans encombre
        if self.state in (PitlaneSpotterState.PIT_TRAFFIC_AHEAD, PitlaneSpotterState.PIT_OVERLAP):
            self.state = PitlaneSpotterState.IDLE
            self._live_pit_info = "Pitlane clear"
            return None

        self.state = PitlaneSpotterState.IDLE
        self._live_pit_info = "Pitlane clear"
        return None

    def reset(self) -> None:
        self.state = PitlaneSpotterState.IDLE
        self.target_threat_id = None
        self.target_threat_name = ""
        self._last_state_change_time = 0.0
        self._last_alert_time = 0.0
        self._was_in_box = False
        self._hazard_cleared = False
        self._live_hazard_dist = 0.0
        self._live_hazard_speed_kmh = 0.0
        self._live_hazard_ttc = float("inf")
        self._live_pit_info = "Track clear"

    def get_config(self) -> Dict[str, Any]:
        cfg = super().get_config()
        cfg.update({
            "unsafe_release_distance_m": self.unsafe_release_distance_m,
            "unsafe_release_ttc_sec": self.unsafe_release_ttc_sec,
            "pit_slow_ahead_distance_m": self.pit_slow_ahead_distance_m,
            "pit_slow_speed_threshold_kmh": self.pit_slow_speed_threshold_mps * 3.6,
            "enable_unsafe_release": self.enable_unsafe_release,
            "enable_pit_traffic_ahead": self.enable_pit_traffic_ahead,
            "enable_pit_overlap": self.enable_pit_overlap,
        })
        return cfg

    def set_config(self, config: Dict[str, Any]) -> None:
        super().set_config(config)
        if "unsafe_release_distance_m" in config:
            self.unsafe_release_distance_m = float(config["unsafe_release_distance_m"])
        if "unsafe_release_ttc_sec" in config:
            self.unsafe_release_ttc_sec = float(config["unsafe_release_ttc_sec"])
        if "pit_slow_ahead_distance_m" in config:
            self.pit_slow_ahead_distance_m = float(config["pit_slow_ahead_distance_m"])
        if "pit_slow_speed_threshold_kmh" in config:
            self.pit_slow_speed_threshold_mps = float(config["pit_slow_speed_threshold_kmh"]) / 3.6
        if "enable_unsafe_release" in config:
            self.enable_unsafe_release = bool(config["enable_unsafe_release"])
        if "enable_pit_traffic_ahead" in config:
            self.enable_pit_traffic_ahead = bool(config["enable_pit_traffic_ahead"])
        if "enable_pit_overlap" in config:
            self.enable_pit_overlap = bool(config["enable_pit_overlap"])

    def get_state_summary(self) -> Dict[str, Any]:
        summary = super().get_state_summary()
        summary.update({
            "fsm_state": self.state.value,
            "target_threat": self.target_threat_name or "None",
            "live_hazard_dist": round(self._live_hazard_dist, 1),
            "live_hazard_speed_kmh": round(self._live_hazard_speed_kmh, 1),
            "live_hazard_ttc": round(self._live_hazard_ttc, 1) if self._live_hazard_ttc < 99 else "--",
            "pit_info": self._live_pit_info,
            "is_busy": self.is_busy(),
        })
        return summary
