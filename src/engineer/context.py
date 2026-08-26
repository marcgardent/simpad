"""
SimPad Race Engineer — Contexte d'évaluation pour les rôles de l'ingénieur de course.
Fournit un accès unifié, propre et optimisé à la télémétrie et aux données de scoring (LMU).
"""

import math
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple
from src.telemetry.lmu_parser import TelemetryData


@dataclass
class EngineerContext:
    """
    Objet de contexte transmis aux rôles lors de chaque cycle de calcul.
    Encapsule la télémétrie physique et les informations globales de scoring/session.
    """
    telemetry: Optional[TelemetryData] = None
    scoring: Optional[Dict[str, Any]] = None
    timestamp: float = field(default_factory=time.time)
    audio_engine: Optional[Any] = None

    def get_track_length(self) -> float:
        """Retourne la longueur totale du circuit en mètres."""
        if self.scoring:
            lap_dist = float(self.scoring.get("mLapDist", self.scoring.get("lapDist", 0.0)))
            if lap_dist > 500.0:
                return lap_dist
        return 5000.0  # Valeur par défaut de repli

    def get_player_vehicle(self) -> Optional[Dict[str, Any]]:
        """Extrait le véhicule du joueur depuis la liste des véhicules scoring."""
        if not self.scoring:
            return None
        vehicles = self.scoring.get("mVehicles", [])
        if not isinstance(vehicles, list):
            return None

        # Priorité au flag explicite isPlayer
        for v in vehicles:
            if isinstance(v, dict) and (v.get("mIsPlayer") or v.get("isPlayer")):
                return v

        # Repli sur le contrôle joueur local (mControl == 0)
        for v in vehicles:
            if isinstance(v, dict) and v.get("mControl") == 0:
                return v

        return None

    def get_opponent_vehicles(self, include_pits: bool = False) -> List[Dict[str, Any]]:
        """
        Retourne la liste des véhicules adverses actifs en piste.
        Exclut le joueur, les véhicules au garage, et optionnellement les voitures aux stands.
        """
        if not self.scoring:
            return []
        vehicles = self.scoring.get("mVehicles", [])
        if not isinstance(vehicles, list):
            return []

        opponents = []
        for v in vehicles:
            if not isinstance(v, dict):
                continue
            if v.get("mIsPlayer") or v.get("isPlayer") or v.get("mControl") == 0:
                continue
            if v.get("mInGarageStall") or v.get("inGarageStall"):
                continue
            if not include_pits and (v.get("mInPits") or v.get("inPits")):
                continue
            # Exclure les voitures ayant abandonné (finishStatus != 0)
            if v.get("mFinishStatus", 0) not in (0, "0"):
                continue

            opponents.append(v)

        return opponents

    @classmethod
    def extract_vehicle_speed_mps(cls, veh: Dict[str, Any]) -> float:
        """Calcule la vitesse scalaire en m/s d'un véhicule depuis son vecteur de vitesse locale."""
        vel = veh.get("mLocalVel") or veh.get("localVel")
        if isinstance(vel, dict):
            vx = float(vel.get("x", 0.0))
            vy = float(vel.get("y", 0.0))
            vz = float(vel.get("z", 0.0))
            return math.sqrt(vx * vx + vy * vy + vz * vz)
        elif isinstance(vel, (list, tuple)) and len(vel) >= 3:
            return math.sqrt(float(vel[0])**2 + float(vel[1])**2 + float(vel[2])**2)
        elif "mSpeed" in veh or "speed" in veh:
            return float(veh.get("mSpeed", veh.get("speed", 0.0)))
        return 0.0

    def get_player_speed_mps(self) -> float:
        """Retourne la vitesse instantanée du joueur en m/s."""
        # 1. Depuis la télémétrie haute fréquence si disponible
        if self.telemetry and self.telemetry.longitudinal_ground_vel:
            speeds = [abs(v) for v in self.telemetry.longitudinal_ground_vel if isinstance(v, (int, float))]
            if speeds:
                return max(speeds)

        # 2. Depuis le véhicule joueur dans le scoring
        player_veh = self.get_player_vehicle()
        if player_veh:
            return self.extract_vehicle_speed_mps(player_veh)

        return 0.0

    def compute_distance_behind(
        self,
        player_veh: Dict[str, Any],
        opp_veh: Dict[str, Any],
        track_length: Optional[float] = None,
    ) -> float:
        """
        Calcule la distance relative le long de la spline du circuit.
        - Valeur > 0 : L'adversaire est DERRIÈRE le joueur (en mètres).
        - Valeur < 0 : L'adversaire est DEVANT le joueur (en mètres).
        Gère le rebouclage de la ligne de départ/arrivée (wraparound).
        """
        l_track = track_length or self.get_track_length()
        p_dist = float(player_veh.get("mLapDist", player_veh.get("lapDist", 0.0))) % l_track
        o_dist = float(opp_veh.get("mLapDist", opp_veh.get("lapDist", 0.0))) % l_track

        delta = (p_dist - o_dist) % l_track
        if delta < l_track / 2.0:
            return delta  # Adversaire derrière
        else:
            return delta - l_track  # Adversaire devant (valeur négative)

    @classmethod
    def compute_euclidean_distance(cls, veh_a: Dict[str, Any], veh_b: Dict[str, Any]) -> float:
        """Calcule la distance euclidienne 3D entre deux véhicules si la position mPos est disponible."""
        pos_a = veh_a.get("mPos") or veh_a.get("pos")
        pos_b = veh_b.get("mPos") or veh_b.get("pos")
        if not pos_a or not pos_b:
            return float("inf")

        def _get_xyz(p):
            if isinstance(p, dict):
                return float(p.get("x", 0.0)), float(p.get("y", 0.0)), float(p.get("z", 0.0))
            elif isinstance(p, (list, tuple)) and len(p) >= 3:
                return float(p[0]), float(p[1]), float(p[2])
            return 0.0, 0.0, 0.0

        xa, ya, za = _get_xyz(pos_a)
        xb, yb, zb = _get_xyz(pos_b)
        return math.sqrt((xa - xb)**2 + (ya - yb)**2 + (za - zb)**2)
