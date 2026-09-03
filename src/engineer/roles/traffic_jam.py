"""
SimPad Race Engineer — Rôle Traffic Jam / Véhicules Ralentis devant.
Surveille la piste devant le joueur pour détecter les ralentissements soudains,
voitures en perdition ou embouteillages.
"""

import time
import logging
from typing import Optional, Dict, Any, List
from src.engineer.base import BaseRole, EngineerMessage, RoleStatus
from src.engineer.context import EngineerContext, get_vehicle_attr
from src.engineer.registry import RoleRegistry
from src.engineer.params import RoleParam, FloatRangeParam, BoolParam
from src.telemetry.reference_profile import ReferenceLapProfile

logger = logging.getLogger(__name__)


@RoleRegistry.register(
    role_id="traffic_jam",
    name="Traffic Jam (Slow Cars Ahead)",
    description="Alerte lorsque des véhicules sont au ralenti ou accidentés devant le joueur sur la trajectoire.",
    default_priority=75,
)
class TrafficJamRole(BaseRole):
    """
    Rôle surveillant les voitures lentes ou à l'arrêt devant le joueur.
    """

    def __init__(
        self,
        role_id: str = "traffic_jam",
        name: str = "Traffic Jam (Slow Cars Ahead)",
        description: str = "",
        priority: int = 75,
        enabled: bool = True,
        audio_engine: Optional[Any] = None,
        slow_speed_threshold_kmh: float = 50.0,
        warning_distance_m: float = 180.0,
        cooldown_sec: float = 8.0,
        enable_ref_lap_filter: bool = True,
        domain_speed_tolerance_kmh: float = 30.0,
    ):
        super().__init__(
            role_id=role_id,
            name=name,
            description=description,
            priority=priority,
            enabled=enabled,
            audio_engine=audio_engine,
        )
        self.slow_speed_threshold_mps = float(slow_speed_threshold_kmh) / 3.6
        self.warning_distance_m = float(warning_distance_m)
        self.cooldown_sec = float(cooldown_sec)
        self.enable_ref_lap_filter = bool(enable_ref_lap_filter)
        self.domain_speed_tolerance_kmh = float(domain_speed_tolerance_kmh)
        self._custom_profile: Optional[ReferenceLapProfile] = None

        self._last_alert_time: float = 0.0
        self._is_active_alert: bool = False
        self._target_slow_car_info: str = ""

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
    def slow_speed_threshold_kmh(self) -> float:
        return round(self.slow_speed_threshold_mps * 3.6, 1)

    @slow_speed_threshold_kmh.setter
    def slow_speed_threshold_kmh(self, value: float) -> None:
        self.slow_speed_threshold_mps = float(value) / 3.6

    def get_parameters(self) -> List[RoleParam]:
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
                name="slow_speed_threshold_kmh",
                label="Vitesse Seuil Ralenti",
                min_val=10.0,
                max_val=120.0,
                step=5.0,
                unit="km/h",
                default=50.0,
                description="Vitesse sous laquelle une voiture devant est considérée au ralenti/accidentée",
            ),
            FloatRangeParam(
                name="warning_distance_m",
                label="Distance d'Alerte",
                min_val=50.0,
                max_val=400.0,
                step=10.0,
                unit="m",
                default=180.0,
                description="Distance maximale devant le joueur pour détecter les ralentissements",
            ),
            FloatRangeParam(
                name="cooldown_sec",
                label="Cooldown Alerte",
                min_val=2.0,
                max_val=30.0,
                step=1.0,
                unit="s",
                default=8.0,
                description="Délai minimal entre deux alertes vocales",
            ),
        ]

    def get_channel_requirements(self) -> List[Any]:
        try:
            from simpad_qt.core.telemetry_channels import TelemetryChannel, ChannelRequirement
            return [
                ChannelRequirement(
                    channel=TelemetryChannel.FULL_SCORING,
                    preferred_hz=10,
                    required=True,
                    reason="Positions et vitesses scalaires des adversaires devant sur la trajectoire",
                ),
                ChannelRequirement(
                    channel=TelemetryChannel.COMPACT_SCORING,
                    preferred_hz=10,
                    required=False,
                    reason="Spline de piste et calcul de distance relative devant",
                ),
            ]
        except ImportError:
            return []

    def get_sound_requirements(self) -> Dict[str, str]:
        return {
            "car": "Car",
        }

    def is_busy(self) -> bool:
        """Occupé si une alerte de trafic ralenti est active."""
        return self._is_active_alert

    def update(self, context: EngineerContext) -> Optional[EngineerMessage]:
        if not self.enabled or not context.scoring or context.is_private_qualifying():
            self._is_active_alert = False
            self._target_slow_car_info = ""
            return None

        player_veh = context.get_player_vehicle()
        if not player_veh:
            self._is_active_alert = False
            return None

        # Si le joueur est dans la pitlane ou au garage, désactiver l'alerte bouchon sur piste
        if context.is_player_in_pits() or context.is_player_in_garage():
            self._is_active_alert = False
            self._target_slow_car_info = ""
            return None

        now = time.time()
        track_length = context.get_track_length()
        opponents = context.get_track_opponents()
        ref_prof = self.get_reference_profile(context)
        has_valid_ref = bool(ref_prof and getattr(ref_prof, "num_points", 0) >= 2)

        slow_cars_ahead = []
        for opp in opponents:
            dist_behind = context.compute_distance_behind(player_veh, opp, track_length)
            # dist_behind < 0 signifie que la voiture est DEVANT le joueur
            if -self.warning_distance_m <= dist_behind < -5.0:
                opp_speed = context.extract_vehicle_speed_mps(opp)
                if opp_speed < self.slow_speed_threshold_mps:
                    # Filtre du tour de référence : il faut au moins soit moi, soit l'autre hors domaine
                    if self.enable_ref_lap_filter and has_valid_ref:
                        if not context.has_traffic_domain_anomaly(
                            player_veh,
                            opp,
                            profile=ref_prof,
                            tolerance_kmh=self.domain_speed_tolerance_kmh,
                        ):
                            continue

                    dist_ahead = abs(dist_behind)
                    slow_cars_ahead.append((dist_ahead, opp_speed, opp))

        if slow_cars_ahead:
            self._is_active_alert = True
            slow_cars_ahead.sort(key=lambda x: x[0])
            closest_dist, closest_speed, closest_opp = slow_cars_ahead[0]
            driver_name = get_vehicle_attr(closest_opp, "driver_name", "Car")
            self._target_slow_car_info = f"{driver_name} ({closest_speed * 3.6:.0f} km/h, {closest_dist:.0f}m ahead)"

            if (now - self._last_alert_time) > self.cooldown_sec:
                self._last_alert_time = now
                msg = EngineerMessage(
                    phrase_key="car",
                    priority=self.priority,
                    interrupt=False,
                    role_id=self.role_id,
                )
                self.emit_sound("car", interrupt=False)
                return msg
        else:
            self._is_active_alert = False
            self._target_slow_car_info = ""

        return None

    def reset(self) -> None:
        self._last_alert_time = 0.0
        self._is_active_alert = False
        self._target_slow_car_info = ""

    def get_config(self) -> Dict[str, Any]:
        cfg = super().get_config()
        cfg.update({
            "slow_speed_threshold_kmh": self.slow_speed_threshold_mps * 3.6,
            "warning_distance_m": self.warning_distance_m,
            "cooldown_sec": self.cooldown_sec,
            "enable_ref_lap_filter": self.enable_ref_lap_filter,
            "domain_speed_tolerance_kmh": self.domain_speed_tolerance_kmh,
        })
        return cfg

    def set_config(self, config: Dict[str, Any]) -> None:
        super().set_config(config)
        if "slow_speed_threshold_kmh" in config:
            self.slow_speed_threshold_mps = float(config["slow_speed_threshold_kmh"]) / 3.6
        if "warning_distance_m" in config:
            self.warning_distance_m = float(config["warning_distance_m"])
        if "cooldown_sec" in config:
            self.cooldown_sec = float(config["cooldown_sec"])
        if "enable_ref_lap_filter" in config:
            self.enable_ref_lap_filter = bool(config["enable_ref_lap_filter"])
        if "domain_speed_tolerance_kmh" in config:
            self.domain_speed_tolerance_kmh = float(config["domain_speed_tolerance_kmh"])

    def get_state_summary(self) -> Dict[str, Any]:
        summary = super().get_state_summary()
        summary.update({
            "is_alert_active": self._is_active_alert,
            "slow_car_info": self._target_slow_car_info or "Clear ahead",
            "enable_ref_lap_filter": self.enable_ref_lap_filter,
            "domain_speed_tolerance_kmh": self.domain_speed_tolerance_kmh,
            "is_busy": self.is_busy(),
        })
        return summary
