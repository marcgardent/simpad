"""
SimPad Race Engineer — Rôle Fight Spotter (CrewChief V4 Cartesian FSM).
Architecture POO et principes SOLID :
- SRP : Découpage en modules spécialisés (Géométrie 2D, Filtrage bruit/vitesse, Détection overlap, FSM temporelle, Stratégies de vocabulaire).
- OCP : Stratégies de phrasé interchangeables (Routier vs Ovale) et paramètres déclaratifs extensibles.
- LSP : Implémentation conforme et substituable de BaseRole.
- ISP : Protocoles clairs et ciblés pour la géométrie, la vitesse et la FSM.
- DIP : Découplage strict entre la logique spatiale et le runtime audio/télémétrie.
"""

import time
import math
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple, Protocol, Union

from src.engineer.base import BaseRole, EngineerMessage, RoleStatus
from src.engineer.context import EngineerContext, get_vehicle_attr
from src.engineer.registry import RoleRegistry
from src.engineer.params import RoleParam, FloatRangeParam, BoolParam

logger = logging.getLogger(__name__)


# =============================================================================
# 1. ÉNUMÉRATIONS ET STRUCTURES DE DONNÉES TYPÉES
# =============================================================================

class SpotterSide(str, Enum):
    """Côté relatif d'un adversaire par rapport au véhicule joueur."""
    NONE = "none"
    LEFT = "left"
    RIGHT = "right"


class SpotterMessageType(str, Enum):
    """Types de messages vocaux émis par le Spotter."""
    NONE = "none"
    CAR_LEFT = "car_left"
    CAR_RIGHT = "car_right"
    CLEAR_LEFT = "clear_left"
    CLEAR_RIGHT = "clear_right"
    CLEAR_ALL_ROUND = "clear_all_round"
    THREE_WIDE_MIDDLE = "three_wide_middle"
    THREE_WIDE_LEFT = "three_wide_left"
    THREE_WIDE_RIGHT = "three_wide_right"
    STILL_THERE = "still_there"


class FightSpotterState(str, Enum):
    """État global de la situation spatiale de combat autour du véhicule joueur."""
    IDLE = "IDLE"
    CLEAR = "CLEAR"
    OVERLAP_LEFT = "OVERLAP_LEFT"
    OVERLAP_RIGHT = "OVERLAP_RIGHT"
    THREE_WIDE_MIDDLE = "THREE_WIDE_MIDDLE"
    THREE_WIDE_LEFT = "THREE_WIDE_LEFT"
    THREE_WIDE_RIGHT = "THREE_WIDE_RIGHT"


@dataclass
class OpponentTrackingData:
    """Mémoire de suivi temporel et cinématique pour un adversaire."""
    opponent_id: int
    pos_x: float
    pos_z: float
    vel_x: float = 0.0
    vel_z: float = 0.0
    last_update_time: float = 0.0


@dataclass
class AlignedOpponent:
    """Position et classification relative d'un adversaire dans le repère joueur."""
    opponent_id: int
    side: SpotterSide
    lateral_separation_m: float
    longitudinal_dist_m: float
    is_speed_valid: bool


# =============================================================================
# 2. STRATÉGIES DE VOCABULAIRE (PATTERN STRATEGY - OCP)
# =============================================================================

class ISpotterPhrasingStrategy(Protocol):
    """Protocole pour la résolution des clés de phrases audio du Spotter."""
    def resolve_phrase(self, message_type: SpotterMessageType) -> str:
        """Retourne la clé de phrase audio correspondant au type de message."""
        ...


class RoadSpotterPhrasingStrategy:
    """Stratégie de phrasé pour circuits routiers (Car Left, Car Right, Clear, 3-Wide)."""
    _PHRASE_MAP = {
        SpotterMessageType.CAR_LEFT: "car_left",
        SpotterMessageType.CAR_RIGHT: "car_right",
        SpotterMessageType.CLEAR_LEFT: "clear_left",
        SpotterMessageType.CLEAR_RIGHT: "clear_right",
        SpotterMessageType.CLEAR_ALL_ROUND: "clear_all_round",
        SpotterMessageType.THREE_WIDE_MIDDLE: "three_wide",
        SpotterMessageType.THREE_WIDE_LEFT: "three_wide_left",
        SpotterMessageType.THREE_WIDE_RIGHT: "three_wide_right",
        SpotterMessageType.STILL_THERE: "still_there",
    }

    def resolve_phrase(self, message_type: SpotterMessageType) -> str:
        return self._PHRASE_MAP.get(message_type, "")


class OvalSpotterPhrasingStrategy:
    """Stratégie de phrasé pour circuits ovales (Inside, Outside, Clear Inside/Outside)."""
    _PHRASE_MAP = {
        SpotterMessageType.CAR_LEFT: "car_inside",
        SpotterMessageType.CAR_RIGHT: "car_outside",
        SpotterMessageType.CLEAR_LEFT: "clear_inside",
        SpotterMessageType.CLEAR_RIGHT: "clear_outside",
        SpotterMessageType.CLEAR_ALL_ROUND: "clear_all_round",
        SpotterMessageType.THREE_WIDE_MIDDLE: "three_wide",
        SpotterMessageType.THREE_WIDE_LEFT: "three_wide_inside",
        SpotterMessageType.THREE_WIDE_RIGHT: "three_wide_outside",
        SpotterMessageType.STILL_THERE: "still_there",
    }

    def resolve_phrase(self, message_type: SpotterMessageType) -> str:
        return self._PHRASE_MAP.get(message_type, "")


# =============================================================================
# 3. MOTEUR GÉOMÉTRIQUE CARTÉSIEN 2D (SRP)
# =============================================================================

class CartesianGeometry2D:
    """
    Gère les projections géométriques 2D du repère mondial vers le repère local de la voiture.
    Repère joueur : Origine (0, 0), +Z vers l'arrière / -Z vers l'avant, +X à gauche / -X à droite.
    """

    @staticmethod
    def get_aligned_xz_coordinates(
        player_rotation_rad: float,
        player_x: float,
        player_z: float,
        opponent_x: float,
        opponent_z: float,
    ) -> Tuple[float, float]:
        """
        Effectue le changement de repère par rotation trigonométrique 2D.
        """
        raw_x = opponent_x - player_x
        raw_z = opponent_z - player_z

        cos_rot = math.cos(player_rotation_rad)
        sin_rot = math.sin(player_rotation_rad)

        # X_aligné : > 0 à gauche, < 0 à droite
        aligned_x = float((cos_rot * raw_x) + (sin_rot * raw_z))
        # Z_aligné : > 0 derrière, < 0 devant
        aligned_z = float((cos_rot * raw_z) - (sin_rot * raw_x))

        return aligned_x, aligned_z

    @staticmethod
    def compute_yaw_from_velocity(vel_x: float, vel_z: float) -> float:
        """Calcule l'angle de lacet (yaw) à partir du vecteur vitesse mondiale."""
        if abs(vel_x) < 0.001 and abs(vel_z) < 0.001:
            return 0.0
        yaw = math.atan2(vel_x, vel_z)
        if yaw < 0.0:
            yaw += 2.0 * math.pi
        return yaw

    @staticmethod
    def compute_yaw_from_orientation(m_ori: Any) -> Optional[float]:
        """Extrait l'angle de lacet depuis une matrice d'orientation rFactor2/LMU si disponible."""
        if m_ori is None:
            return None
        try:
            # Format mOri rF2 : mOri[RowZ].x, mOri[RowZ].z
            if isinstance(m_ori, (list, tuple)) and len(m_ori) >= 3:
                row_z = m_ori[2]
                if isinstance(row_z, dict):
                    x = float(row_z.get("x", 0.0))
                    z = float(row_z.get("z", 0.0))
                    yaw = math.atan2(x, z)
                    return yaw if yaw >= 0 else yaw + 2.0 * math.pi
                elif hasattr(row_z, "x") and hasattr(row_z, "z"):
                    yaw = math.atan2(float(row_z.x), float(row_z.z))
                    return yaw if yaw >= 0 else yaw + 2.0 * math.pi
        except Exception:
            pass
        return None


# =============================================================================
# 4. FILTRE DE VITESSE ET BRUIT CINÉMATIQUE (SRP)
# =============================================================================

class OpponentSpeedFilter:
    """
    Suit la cinématique des adversaires par différences finies et filtre les vitesses anormales
    (ex: voitures en toupie, à contresens ou téléportées).
    """

    def __init__(
        self,
        calculate_speeds_interval_sec: float = 0.2,
        max_closing_speed_mps: float = 25.0,  # 90 km/h
    ):
        self.calculate_speeds_interval_sec = calculate_speeds_interval_sec
        self.max_closing_speed_mps = max_closing_speed_mps
        self._cache: Dict[int, OpponentTrackingData] = {}

    def update_and_validate(
        self,
        opponent_id: int,
        opp_x: float,
        opp_z: float,
        player_vel_x: float,
        player_vel_z: float,
        now: float,
        opp_vel_x: Optional[float] = None,
        opp_vel_z: Optional[float] = None,
    ) -> bool:
        """
        Met à jour la vitesse de l'adversaire et valide si la vitesse relative de rapprochement
        est dans la plage réaliste d'une bataille en piste.
        """
        tracking = self._cache.get(opponent_id)
        if tracking is None:
            vx = opp_vel_x if opp_vel_x is not None else player_vel_x
            vz = opp_vel_z if opp_vel_z is not None else player_vel_z
            self._cache[opponent_id] = OpponentTrackingData(
                opponent_id=opponent_id,
                pos_x=opp_x,
                pos_z=opp_z,
                vel_x=vx,
                vel_z=vz,
                last_update_time=now,
            )
            return True

        if opp_vel_x is not None and opp_vel_z is not None:
            tracking.vel_x = opp_vel_x
            tracking.vel_z = opp_vel_z
            tracking.pos_x = opp_x
            tracking.pos_z = opp_z
            tracking.last_update_time = now
        else:
            time_diff = now - tracking.last_update_time
            if time_diff >= self.calculate_speeds_interval_sec and time_diff > 0.0:
                tracking.vel_x = (opp_x - tracking.pos_x) / time_diff
                tracking.vel_z = (opp_z - tracking.pos_z) / time_diff
                tracking.pos_x = opp_x
                tracking.pos_z = opp_z
                tracking.last_update_time = now

        # Vérification du différentiel de vitesse (closing speed)
        delta_vx = abs(player_vel_x - tracking.vel_x)
        delta_vz = abs(player_vel_z - tracking.vel_z)

        return delta_vx <= self.max_closing_speed_mps and delta_vz <= self.max_closing_speed_mps

    def purge_inactive(self, active_ids: set) -> None:
        """Supprime du cache les véhicules qui ne sont plus dans la zone d'intérêt."""
        stale_keys = [k for k in self._cache.keys() if k not in active_ids]
        for k in stale_keys:
            del self._cache[k]

    def clear(self) -> None:
        """Réinitialise tout le cache cinématique."""
        self._cache.clear()


# =============================================================================
# 5. ÉVALUATEUR D'OVERLAP ET GESTION 3-WIDE (SRP)
# =============================================================================

class CartesianOverlapEvaluator:
    """
    Évalue la présence d'overlap avec hystérésis de dégagement (Clear Gap)
    et analyse la dispersion latérale pour distinguer la file indienne du 3-Wide.
    """

    def __init__(
        self,
        car_length_m: float = 4.2,
        car_width_m: float = 1.9,
        gap_needed_for_clear_m: float = 1.5,
        car_behind_extra_length_m: float = 0.4,
        track_zone_to_consider_m: float = 20.0,
    ):
        self.car_length_m = car_length_m
        self.car_width_m = car_width_m
        self.gap_needed_for_clear_m = gap_needed_for_clear_m
        self.long_car_length_m = car_length_m + gap_needed_for_clear_m
        self.car_behind_extra_length_m = car_behind_extra_length_m
        self.track_zone_to_consider_m = track_zone_to_consider_m

    def set_dimensions(self, length_m: float, width_m: float, clear_gap_m: Optional[float] = None) -> None:
        """Met à jour dynamiquement les dimensions du véhicule."""
        self.car_length_m = float(length_m)
        self.car_width_m = float(width_m)
        if clear_gap_m is not None:
            self.gap_needed_for_clear_m = float(clear_gap_m)
        self.long_car_length_m = self.car_length_m + self.gap_needed_for_clear_m

    def is_in_consideration_zone(self, aligned_x: float, aligned_z: float) -> bool:
        """Vérifie si le véhicule adverse est dans le périmètre d'analyse immédiat (20m)."""
        return (abs(aligned_x) <= self.track_zone_to_consider_m and
                abs(aligned_z) <= self.track_zone_to_consider_m)

    def evaluate_opponent_overlap(
        self,
        aligned_x: float,
        aligned_z: float,
        had_overlap_on_side: bool,
        is_speed_valid: bool,
    ) -> Tuple[SpotterSide, float]:
        """
        Détermine si l'adversaire est en situation d'overlap (gauche ou droite)
        en appliquant la règle d'hystérésis (longCarLength vs carLength).
        """
        if not self.is_in_consideration_zone(aligned_x, aligned_z):
            return SpotterSide.NONE, -1.0

        # Opponent à DROITE (X < 0)
        if aligned_x < 0:
            lateral_sep = abs(aligned_x)
            if had_overlap_on_side:
                # Si déjà en overlap, maintien jusqu'à long_car_length
                if abs(aligned_z) < self.long_car_length_m:
                    return SpotterSide.RIGHT, lateral_sep
            else:
                # Nouvel overlap : vérification stricte longueur + largeur + vitesse
                is_longitudinal_overlap = (
                    (aligned_z < 0 and abs(aligned_z) < self.car_length_m) or
                    (aligned_z >= 0 and aligned_z < (self.car_length_m + self.car_behind_extra_length_m))
                )
                if is_longitudinal_overlap and lateral_sep >= (self.car_width_m * 0.4) and is_speed_valid:
                    return SpotterSide.RIGHT, lateral_sep

        # Opponent à GAUCHE (X > 0)
        elif aligned_x > 0:
            lateral_sep = aligned_x
            if had_overlap_on_side:
                if abs(aligned_z) < self.long_car_length_m:
                    return SpotterSide.LEFT, lateral_sep
            else:
                is_longitudinal_overlap = (
                    (aligned_z < 0 and abs(aligned_z) < self.car_length_m) or
                    (aligned_z >= 0 and aligned_z < (self.car_length_m + self.car_behind_extra_length_m))
                )
                if is_longitudinal_overlap and lateral_sep >= (self.car_width_m * 0.4) and is_speed_valid:
                    return SpotterSide.LEFT, lateral_sep

        return SpotterSide.NONE, -1.0

    def analyze_multi_car_distribution(
        self,
        left_separations: List[float],
        right_separations: List[float],
    ) -> Tuple[int, int]:
        """
        Calcule le nombre effectif de voitures de front à gauche et à droite.
        Filtre les véhicules en file indienne (line-astern) si delta séparation < car_width.
        """
        cars_left = len(left_separations)
        cars_right = len(right_separations)

        if cars_left > 1 and cars_right == 0:
            delta_left = max(left_separations) - min(left_separations)
            if delta_left < self.car_width_m:
                cars_left = 1  # File indienne

        if cars_right > 1 and cars_left == 0:
            delta_right = max(right_separations) - min(right_separations)
            if delta_right < self.car_width_m:
                cars_right = 1  # File indienne

        return cars_left, cars_right


# =============================================================================
# 6. MACHINE À ÉTATS TEMPORELLE ET LOGIQUE ANTI-CHATTER (SRP)
# =============================================================================

class SpotterStateMachine:
    """
    Machine à états finis temporelle inspirée de CrewChiefV4.
    Gère les délais de confirmation (Clear Delay), les répétitions ("Still there"),
    la prévention du rebond (Anti-Chatter) et le maintien du canal radio.
    """

    def __init__(
        self,
        clear_message_delay_sec: float = 0.35,
        oval_clear_message_delay_sec: float = 0.20,
        repeat_hold_freq_sec: float = 3.0,
        bouncing_wait_sec: float = 1.5,
        on_single_to_3wide_delay_sec: float = 0.5,
        enable_three_wide: bool = True,
        time_to_wait_before_closing_channel_sec: float = 5.0,
    ):
        self.clear_message_delay_sec = clear_message_delay_sec
        self.oval_clear_message_delay_sec = oval_clear_message_delay_sec
        self.repeat_hold_freq_sec = repeat_hold_freq_sec
        self.bouncing_wait_sec = bouncing_wait_sec
        self.on_single_to_3wide_delay_sec = on_single_to_3wide_delay_sec
        self.enable_three_wide = enable_three_wide
        self.time_to_wait_before_closing_channel_sec = time_to_wait_before_closing_channel_sec

        # États internes
        self.cars_on_left_prev: int = 0
        self.cars_on_right_prev: int = 0
        self.reported_single_overlap_left: bool = False
        self.reported_single_overlap_right: bool = False
        self.reported_double_overlap_left: bool = False
        self.reported_double_overlap_right: bool = False
        self.was_in_middle: bool = False

        self.next_message_type: SpotterMessageType = SpotterMessageType.NONE
        self.next_message_due_time: float = 0.0

        # Gestion du canal radio ouvert
        self.channel_open: bool = False
        self.time_when_channel_should_close: float = float("inf")

    def reset(self) -> None:
        """Réinitialise tous les états de la machine."""
        self.cars_on_left_prev = 0
        self.cars_on_right_prev = 0
        self.reported_single_overlap_left = False
        self.reported_single_overlap_right = False
        self.reported_double_overlap_left = False
        self.reported_double_overlap_right = False
        self.was_in_middle = False
        self.next_message_type = SpotterMessageType.NONE
        self.next_message_due_time = 0.0
        self.channel_open = False
        self.time_when_channel_should_close = float("inf")

    def evaluate_next_message(
        self,
        cars_on_left: int,
        cars_on_right: int,
        now: float,
        use_oval_logic: bool = False,
    ) -> None:
        """
        Détermine le prochain message à planifier en fonction de l'évolution des overlaps.
        """
        clear_delay = self.oval_clear_message_delay_sec if use_oval_logic else self.clear_message_delay_sec

        # 1. Clear All Round (dégagé des deux côtés)
        if cars_on_left == 0 and cars_on_right == 0 and (self.cars_on_left_prev > 0 and self.cars_on_right_prev > 0):
            self.next_message_type = SpotterMessageType.CLEAR_ALL_ROUND
            self.next_message_due_time = now + clear_delay

        # 2. Clear Left
        elif cars_on_left == 0 and self.cars_on_left_prev > 0 and (
            (cars_on_right == 0 and self.cars_on_right_prev == 0) or
            (cars_on_right > 0 and self.cars_on_right_prev > 0)
        ):
            self.next_message_type = SpotterMessageType.CLEAR_LEFT
            self.next_message_due_time = now + clear_delay

        # 3. Clear Right
        elif cars_on_right == 0 and self.cars_on_right_prev > 0 and (
            (cars_on_left == 0 and self.cars_on_left_prev == 0) or
            (cars_on_left > 0 and self.cars_on_left_prev > 0)
        ):
            self.next_message_type = SpotterMessageType.CLEAR_RIGHT
            self.next_message_due_time = now + clear_delay

        # 4. Three Wide In the Middle (voitures des deux côtés)
        elif cars_on_left > 0 and cars_on_right > 0 and (self.cars_on_left_prev == 0 or self.cars_on_right_prev == 0):
            has_pending_clear = (self.reported_single_overlap_left or self.reported_double_overlap_left) and \
                                (self.reported_single_overlap_right or self.reported_double_overlap_right)
            self.next_message_due_time = now + (self.bouncing_wait_sec if has_pending_clear else 0.0)
            self.next_message_type = SpotterMessageType.THREE_WIDE_MIDDLE

        # 5. Nouvel Overlap à Gauche
        elif cars_on_left > 0 and cars_on_right == 0 and self.cars_on_left_prev == 0 and self.cars_on_right_prev == 0:
            has_pending_clear = self.reported_single_overlap_left or self.reported_double_overlap_left
            self.next_message_due_time = now + (self.bouncing_wait_sec if has_pending_clear else 0.0)
            if self.enable_three_wide and cars_on_left > 1:
                self.next_message_type = SpotterMessageType.THREE_WIDE_RIGHT
            else:
                self.next_message_type = SpotterMessageType.CAR_LEFT

        # 6. Nouvel Overlap à Droite
        elif cars_on_left == 0 and cars_on_right > 0 and self.cars_on_left_prev == 0 and self.cars_on_right_prev == 0:
            has_pending_clear = self.reported_single_overlap_right or self.reported_double_overlap_right
            self.next_message_due_time = now + (self.bouncing_wait_sec if has_pending_clear else 0.0)
            if self.enable_three_wide and cars_on_right > 1:
                self.next_message_type = SpotterMessageType.THREE_WIDE_LEFT
            else:
                self.next_message_type = SpotterMessageType.CAR_RIGHT

        # 7. Escalade vers 3-Wide sur un seul côté
        elif self.enable_three_wide and cars_on_left > 1 and cars_on_right == 0 and self.cars_on_left_prev == 1:
            self.next_message_due_time = now + (self.on_single_to_3wide_delay_sec if self.reported_single_overlap_left else 0.0)
            self.next_message_type = SpotterMessageType.THREE_WIDE_RIGHT

        elif self.enable_three_wide and cars_on_left == 0 and cars_on_right > 1 and self.cars_on_right_prev == 1:
            self.next_message_due_time = now + (self.on_single_to_3wide_delay_sec if self.reported_single_overlap_right else 0.0)
            self.next_message_type = SpotterMessageType.THREE_WIDE_LEFT

        # 8. Désescalade 3-Wide -> simple overlap
        elif self.enable_three_wide and cars_on_left == 1 and cars_on_right == 0 and self.cars_on_left_prev > 1:
            self.next_message_type = SpotterMessageType.CAR_LEFT
            self.next_message_due_time = now

        elif self.enable_three_wide and cars_on_left == 0 and cars_on_right == 1 and self.cars_on_right_prev > 1:
            self.next_message_type = SpotterMessageType.CAR_RIGHT
            self.next_message_due_time = now

    def is_message_valid(self, msg_type: SpotterMessageType, cars_on_left: int, cars_on_right: int) -> bool:
        """Vérifie la validité contextuelle du message avant émission."""
        if msg_type == SpotterMessageType.CAR_LEFT and cars_on_left == 0:
            return False
        if msg_type == SpotterMessageType.CAR_RIGHT and cars_on_right == 0:
            return False
        if msg_type == SpotterMessageType.THREE_WIDE_MIDDLE and (cars_on_left == 0 or cars_on_right == 0):
            return False
        if msg_type == SpotterMessageType.THREE_WIDE_LEFT and cars_on_right < 2:
            return False
        if msg_type == SpotterMessageType.THREE_WIDE_RIGHT and cars_on_left < 2:
            return False
        if msg_type == SpotterMessageType.STILL_THERE and cars_on_left == 0 and cars_on_right == 0:
            return False
        return True

    def process_playback_tick(
        self,
        cars_on_left: int,
        cars_on_right: int,
        now: float,
    ) -> Optional[Tuple[SpotterMessageType, bool]]:
        """
        Consomme le message prêt s'il est éligible et met à jour les indicateurs d'état.
        Retourne (message_type, keep_channel_open) ou None.
        """
        if self.next_message_type == SpotterMessageType.NONE or now < self.next_message_due_time:
            return None

        if not self.is_message_valid(self.next_message_type, cars_on_left, cars_on_right):
            self.next_message_type = SpotterMessageType.NONE
            return None

        msg_to_play = self.next_message_type

        # Machine de transition des états après émission
        if msg_to_play == SpotterMessageType.THREE_WIDE_MIDDLE:
            self.reported_single_overlap_left = True
            self.reported_single_overlap_right = True
            self.reported_double_overlap_left = False
            self.reported_double_overlap_right = False
            self.was_in_middle = True
            self.channel_open = True
            self.next_message_type = SpotterMessageType.STILL_THERE
            self.next_message_due_time = now + self.repeat_hold_freq_sec
            return msg_to_play, True

        elif msg_to_play == SpotterMessageType.THREE_WIDE_LEFT:
            self.reported_double_overlap_right = True
            self.reported_single_overlap_right = False
            self.channel_open = True
            self.next_message_type = SpotterMessageType.STILL_THERE
            self.next_message_due_time = now + self.repeat_hold_freq_sec
            return msg_to_play, True

        elif msg_to_play == SpotterMessageType.THREE_WIDE_RIGHT:
            self.reported_double_overlap_left = True
            self.reported_single_overlap_left = False
            self.channel_open = True
            self.next_message_type = SpotterMessageType.STILL_THERE
            self.next_message_due_time = now + self.repeat_hold_freq_sec
            return msg_to_play, True

        elif msg_to_play == SpotterMessageType.CAR_LEFT:
            self.reported_single_overlap_left = True
            self.reported_double_overlap_left = False
            self.channel_open = True
            self.next_message_type = SpotterMessageType.STILL_THERE
            self.next_message_due_time = now + self.repeat_hold_freq_sec
            return msg_to_play, True

        elif msg_to_play == SpotterMessageType.CAR_RIGHT:
            self.reported_single_overlap_right = True
            self.reported_double_overlap_right = False
            self.channel_open = True
            self.next_message_type = SpotterMessageType.STILL_THERE
            self.next_message_due_time = now + self.repeat_hold_freq_sec
            return msg_to_play, True

        elif msg_to_play == SpotterMessageType.CLEAR_ALL_ROUND:
            had_overlap = (self.reported_single_overlap_left or self.reported_single_overlap_right or
                           self.reported_double_overlap_left or self.reported_double_overlap_right)
            self.reported_single_overlap_left = False
            self.reported_single_overlap_right = False
            self.reported_double_overlap_left = False
            self.reported_double_overlap_right = False
            self.was_in_middle = False
            self.channel_open = False
            self.next_message_type = SpotterMessageType.NONE
            return (msg_to_play, False) if had_overlap else None

        elif msg_to_play == SpotterMessageType.CLEAR_LEFT:
            had_overlap = self.reported_single_overlap_left or self.reported_double_overlap_left
            self.reported_single_overlap_left = False
            self.reported_double_overlap_left = False

            if cars_on_right == 0 and self.was_in_middle:
                self.was_in_middle = False
                self.channel_open = False
                self.next_message_type = SpotterMessageType.NONE
                return SpotterMessageType.CLEAR_ALL_ROUND, False
            elif self.was_in_middle:
                self.next_message_type = SpotterMessageType.CAR_RIGHT
                self.next_message_due_time = now + self.repeat_hold_freq_sec
                return msg_to_play, True
            else:
                self.channel_open = (cars_on_right > 0)
                self.next_message_type = SpotterMessageType.NONE
                return (msg_to_play, False) if had_overlap else None

        elif msg_to_play == SpotterMessageType.CLEAR_RIGHT:
            had_overlap = self.reported_single_overlap_right or self.reported_double_overlap_right
            self.reported_single_overlap_right = False
            self.reported_double_overlap_right = False

            if cars_on_left == 0 and self.was_in_middle:
                self.was_in_middle = False
                self.channel_open = False
                self.next_message_type = SpotterMessageType.NONE
                return SpotterMessageType.CLEAR_ALL_ROUND, False
            elif self.was_in_middle:
                self.next_message_type = SpotterMessageType.CAR_LEFT
                self.next_message_due_time = now + self.repeat_hold_freq_sec
                return msg_to_play, True
            else:
                self.channel_open = (cars_on_left > 0)
                self.next_message_type = SpotterMessageType.NONE
                return (msg_to_play, False) if had_overlap else None

        elif msg_to_play == SpotterMessageType.STILL_THERE:
            has_active_overlap = (self.reported_single_overlap_left or self.reported_single_overlap_right or
                                  self.reported_double_overlap_left or self.reported_double_overlap_right)
            if has_active_overlap:
                self.next_message_type = SpotterMessageType.STILL_THERE
                self.next_message_due_time = now + self.repeat_hold_freq_sec
                return msg_to_play, True
            else:
                self.next_message_type = SpotterMessageType.NONE
                return None

        return None


# =============================================================================
# 7. RÔLE PRINCIPAL RACE ENGINEER : FIGHT SPOTTER (SOLID - LSP / DIP)
# =============================================================================

@RoleRegistry.register(
    role_id="fight_spotter",
    name="Fight Spotter (CrewChief Cartesian FSM)",
    description="Spotter de combat de proximité haute fidélité basé sur CrewChief V4 : transformation 2D locale, filtrage cinématique, hystérésis d'overlap, détection 3-wide et machine à états anti-chatter.",
    default_priority=110,
)
class FightSpotterRole(BaseRole):
    """
    Rôle Fight Spotter implémentant l'architecture complète de combat rapproché de CrewChiefV4.
    """

    def __init__(
        self,
        role_id: str = "fight_spotter",
        name: str = "Fight Spotter (CrewChief Cartesian FSM)",
        description: str = "",
        priority: int = 110,
        enabled: bool = True,
        audio_engine: Optional[Any] = None,
        car_length_m: float = 4.2,
        car_width_m: float = 1.9,
        gap_needed_for_clear_m: float = 1.5,
        clear_message_delay_sec: float = 0.35,
        repeat_hold_freq_sec: float = 3.0,
        min_speed_kmh: float = 35.0,
        max_closing_speed_kmh: float = 90.0,
        use_oval_logic: bool = False,
        enable_three_wide: bool = True,
    ):
        super().__init__(
            role_id=role_id,
            name=name,
            description=description,
            priority=priority,
            enabled=enabled,
            audio_engine=audio_engine,
        )

        # Paramètres configurables
        self.car_length_m = float(car_length_m)
        self.car_width_m = float(car_width_m)
        self.gap_needed_for_clear_m = float(gap_needed_for_clear_m)
        self.clear_message_delay_sec = float(clear_message_delay_sec)
        self.repeat_hold_freq_sec = float(repeat_hold_freq_sec)
        self.min_speed_mps = float(min_speed_kmh) / 3.6
        self.max_closing_speed_mps = float(max_closing_speed_kmh) / 3.6
        self.use_oval_logic = bool(use_oval_logic)
        self.enable_three_wide = bool(enable_three_wide)

        # Instanciation des sous-systèmes modulaires (SOLID SRP/ISP/DIP)
        self.geometry_engine = CartesianGeometry2D()
        self.speed_filter = OpponentSpeedFilter(
            calculate_speeds_interval_sec=0.2,
            max_closing_speed_mps=self.max_closing_speed_mps,
        )
        self.overlap_evaluator = CartesianOverlapEvaluator(
            car_length_m=self.car_length_m,
            car_width_m=self.car_width_m,
            gap_needed_for_clear_m=self.gap_needed_for_clear_m,
        )
        self.fsm = SpotterStateMachine(
            clear_message_delay_sec=self.clear_message_delay_sec,
            repeat_hold_freq_sec=self.repeat_hold_freq_sec,
            enable_three_wide=self.enable_three_wide,
        )
        self._road_phrasing = RoadSpotterPhrasingStrategy()
        self._oval_phrasing = OvalSpotterPhrasingStrategy()

        # Variables dynamiques de télémétrie précédente
        self._prev_player_x: float = 0.0
        self._prev_player_z: float = 0.0
        self._prev_time: float = 0.0

        # Données de diagnostic en direct pour l'IHM
        self._live_cars_left: int = 0
        self._live_cars_right: int = 0
        self._live_channel_open: bool = False
        self._live_last_message: str = "none"

    def get_parameters(self) -> List[RoleParam]:
        """Déclare les paramètres configurables pour l'éditeur IHM."""
        return [
            FloatRangeParam(
                name="car_length_m",
                label="Car Length",
                description="Longueur nominale du véhicule (mètres)",
                min_val=2.5,
                max_val=6.0,
                step=0.1,
                unit="m",
                default=4.2,
            ),
            FloatRangeParam(
                name="car_width_m",
                label="Car Width",
                description="Largeur nominale du véhicule (mètres)",
                min_val=1.2,
                max_val=2.5,
                step=0.05,
                unit="m",
                default=1.9,
            ),
            FloatRangeParam(
                name="gap_needed_for_clear_m",
                label="Clear Gap Hysteresis",
                description="Distance supplémentaire requise pour déclarer 'Clear' (mètres)",
                min_val=0.2,
                max_val=5.0,
                step=0.1,
                unit="m",
                default=1.5,
            ),
            FloatRangeParam(
                name="clear_message_delay_sec",
                label="Clear Delay",
                description="Délai de confirmation avant d'annoncer Clear (secondes)",
                min_val=0.0,
                max_val=2.0,
                step=0.05,
                unit="s",
                default=0.35,
            ),
            FloatRangeParam(
                name="repeat_hold_freq_sec",
                label="Hold Repeat Frequency",
                description="Fréquence de rappel 'Still There' pendant un overlap maintenu (secondes)",
                min_val=1.0,
                max_val=10.0,
                step=0.5,
                unit="s",
                default=3.0,
            ),
            FloatRangeParam(
                name="min_speed_kmh",
                label="Min Speed for Spotter",
                description="Vitesse minimale requise pour activer le Spotter (km/h)",
                min_val=10.0,
                max_val=100.0,
                step=5.0,
                unit="km/h",
                default=35.0,
            ),
            FloatRangeParam(
                name="max_closing_speed_kmh",
                label="Max Closing Speed",
                description="Vitesse relative différentielle maximale tolérée pour un overlap (km/h)",
                min_val=30.0,
                max_val=200.0,
                step=5.0,
                unit="km/h",
                default=90.0,
            ),
            BoolParam(
                name="use_oval_logic",
                label="Oval Course Phrasing",
                description="Utiliser les termes Inside / Outside au lieu de Left / Right",
                default=False,
            ),
            BoolParam(
                name="enable_three_wide",
                label="Enable 3-Wide Calls",
                description="Activer les détections et annonces de situation 3-Wide",
                default=True,
            ),
        ]

    def set_param_value(self, name: str, value: Any) -> None:
        """Applique et synchronise les paramètres avec les sous-systèmes internes."""
        super().set_param_value(name, value)
        if name in ("car_length_m", "car_width_m", "gap_needed_for_clear_m"):
            self.overlap_evaluator.set_dimensions(
                self.car_length_m, self.car_width_m, self.gap_needed_for_clear_m
            )
        elif name == "clear_message_delay_sec":
            self.fsm.clear_message_delay_sec = float(self.clear_message_delay_sec)
        elif name == "repeat_hold_freq_sec":
            self.fsm.repeat_hold_freq_sec = float(self.repeat_hold_freq_sec)
        elif name == "min_speed_kmh":
            self.min_speed_mps = float(self.min_speed_kmh) / 3.6
        elif name == "max_closing_speed_kmh":
            self.max_closing_speed_mps = float(self.max_closing_speed_kmh) / 3.6
            self.speed_filter.max_closing_speed_mps = self.max_closing_speed_mps
        elif name == "enable_three_wide":
            self.fsm.enable_three_wide = bool(self.enable_three_wide)

    def get_channel_requirements(self) -> List[Any]:
        try:
            from simpad_qt.core.telemetry_channels import TelemetryChannel, ChannelRequirement
            return [
                ChannelRequirement(
                    channel=TelemetryChannel.TELEMETRY,
                    preferred_hz=100,
                    required=True,
                    reason="Orientation lacet (yaw) et cinématique locale ultra-précise du joueur",
                ),
                ChannelRequirement(
                    channel=TelemetryChannel.FULL_SCORING,
                    preferred_hz=10,
                    required=True,
                    reason="Positions mondiales 3D et vecteurs vitesse de l'ensemble du plateau",
                ),
            ]
        except ImportError:
            return []

    def get_sound_requirements(self) -> Dict[str, str]:
        return {
            "car_left": "Car left",
            "car_right": "Car right",
            "clear_left": "Clear left",
            "clear_right": "Clear right",
            "clear_all_round": "Clear all round",
            "three_wide": "Three wide",
            "three_wide_left": "Three wide on the left",
            "three_wide_right": "Three wide on the right",
            "car_inside": "Car inside",
            "car_outside": "Car outside",
            "clear_inside": "Clear inside",
            "clear_outside": "Clear outside",
            "three_wide_inside": "Three wide on the inside",
            "three_wide_outside": "Three wide on the outside",
            "still_there": "Still there",
        }

    def is_busy(self) -> bool:
        """
        Indique si le Spotter est actuellement engagé dans une situation critique
        (overlap actif, 3-wide ou annonce en cours de planification).
        """
        return (
            self.fsm.channel_open or
            self.fsm.reported_single_overlap_left or
            self.fsm.reported_single_overlap_right or
            self.fsm.reported_double_overlap_left or
            self.fsm.reported_double_overlap_right or
            self.fsm.next_message_type != SpotterMessageType.NONE
        )

    def reset(self) -> None:
        """Réinitialise totalement l'état du rôle."""
        self.fsm.reset()
        self.speed_filter.clear()
        self._prev_player_x = 0.0
        self._prev_player_z = 0.0
        self._prev_time = 0.0
        self._live_cars_left = 0
        self._live_cars_right = 0
        self._live_channel_open = False
        self._live_last_message = "none"

    def _extract_player_data(
        self,
        context: EngineerContext,
        now: float,
    ) -> Optional[Tuple[float, float, float, float, float]]:
        """
        Extrait la position (X, Z), la vitesse (vx, vz) et l'orientation lacet (yaw) du joueur.
        Retourne (player_x, player_z, vel_x, vel_z, player_yaw_rad) ou None.
        """
        player_veh = context.get_player_vehicle()
        if not player_veh:
            return None

        # Position cartésienne
        pos = get_vehicle_attr(player_veh, "pos")
        if pos is None:
            return None

        if isinstance(pos, dict):
            px = float(pos.get("x", 0.0))
            pz = float(pos.get("z", pos.get("y", 0.0)))
        elif hasattr(pos, "x") and (hasattr(pos, "z") or hasattr(pos, "y")):
            px = float(pos.x)
            pz = float(getattr(pos, "z", getattr(pos, "y", 0.0)))
        elif isinstance(pos, (list, tuple)):
            if len(pos) >= 3:
                px = float(pos[0])
                pz = float(pos[2])  # Dans ISI X/Y/Z : Z est le plan au sol
            elif len(pos) == 2:
                px = float(pos[0])
                pz = float(pos[1])
            else:
                return None
        else:
            return None

        if px == 0.0 and pz == 0.0:
            return None

        # Calcul ou extraction de la vitesse
        dt = (now - self._prev_time) if self._prev_time > 0.0 else 0.05
        dt = max(0.001, dt)

        vel_obj = get_vehicle_attr(player_veh, "local_vel")
        if isinstance(vel_obj, dict):
            vx = float(vel_obj.get("x", 0.0))
            vz = float(vel_obj.get("z", vel_obj.get("y", 0.0)))
        elif hasattr(vel_obj, "x") and (hasattr(vel_obj, "z") or hasattr(vel_obj, "y")):
            vx = float(vel_obj.x)
            vz = float(getattr(vel_obj, "z", getattr(vel_obj, "y", 0.0)))
        elif isinstance(vel_obj, (list, tuple)):
            if len(vel_obj) >= 3:
                vx = float(vel_obj[0])
                vz = float(vel_obj[2])
            elif len(vel_obj) == 2:
                vx = float(vel_obj[0])
                vz = float(vel_obj[1])
            else:
                vx, vz = 0.0, 0.0
        elif self._prev_time > 0.0:
            vx = (px - self._prev_player_x) / dt
            vz = (pz - self._prev_player_z) / dt
        else:
            speed_val = context.get_player_speed_mps()
            vx, vz = 0.0, float(speed_val)

        # Calcul ou extraction de l'orientation (yaw)
        m_ori = get_vehicle_attr(player_veh, "mOri") or get_vehicle_attr(player_veh, "ori")
        yaw_from_ori = self.geometry_engine.compute_yaw_from_orientation(m_ori)
        if yaw_from_ori is not None:
            yaw = yaw_from_ori
        else:
            yaw = self.geometry_engine.compute_yaw_from_velocity(vx, vz)

        self._prev_player_x = px
        self._prev_player_z = pz
        self._prev_time = now

        return px, pz, vx, vz, yaw

    def update(self, context: EngineerContext) -> Optional[EngineerMessage]:
        """
        Évalue la télémétrie et le positionnement relatif à chaque tick.
        """
        if not self.enabled:
            return None

        now = context.timestamp or time.time()

        # 1. Filtre conditions globales : Stand, Garage, Qualification isolée
        if context.is_player_in_pits() or context.is_player_in_garage() or context.is_private_qualifying():
            if self.is_busy():
                self.reset()
            return None

        # 2. Extraction des données joueur
        player_data = self._extract_player_data(context, now)
        if not player_data:
            return None

        player_x, player_z, player_vx, player_vz, player_yaw = player_data
        player_speed_scalar = math.sqrt(player_vx * player_vx + player_vz * player_vz)

        # Filtre vitesse minimale
        if player_speed_scalar < self.min_speed_mps:
            if self.fsm.channel_open and (now > self.fsm.time_when_channel_should_close):
                self.reset()
            elif self.fsm.channel_open and self.fsm.time_when_channel_should_close == float("inf"):
                self.fsm.time_when_channel_should_close = now + self.fsm.time_to_wait_before_closing_channel_sec
            return None
        else:
            self.fsm.time_when_channel_should_close = float("inf")

        # 3. Récupération des adversaires sur la piste (exclut stands et garages)
        opponents = context.get_track_opponents()
        active_ids = set()

        left_separations: List[float] = []
        right_separations: List[float] = []

        had_overlap_left = self.fsm.cars_on_left_prev > 0
        had_overlap_right = self.fsm.cars_on_right_prev > 0

        # 4. Traitement géométrique et cinématique pour chaque adversaire
        for opp in opponents:
            opp_id = int(get_vehicle_attr(opp, "id", 0) or get_vehicle_attr(opp, "mID", 0))
            pos = get_vehicle_attr(opp, "pos")
            if pos is None:
                continue

            if isinstance(pos, dict):
                ox = float(pos.get("x", 0.0))
                oz = float(pos.get("z", pos.get("y", 0.0)))
            elif hasattr(pos, "x") and (hasattr(pos, "z") or hasattr(pos, "y")):
                ox = float(pos.x)
                oz = float(getattr(pos, "z", getattr(pos, "y", 0.0)))
            elif isinstance(pos, (list, tuple)):
                if len(pos) >= 3:
                    ox = float(pos[0])
                    oz = float(pos[2])
                elif len(pos) == 2:
                    ox = float(pos[0])
                    oz = float(pos[1])
                else:
                    continue
            else:
                continue

            if ox == 0.0 and oz == 0.0:
                continue

            active_ids.add(opp_id)

            # Extraction optionnelle vitesse adversaire
            ovx, ovz = None, None
            opp_vel = get_vehicle_attr(opp, "local_vel")
            if isinstance(opp_vel, dict):
                ovx = float(opp_vel.get("x", 0.0))
                ovz = float(opp_vel.get("z", opp_vel.get("y", 0.0)))
            elif isinstance(opp_vel, (list, tuple)):
                if len(opp_vel) >= 3:
                    ovx = float(opp_vel[0])
                    ovz = float(opp_vel[2])
                elif len(opp_vel) == 2:
                    ovx = float(opp_vel[0])
                    ovz = float(opp_vel[1])

            # Projection cartésienne 2D dans le repère local joueur
            aligned_x, aligned_z = self.geometry_engine.get_aligned_xz_coordinates(
                player_yaw, player_x, player_z, ox, oz
            )

            # Vérification pré-filtrage portée (20m)
            if not self.overlap_evaluator.is_in_consideration_zone(aligned_x, aligned_z):
                continue

            # Validation de la vitesse de rapprochement
            is_speed_valid = self.speed_filter.update_and_validate(
                opponent_id=opp_id,
                opp_x=ox,
                opp_z=oz,
                player_vel_x=player_vx,
                player_vel_z=player_vz,
                now=now,
                opp_vel_x=ovx,
                opp_vel_z=ovz,
            )

            # Évaluation d'overlap
            side, lateral_sep = self.overlap_evaluator.evaluate_opponent_overlap(
                aligned_x=aligned_x,
                aligned_z=aligned_z,
                had_overlap_on_side=(had_overlap_left if aligned_x > 0 else had_overlap_right),
                is_speed_valid=is_speed_valid,
            )

            if side == SpotterSide.LEFT:
                left_separations.append(lateral_sep)
            elif side == SpotterSide.RIGHT:
                right_separations.append(lateral_sep)

        # Purge des véhicules hors de portée
        self.speed_filter.purge_inactive(active_ids)

        # 5. Détection 3-Wide et filtrage file indienne
        cars_on_left, cars_on_right = self.overlap_evaluator.analyze_multi_car_distribution(
            left_separations, right_separations
        )

        self._live_cars_left = cars_on_left
        self._live_cars_right = cars_on_right

        # 6. Évaluation machine à états (FSM)
        self.fsm.evaluate_next_message(
            cars_on_left=cars_on_left,
            cars_on_right=cars_on_right,
            now=now,
            use_oval_logic=self.use_oval_logic,
        )

        # 7. Exécution et émission audio
        playback_result = self.fsm.process_playback_tick(
            cars_on_left=cars_on_left,
            cars_on_right=cars_on_right,
            now=now,
        )

        self.fsm.cars_on_left_prev = cars_on_left
        self.fsm.cars_on_right_prev = cars_on_right
        self._live_channel_open = self.fsm.channel_open

        if playback_result is not None:
            msg_type, keep_open = playback_result
            strategy: ISpotterPhrasingStrategy = self._oval_phrasing if self.use_oval_logic else self._road_phrasing
            phrase_key = strategy.resolve_phrase(msg_type)

            if phrase_key:
                self._live_last_message = phrase_key
                # Les alertes spotter de combat ont la priorité maximale et interrompent les messages réguliers
                msg = EngineerMessage(
                    phrase_key=phrase_key,
                    priority=self.priority,
                    interrupt=True,
                    role_id=self.role_id,
                )
                self.emit_sound(phrase_key, interrupt=True)
                return msg

        return None

    def get_state_summary(self) -> Dict[str, Any]:
        """Retourne le diagnostic d'état en direct pour le monitoring IHM."""
        summary = super().get_state_summary()
        summary.update({
            "cars_on_left": self._live_cars_left,
            "cars_on_right": self._live_cars_right,
            "channel_open": self._live_channel_open,
            "last_message": self._live_last_message,
            "is_busy": self.is_busy(),
        })
        return summary
