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
    reference_profile: Optional[Any] = None

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
        if self.scoring:
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
        if self.scoring:
            name = str(self.scoring.get("mTrackName", self.scoring.get("trackName", "")))
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
        scoring_track = ""
        if self.scoring:
            scoring_track = str(self.scoring.get("mTrackName", self.scoring.get("trackName", "")))

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
                prof = delta_eng.current_profile or delta_eng.all_time_best_profile
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
        
        Si aucun tour de référence n'est chargé, retourne True (repli tolérant).
        Si |Vitesse - VitesseRef| <= tolerance_kmh -> True (dans le domaine normal).
        Sinon -> False (hors domaine / anomalie).
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
        veh: Dict[str, Any],
        profile: Optional[Any] = None,
        tolerance_kmh: float = 30.0,
    ) -> bool:
        """
        Détermine si un véhicule roule dans son domaine de vitesse 'normal'
        selon sa position sur la piste.
        """
        if not isinstance(veh, dict):
            return True
        track_len = self.get_track_length()
        lap_dist = float(veh.get("mLapDist", veh.get("lapDist", 0.0))) % track_len
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
        lap_dist = float(player_veh.get("mLapDist", player_veh.get("lapDist", 0.0))) % track_len
        player_speed = self.get_player_speed_mps()
        return self.is_speed_in_normal_domain(
            speed_mps=player_speed,
            track_dist=lap_dist,
            profile=profile,
            tolerance_kmh=tolerance_kmh,
        )

    def has_traffic_domain_anomaly(
        self,
        player_veh: Dict[str, Any],
        opp_veh: Dict[str, Any],
        profile: Optional[Any] = None,
        tolerance_kmh: float = 30.0,
    ) -> bool:
        """
        Vérifie la condition de filtrage pour les rôles trafic :
        Il faut qu'au moins l'un des deux (moi OU l'autre) soit hors domaine.
        
        - Si aucun tour de référence n'est disponible -> True (pas de filtrage).
        - Si le joueur OU l'adversaire est hors domaine -> True (alerte autorisée).
        - Si les DEUX sont dans le domaine normal -> False (alerte filtrée / ignorée).
        """
        ref_prof = profile or self.get_reference_profile()
        if not ref_prof or getattr(ref_prof, "num_points", 0) < 2:
            return True

        player_in = self.is_vehicle_in_normal_domain(player_veh, profile=ref_prof, tolerance_kmh=tolerance_kmh)
        opp_in = self.is_vehicle_in_normal_domain(opp_veh, profile=ref_prof, tolerance_kmh=tolerance_kmh)

        return (not player_in) or (not opp_in)

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

    def is_player_in_pits(self) -> bool:
        """Indique si le véhicule joueur est actuellement dans la pitlane (entre entrée et sortie)."""
        player = self.get_player_vehicle()
        if not player:
            return False
        return self.is_vehicle_in_pits(player)

    def is_player_in_garage(self) -> bool:
        """Indique si le joueur est dans son box / garage."""
        player = self.get_player_vehicle()
        if not player:
            return False
        return self.is_vehicle_in_garage(player)

    @classmethod
    def is_vehicle_in_pits(cls, veh: Dict[str, Any]) -> bool:
        """
        Indique si un véhicule donné est dans la pitlane.
        Vérifie les drapeaux mInPits et l'état mPitState (2=entering, 3=stopped, 4=exiting).
        """
        if not isinstance(veh, dict):
            return False
        if veh.get("mInPits") or veh.get("inPits"):
            return True
        pit_state = veh.get("mPitState", veh.get("pitState", 0))
        try:
            if int(pit_state) in (2, 3, 4):
                return True
        except (ValueError, TypeError):
            pass
        return False

    @classmethod
    def is_vehicle_in_garage(cls, veh: Dict[str, Any]) -> bool:
        """Indique si un véhicule donné est dans son garage / box."""
        if not isinstance(veh, dict):
            return False
        return bool(veh.get("mInGarageStall") or veh.get("inGarageStall"))

    def get_track_opponents(self) -> List[Dict[str, Any]]:
        """
        Retourne uniquement la liste des véhicules adverses actifs SUR LA PISTE (hors stands et garage).
        Garantit qu'aucun véhicule en pitlane ne perturbe les calculs de spotter ou de trafic en piste.
        """
        return self.get_opponent_vehicles(include_pits=False, include_garage=False)

    def get_pit_opponents(self) -> List[Dict[str, Any]]:
        """
        Retourne la liste des véhicules adverses présents DANS LA PITLANE (hors garage).
        Permet un traitement distinct du trafic en voie des stands.
        """
        if not self.scoring:
            return []
        vehicles = self.scoring.get("mVehicles", [])
        if not isinstance(vehicles, list):
            return []

        pit_opponents = []
        for v in vehicles:
            if not isinstance(v, dict):
                continue
            if v.get("mIsPlayer") or v.get("isPlayer") or v.get("mControl") == 0:
                continue
            if self.is_vehicle_in_garage(v):
                continue
            if not self.is_vehicle_in_pits(v):
                continue
            if v.get("mFinishStatus", 0) not in (0, "0"):
                continue
            pit_opponents.append(v)
        return pit_opponents

    def get_opponent_vehicles(
        self,
        include_pits: bool = False,
        include_garage: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Retourne la liste des véhicules adverses actifs.
        Exclut le joueur, les véhicules au garage (sauf si include_garage=True),
        et les voitures aux stands (sauf si include_pits=True).
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
            if not include_garage and self.is_vehicle_in_garage(v):
                continue
            if not include_pits and self.is_vehicle_in_pits(v):
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
