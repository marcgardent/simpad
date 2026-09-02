"""
SimPad Race Engineer — Contexte d'évaluation pour les rôles de l'ingénieur de course.
Fournit un accès unifié, propre et optimisé à la télémétrie et aux données de scoring (LMU).
"""

import math
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple, Union

try:
    from isimotor_rawudp_client import (
        TelemInfo,
        CompactScoring,
        FullScoringSession,
        VehicleScoring,
    )
except ImportError:
    TelemInfo = Any  # type: ignore
    CompactScoring = Any  # type: ignore
    FullScoringSession = Any  # type: ignore
    VehicleScoring = Any  # type: ignore

from src.telemetry.lmu_parser import TelemetryData


ATTRIBUTE_CANDIDATES_MAP: Dict[str, List[str]] = {
    "id": ["id", "mID", "m_id", "ID"],
    "mID": ["id", "mID", "m_id", "ID"],
    "driver_name": ["driver_name", "mDriverName", "driverName"],
    "mDriverName": ["driver_name", "mDriverName", "driverName"],
    "vehicle_name": ["vehicle_name", "mVehicleName", "vehicleName"],
    "mVehicleName": ["vehicle_name", "mVehicleName", "vehicleName"],
    "pit_state": ["pit_state", "mPitState", "pitState"],
    "mPitState": ["pit_state", "mPitState", "pitState"],
    "in_garage_stall": ["in_garage_stall", "mInGarageStall", "inGarageStall"],
    "mInGarageStall": ["in_garage_stall", "mInGarageStall", "inGarageStall"],
    "in_pits": ["in_pits", "mInPits", "inPits"],
    "mInPits": ["in_pits", "mInPits", "inPits"],
    "lap_dist": ["lap_dist", "mLapDist", "lapDist"],
    "mLapDist": ["lap_dist", "mLapDist", "lapDist"],
    "total_laps": ["total_laps", "mTotalLaps", "totalLaps"],
    "mTotalLaps": ["total_laps", "mTotalLaps", "totalLaps"],
    "count_lap_flag": ["count_lap_flag", "mCountLapFlag", "countLapFlag"],
    "mCountLapFlag": ["count_lap_flag", "mCountLapFlag", "countLapFlag"],
    "is_player": ["is_player", "mIsPlayer", "isPlayer"],
    "mIsPlayer": ["is_player", "mIsPlayer", "isPlayer"],
    "control": ["control", "mControl"],
    "mControl": ["control", "mControl"],
    "finish_status": ["finish_status", "mFinishStatus", "finishStatus"],
    "mFinishStatus": ["finish_status", "mFinishStatus", "finishStatus"],
    "speed": ["speed_mps", "speed", "mSpeed", "forward_speed_mps"],
    "speed_mps": ["speed_mps", "speed", "mSpeed", "forward_speed_mps"],
    "mSpeed": ["speed_mps", "speed", "mSpeed", "forward_speed_mps"],
    "sector": ["sector", "mSector"],
    "mSector": ["sector", "mSector"],
    "pos": ["pos", "mPos"],
    "mPos": ["pos", "mPos"],
    "local_vel": ["local_vel", "mLocalVel", "localVel"],
    "mLocalVel": ["local_vel", "mLocalVel", "localVel"],
    "ori": ["ori", "mOri"],
    "mOri": ["ori", "mOri"],
}


def get_vehicle_attr(veh: Any, key: str, default: Any = None) -> Any:
    """
    Récupère un attribut ou une clé de dictionnaire de façon universelle, bidirectionnelle et sûre
    pour un véhicule (VehicleScoring typé ou dictionnaire de télémétrie).
    """
    if veh is None:
        return default

    candidates = ATTRIBUTE_CANDIDATES_MAP.get(key, [key])
    if key not in candidates:
        candidates = [key] + candidates

    # 1. Si c'est un dictionnaire
    if isinstance(veh, dict):
        for candidate in candidates:
            if candidate in veh and veh[candidate] is not None:
                return veh[candidate]
        return default

    # 2. Si c'est un objet (ex: VehicleScoring de isimotor_rawudp_client)
    for candidate in candidates:
        if hasattr(veh, candidate):
            val = getattr(veh, candidate)
            if val is not None:
                return val

    return default


@dataclass
class EngineerContext:
    """
    Objet de contexte transmis aux rôles lors de chaque cycle de calcul.
    Encapsule la télémétrie physique et les informations globales de scoring/session (dict ou modèles typés isimotor).
    """
    telemetry: Optional[Union[TelemetryData, TelemInfo, Any]] = None
    scoring: Optional[Union[Dict[str, Any], FullScoringSession, CompactScoring, Any]] = None
    timestamp: float = field(default_factory=time.time)
    audio_engine: Optional[Any] = None
    reference_profile: Optional[Any] = None

    @staticmethod
    def get_attr(veh: Any, key: str, default: Any = None) -> Any:
        """Méthode statique utilitaire pour accéder aux attributs d'un véhicule."""
        return get_vehicle_attr(veh, key, default)

    def get_session_type(self) -> int:
        """
        Retourne le code mSession reçu dans le paquet de scoring (LMU / rF2) :
        0 = TestDay
        1..4 = Practice (FP1 à FP4)
        5..8 = Qualifying (Q1 à Q4 / Hyperpole / Private Qual)
        9 = Warmup
        10..13 = Race (Course 1 à 4)
        Retourne -1 si non disponible.
        """
        if self.scoring is not None:
            if hasattr(self.scoring, "session"):
                try:
                    return int(self.scoring.session)
                except (ValueError, TypeError):
                    pass
            elif isinstance(self.scoring, dict):
                try:
                    return int(self.scoring.get("mSession", self.scoring.get("session", -1)))
                except (ValueError, TypeError):
                    pass
        return -1

    def is_qualifying_session(self) -> bool:
        """Indique si la session active est une qualification (mSession entre 5 et 8 inclus)."""
        return self.get_session_type() in (5, 6, 7, 8)

    def is_private_qualifying(self) -> bool:
        """
        Indique si la session active est en qualification privée (Private Qualifying).
        Dans Le Mans Ultimate, les sessions de qualification (mSession 5-8) sont isolées
        (voitures fantômes/invisibles, aucun contact physique possible).
        """
        return self.is_qualifying_session()

    def get_track_name(self) -> str:
        """Retourne le nom du circuit actif depuis le paquet de scoring ou le profil de référence."""
        if self.scoring is not None:
            if hasattr(self.scoring, "track_name"):
                name = str(self.scoring.track_name).strip()
                if name:
                    return name
            elif isinstance(self.scoring, dict):
                name = str(self.scoring.get("mTrackName", self.scoring.get("trackName", ""))).strip()
                if name:
                    return name

        if self.reference_profile is not None:
            ref_name = getattr(self.reference_profile, "track_name", "")
            if ref_name:
                return ref_name
        try:
            from src.telemetry.lmu_parser import LMUParser
            delta_eng = getattr(LMUParser, "_delta_engine", None)
            if delta_eng and delta_eng.track_name:
                return delta_eng.track_name
        except Exception:
            pass
        return ""

    def get_reference_profile(self) -> Optional[Any]:
        """Retourne le profil du tour de référence actif s'il correspond au circuit en cours."""
        scoring_track = self.get_track_name()

        if self.reference_profile is not None:
            ref_track = getattr(self.reference_profile, "track_name", "")
            if scoring_track and ref_track:
                t1 = "".join(c for c in scoring_track if c.isalnum()).lower()
                t2 = "".join(c for c in ref_track if c.isalnum()).lower()
                if t1 and t2 and t1 != t2:
                    return None
            return self.reference_profile

        try:
            from src.telemetry.lmu_parser import LMUParser
            delta_eng = getattr(LMUParser, "_delta_engine", None)
            if delta_eng:
                # L'ingénieur de piste (trafic, repères) utilise systématiquement le tour de référence absolu
                prof = delta_eng.all_time_best_profile or delta_eng.current_profile
                if prof:
                    ref_track = getattr(prof, "track_name", "")
                    if scoring_track and ref_track:
                        t1 = "".join(c for c in scoring_track if c.isalnum()).lower()
                        t2 = "".join(c for c in ref_track if c.isalnum()).lower()
                        if t1 and t2 and t1 != t2:
                            return None
                    return prof
        except Exception:
            pass
        return None

    def get_reference_speed_mps(
        self,
        track_dist: float,
        profile: Optional[Any] = None,
    ) -> Optional[float]:
        """Retourne la vitesse du tour de référence à une position de piste donnée (m/s)."""
        ref_prof = profile or self.get_reference_profile()
        if not ref_prof or getattr(ref_prof, "num_points", 0) < 2:
            return None
        val = ref_prof.get_value_at_dist(track_dist)
        return float(val.get("speed_ms", 0.0))

    def is_speed_in_normal_domain(
        self,
        speed_mps: float,
        track_dist: float,
        profile: Optional[Any] = None,
        tolerance_kmh: float = 30.0,
    ) -> bool:
        """
        Vérifie si une vitesse donnée est dans le 'domaine normal'
        par rapport au tour de référence à une position précise du circuit.
        """
        ref_prof = profile or self.get_reference_profile()
        if not ref_prof or getattr(ref_prof, "num_points", 0) < 2:
            return True

        val = ref_prof.get_value_at_dist(track_dist)
        ref_speed_mps = float(val.get("speed_ms", 0.0))
        ref_speed_kmh = ref_speed_mps * 3.6
        actual_speed_kmh = speed_mps * 3.6

        # Si le tour de référence n'a pas de vitesse valide à cet endroit
        if ref_speed_kmh <= 1.0:
            return True

        delta_kmh = abs(actual_speed_kmh - ref_speed_kmh)
        return delta_kmh <= float(tolerance_kmh)

    def is_vehicle_in_normal_domain(
        self,
        veh: Any,
        profile: Optional[Any] = None,
        tolerance_kmh: float = 30.0,
    ) -> bool:
        """
        Détermine si un véhicule roule dans son domaine de vitesse 'normal'
        selon sa position sur la piste.
        """
        if veh is None:
            return True
        track_len = self.get_track_length()
        lap_dist = float(get_vehicle_attr(veh, "lap_dist", 0.0)) % track_len

        speed_mps = self.extract_vehicle_speed_mps(veh)
        return self.is_speed_in_normal_domain(
            speed_mps=speed_mps,
            track_dist=lap_dist,
            profile=profile,
            tolerance_kmh=tolerance_kmh,
        )

    def is_player_in_normal_domain(
        self,
        profile: Optional[Any] = None,
        tolerance_kmh: float = 30.0,
    ) -> bool:
        """Détermine si le véhicule du joueur roule dans son domaine de vitesse normal."""
        player_veh = self.get_player_vehicle()
        if not player_veh:
            return True
        track_len = self.get_track_length()
        lap_dist = float(get_vehicle_attr(player_veh, "lap_dist", 0.0)) % track_len
        player_speed = self.get_player_speed_mps()
        return self.is_speed_in_normal_domain(
            speed_mps=player_speed,
            track_dist=lap_dist,
            profile=profile,
            tolerance_kmh=tolerance_kmh,
        )

    def has_traffic_domain_anomaly(
        self,
        player_veh: Any,
        opp_veh: Any,
        profile: Optional[Any] = None,
        tolerance_kmh: float = 30.0,
    ) -> bool:
        """
        Vérifie la condition de filtrage pour les rôles trafic :
        Il faut qu'au moins l'un des deux (moi OU l'autre) soit hors domaine.
        """
        ref_prof = profile or self.get_reference_profile()
        if not ref_prof or getattr(ref_prof, "num_points", 0) < 2:
            return True

        player_in = self.is_vehicle_in_normal_domain(player_veh, profile=ref_prof, tolerance_kmh=tolerance_kmh)
        opp_in = self.is_vehicle_in_normal_domain(opp_veh, profile=ref_prof, tolerance_kmh=tolerance_kmh)

        return (not player_in) or (not opp_in)

    def get_track_length(self) -> float:
        """Retourne la longueur totale du circuit en mètres."""
        if self.scoring is not None:
            if hasattr(self.scoring, "lap_dist"):
                lap_dist = float(self.scoring.lap_dist)
                if lap_dist > 500.0:
                    return lap_dist
            elif isinstance(self.scoring, dict):
                lap_dist = float(self.scoring.get("mLapDist", self.scoring.get("lapDist", 0.0)))
                if lap_dist > 500.0:
                    return lap_dist
        return 5000.0  # Valeur par défaut de repli

    def get_player_vehicle(self) -> Optional[Any]:
        """Extrait le véhicule du joueur depuis la session scoring (VehicleScoring ou dict)."""
        if not self.scoring:
            return None

        if hasattr(self.scoring, "player_vehicle"):
            pv = self.scoring.player_vehicle
            if pv is not None:
                return pv

        vehicles = getattr(self.scoring, "vehicles", None)
        if vehicles is None and isinstance(self.scoring, dict):
            vehicles = self.scoring.get("mVehicles", [])

        if isinstance(vehicles, (list, tuple)):
            for v in vehicles:
                if get_vehicle_attr(v, "is_player") or get_vehicle_attr(v, "mIsPlayer"):
                    return v

            for v in vehicles:
                if get_vehicle_attr(v, "control") == 0:
                    return v

        return None

    def is_player_in_pits(self) -> bool:
        """Indique si le véhicule joueur est actuellement dans la pitlane (entre entrée et sortie)."""
        player = self.get_player_vehicle()
        if not player:
            return False
        return self.is_vehicle_in_pits(player)

    def is_player_in_garage(self) -> bool:
        """Indique si le joueur est dans son box / garage ou dans les menus."""
        # 1. Si la télémétrie physique active confirme que nous sommes en temps réel en piste,
        # on n'est PAS au garage (empêche tout faux positif lors de micro-transitions de paquets UDP)
        if self.telemetry is not None and getattr(self.telemetry, "in_realtime", False):
            player = self.get_player_vehicle()
            if player and bool(get_vehicle_attr(player, "in_garage_stall", False)):
                return True
            return False

        # 2. Vérification au niveau de la session de scoring globale
        if self.scoring is not None:
            if getattr(self.scoring, "game_phase", 5) == 0:
                return True
            if hasattr(self.scoring, "in_realtime") and not bool(self.scoring.in_realtime):
                return True
            if bool(get_vehicle_attr(self.scoring, "in_garage_stall", False)):
                return True

        # 3. Vérification sur le véhicule joueur
        player = self.get_player_vehicle()
        if player:
            return self.is_vehicle_in_garage(player)

        return False

    @classmethod
    def is_vehicle_in_pits(cls, veh: Any) -> bool:
        """
        Indique si un véhicule donné est dans la pitlane.
        Vérifie les drapeaux in_pits/mInPits et l'état pit_state/mPitState (2=entering, 3=stopped, 4=exiting).
        """
        if veh is None:
            return False
        if bool(get_vehicle_attr(veh, "in_pits", False)):
            return True
        pit_state = get_vehicle_attr(veh, "pit_state", 0)
        try:
            if int(pit_state) in (2, 3, 4):
                return True
        except (ValueError, TypeError):
            pass
        return False

    @classmethod
    def is_vehicle_in_garage(cls, veh: Any) -> bool:
        """Indique si un véhicule donné est dans son garage / box."""
        if veh is None:
            return False
        return bool(get_vehicle_attr(veh, "in_garage_stall", False))

    def get_track_opponents(self) -> List[Any]:
        """
        Retourne uniquement la liste des véhicules adverses actifs SUR LA PISTE (hors stands et garage).
        Garantit qu'aucun véhicule en pitlane ne perturbe les calculs de spotter ou de trafic en piste.
        """
        return self.get_opponent_vehicles(include_pits=False, include_garage=False)

    def get_pit_opponents(self) -> List[Any]:
        """
        Retourne la liste des véhicules adverses présents DANS LA PITLANE (hors garage).
        Permet un traitement distinct du trafic en voie des stands.
        """
        if not self.scoring:
            return []

        vehicles = getattr(self.scoring, "vehicles", None)
        if vehicles is None and isinstance(self.scoring, dict):
            vehicles = self.scoring.get("mVehicles", [])

        if not isinstance(vehicles, (list, tuple)):
            return []

        pit_opponents = []
        for v in vehicles:
            if get_vehicle_attr(v, "is_player") or get_vehicle_attr(v, "control") == 0:
                continue
            if self.is_vehicle_in_garage(v):
                continue
            if not self.is_vehicle_in_pits(v):
                continue
            finish_status = get_vehicle_attr(v, "finish_status", 0)
            if finish_status not in (0, "0"):
                continue
            pit_opponents.append(v)
        return pit_opponents

    def get_opponent_vehicles(
        self,
        include_pits: bool = False,
        include_garage: bool = False,
    ) -> List[Any]:
        """
        Retourne la liste des véhicules adverses actifs.
        Exclut le joueur, les véhicules au garage (sauf si include_garage=True),
        et les voitures aux stands (sauf si include_pits=True).
        """
        if not self.scoring:
            return []

        vehicles = getattr(self.scoring, "vehicles", None)
        if vehicles is None and isinstance(self.scoring, dict):
            vehicles = self.scoring.get("mVehicles", [])

        if not isinstance(vehicles, (list, tuple)):
            return []

        opponents = []
        for v in vehicles:
            if get_vehicle_attr(v, "is_player") or get_vehicle_attr(v, "control") == 0:
                continue
            if not include_garage and self.is_vehicle_in_garage(v):
                continue
            if not include_pits and self.is_vehicle_in_pits(v):
                continue
            finish_status = get_vehicle_attr(v, "finish_status", 0)
            if finish_status not in (0, "0"):
                continue
            opponents.append(v)
        return opponents

    @classmethod
    def extract_vehicle_speed_mps(cls, veh: Any) -> float:
        """Calcule la vitesse scalaire en m/s d'un véhicule (VehicleScoring ou dict)."""
        if veh is None:
            return 0.0
        if hasattr(veh, "speed_mps"):
            return float(veh.speed_mps)

        vel = get_vehicle_attr(veh, "local_vel")
        if isinstance(vel, dict):
            vx = float(vel.get("x", 0.0))
            vy = float(vel.get("y", 0.0))
            vz = float(vel.get("z", 0.0))
            return math.sqrt(vx * vx + vy * vy + vz * vz)
        elif hasattr(vel, "x") and hasattr(vel, "y") and hasattr(vel, "z"):
            return math.sqrt(float(vel.x)**2 + float(vel.y)**2 + float(vel.z)**2)
        elif isinstance(vel, (list, tuple)) and len(vel) >= 3:
            return math.sqrt(float(vel[0])**2 + float(vel[1])**2 + float(vel[2])**2)

        speed = get_vehicle_attr(veh, "speed")
        if speed is not None:
            return float(speed)
        return 0.0

    def get_player_speed_mps(self) -> float:
        """Retourne la vitesse instantanée du joueur en m/s."""
        # 1. Depuis la télémétrie haute fréquence si disponible
        if self.telemetry is not None:
            if hasattr(self.telemetry, "speed_mps"):
                return float(self.telemetry.speed_mps)
            if hasattr(self.telemetry, "longitudinal_ground_vel") and self.telemetry.longitudinal_ground_vel:
                speeds = [abs(v) for v in self.telemetry.longitudinal_ground_vel if isinstance(v, (int, float))]
                if speeds:
                    return max(speeds)

        # 2. Depuis le véhicule joueur dans le scoring
        player_veh = self.get_player_vehicle()
        if player_veh is not None:
            return self.extract_vehicle_speed_mps(player_veh)

        return 0.0

    def compute_distance_behind(
        self,
        player_veh: Any,
        opp_veh: Any,
        track_length: Optional[float] = None,
    ) -> float:
        """
        Calcule la distance relative le long de la spline du circuit.
        - Valeur > 0 : L'adversaire est DERRIÈRE le joueur (en mètres).
        - Valeur < 0 : L'adversaire est DEVANT le joueur (en mètres).
        Gère le rebouclage de la ligne de départ/arrivée (wraparound).
        """
        l_track = track_length or self.get_track_length()
        p_dist = float(get_vehicle_attr(player_veh, "lap_dist", 0.0)) % l_track
        o_dist = float(get_vehicle_attr(opp_veh, "lap_dist", 0.0)) % l_track

        delta = (p_dist - o_dist) % l_track
        if delta < l_track / 2.0:
            return delta  # Adversaire derrière
        else:
            return delta - l_track  # Adversaire devant (valeur négative)

    @classmethod
    def compute_euclidean_distance(cls, veh_a: Any, veh_b: Any) -> float:
        """Calcule la distance euclidienne 3D entre deux véhicules si la position mPos/pos est disponible."""
        def _get_xyz(v):
            if v is None:
                return None
            p = get_vehicle_attr(v, "pos")
            if p is not None:
                if hasattr(p, "x") and hasattr(p, "y") and hasattr(p, "z"):
                    x, y, z = float(p.x), float(p.y), float(p.z)
                    if not (x == 0.0 and y == 0.0 and z == 0.0):
                        return x, y, z
                elif isinstance(p, dict):
                    x, y, z = float(p.get("x", 0.0)), float(p.get("y", 0.0)), float(p.get("z", 0.0))
                    if not (x == 0.0 and y == 0.0 and z == 0.0):
                        return x, y, z
                elif isinstance(p, (list, tuple)) and len(p) >= 3:
                    x, y, z = float(p[0]), float(p[1]), float(p[2])
                    if not (x == 0.0 and y == 0.0 and z == 0.0):
                        return x, y, z
            return None

        pos_a = _get_xyz(veh_a)
        pos_b = _get_xyz(veh_b)
        if pos_a is None or pos_b is None:
            return float("inf")

        xa, ya, za = pos_a
        xb, yb, zb = pos_b
        return math.sqrt((xa - xb)**2 + (ya - yb)**2 + (za - zb)**2)

