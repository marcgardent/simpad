"""
SimPad Race Engineer — Rôle Traffic Jam / Véhicules Ralentis devant.
Surveille la piste devant le joueur pour détecter les ralentissements soudains,
voitures en perdition ou embouteillages.
"""

import time
import logging
from typing import Optional, Dict, Any
from src.engineer.base import BaseRole, EngineerMessage, RoleStatus
from src.engineer.context import EngineerContext
from src.engineer.registry import RoleRegistry

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
    ):
        super().__init__(
            role_id=role_id,
            name=name,
            description=description,
            priority=priority,
            enabled=enabled,
            audio_engine=audio_engine,
        )
        self.slow_speed_threshold_mps = slow_speed_threshold_kmh / 3.6
        self.warning_distance_m = warning_distance_m
        self.cooldown_sec = cooldown_sec

        self._last_alert_time: float = 0.0
        self._is_active_alert: bool = False
        self._target_slow_car_info: str = ""

    def is_busy(self) -> bool:
        """Occupé si une alerte de trafic ralenti est active."""
        return self._is_active_alert

    def update(self, context: EngineerContext) -> Optional[EngineerMessage]:
        if not self.enabled or not context.scoring:
            self._is_active_alert = False
            return None

        player_veh = context.get_player_vehicle()
        if not player_veh:
            self._is_active_alert = False
            return None

        now = time.time()
        track_length = context.get_track_length()
        opponents = context.get_opponent_vehicles(include_pits=False)

        slow_cars_ahead = []
        for opp in opponents:
            dist_behind = context.compute_distance_behind(player_veh, opp, track_length)
            # dist_behind < 0 signifie que la voiture est DEVANT le joueur
            if -self.warning_distance_m <= dist_behind < -5.0:
                opp_speed = context.extract_vehicle_speed_mps(opp)
                if opp_speed < self.slow_speed_threshold_mps:
                    dist_ahead = abs(dist_behind)
                    slow_cars_ahead.append((dist_ahead, opp_speed, opp))

        if slow_cars_ahead:
            self._is_active_alert = True
            slow_cars_ahead.sort(key=lambda x: x[0])
            closest_dist, closest_speed, closest_opp = slow_cars_ahead[0]
            self._target_slow_car_info = f"{closest_opp.get('mDriverName', 'Car')} ({closest_speed * 3.6:.0f} km/h, {closest_dist:.0f}m ahead)"

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

    def get_state_summary(self) -> Dict[str, Any]:
        summary = super().get_state_summary()
        summary.update({
            "is_alert_active": self._is_active_alert,
            "slow_car_info": self._target_slow_car_info or "Clear ahead",
            "is_busy": self.is_busy(),
        })
        return summary
