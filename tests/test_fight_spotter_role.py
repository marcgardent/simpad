"""
Tests unitaires complets pour FightSpotterRole (CrewChief Cartesian FSM Fight Spotter).
Vérifie la transformation 2D, le filtrage cinématique, l'hystérésis d'overlap,
la détection 3-Wide vs file indienne, et la machine à états temporelle anti-chatter.
"""

import math
import pytest
from src.engineer.context import EngineerContext
from src.engineer.base import RoleStatus
from src.engineer.roles.fight_spotter import (
    FightSpotterRole,
    SpotterSide,
    SpotterMessageType,
    CartesianGeometry2D,
    OpponentSpeedFilter,
    CartesianOverlapEvaluator,
    SpotterStateMachine,
    RoadSpotterPhrasingStrategy,
    OvalSpotterPhrasingStrategy,
)


from isimotor_rawudp_client import FullScoringSession, VehicleScoring, TelemVect3


def make_spotter_packet(
    player_pos=(100.0, 500.0),
    player_vel=(0.0, 30.0),  # ~108 km/h vers le Nord (+Z)
    player_yaw=0.0,
    player_in_pits=False,
    opponents=None,
    track_len=5000.0,
):
    """Génère un paquet de scoring LMU pour tester le Fight Spotter."""
    opp_list = opponents or []
    cos_y = math.cos(player_yaw)
    sin_y = math.sin(player_yaw)
    ori = (
        TelemVect3(cos_y, 0.0, -sin_y),
        TelemVect3(0.0, 1.0, 0.0),
        TelemVect3(sin_y, 0.0, cos_y),
    )
    p_veh = VehicleScoring(
        id=1,
        driver_name="Player Driver",
        vehicle_name="Porsche 963 #5",
        is_player=True,
        control=0,
        lap_dist=player_pos[1],
        pos=TelemVect3(player_pos[0], 0.0, player_pos[1]),
        local_vel=TelemVect3(player_vel[0], 0.0, player_vel[1]),
        ori=ori,
        in_garage_stall=False,
        in_pits=player_in_pits,
        pit_state=0,
        finish_status=0,
    )
    veh_list = [p_veh]

    for i, opp in enumerate(opp_list, start=2):
        ox, oz = opp.get("pos", (player_pos[0], player_pos[1]))
        vx, vz = opp.get("vel", (0.0, 30.0))
        in_pits = opp.get("in_pits", False)
        veh_list.append(VehicleScoring(
            id=opp.get("id", i),
            driver_name=opp.get("name", f"Opponent {i}"),
            vehicle_name="Ferrari 499P #50",
            is_player=False,
            control=1,
            lap_dist=oz,
            pos=TelemVect3(ox, 0.0, oz),
            local_vel=TelemVect3(vx, 0.0, vz),
            ori=ori,
            in_garage_stall=False,
            in_pits=in_pits,
            pit_state=0,
            finish_status=0,
        ))

    return FullScoringSession(
        session=10,
        track_name="Test Circuit",
        lap_dist=track_len,
        vehicles=veh_list,
    )


# =============================================================================
# 1. TESTS GÉOMÉTRIE CARTÉSIENNE 2D
# =============================================================================

def test_geometry_rotation_north():
    """Vérifie la projection avec un lacet nul (Nord)."""
    geom = CartesianGeometry2D()
    # Player à (0, 0), face Nord (yaw=0)
    # Opponent à gauche (+2m en X, 0m en Z)
    ax, az = geom.get_aligned_xz_coordinates(
        player_rotation_rad=0.0,
        player_x=0.0,
        player_z=0.0,
        opponent_x=2.0,
        opponent_z=0.0,
    )
    assert pytest.approx(ax, 0.01) == 2.0  # Gauche
    assert pytest.approx(az, 0.01) == 0.0  # Côte à côte


def test_geometry_rotation_east():
    """Vérifie la projection lorsque la voiture braque à 90° Est (yaw = pi/2)."""
    geom = CartesianGeometry2D()
    # Face à l'Est (yaw = pi/2), une voiture située au Nord (+Z) est à sa GAUCHE (+X_aligné)
    ax, az = geom.get_aligned_xz_coordinates(
        player_rotation_rad=math.pi / 2.0,
        player_x=0.0,
        player_z=0.0,
        opponent_x=0.0,
        opponent_z=5.0,
    )
    assert pytest.approx(ax, 0.01) == 5.0   # À gauche dans le repère local
    assert pytest.approx(az, 0.01) == 0.0   # Aligné longitudinalement


# =============================================================================
# 2. TESTS ÉVALUATEUR D'OVERLAP ET HYSTÉRÉSIS (CLEAR GAP)
# =============================================================================

def test_overlap_evaluator_hysteresis():
    """
    Vérifie l'hystérésis d'overlap :
    - Entrée en overlap si |Z| < 4.2m.
    - Maintien d'overlap jusqu'à 4.2m + 1.5m = 5.7m si had_overlap=True.
    """
    evaluator = CartesianOverlapEvaluator(
        car_length_m=4.2,
        car_width_m=1.9,
        gap_needed_for_clear_m=1.5,
    )

    # 1. Pas d'overlap initial, adversaire à 5.0m derrière (X=-2.0m à droite)
    side, sep = evaluator.evaluate_opponent_overlap(
        aligned_x=-2.0,
        aligned_z=5.0,
        had_overlap_on_side=False,
        is_speed_valid=True,
    )
    assert side == SpotterSide.NONE

    # 2. Entrée en overlap à 3.0m derrière (X=-2.0m à droite)
    side, sep = evaluator.evaluate_opponent_overlap(
        aligned_x=-2.0,
        aligned_z=3.0,
        had_overlap_on_side=False,
        is_speed_valid=True,
    )
    assert side == SpotterSide.RIGHT
    assert pytest.approx(sep, 0.01) == 2.0

    # 3. L'adversaire recule à 5.0m derrière, mais had_overlap=True -> Maintien de l'overlap
    side, sep = evaluator.evaluate_opponent_overlap(
        aligned_x=-2.0,
        aligned_z=5.0,
        had_overlap_on_side=True,
        is_speed_valid=True,
    )
    assert side == SpotterSide.RIGHT

    # 4. L'adversaire dépasse la marge de sécurité (6.0m > 5.7m) -> Dégagement (Clear)
    side, sep = evaluator.evaluate_opponent_overlap(
        aligned_x=-2.0,
        aligned_z=6.0,
        had_overlap_on_side=True,
        is_speed_valid=True,
    )
    assert side == SpotterSide.NONE


# =============================================================================
# 3. TESTS MULTI-VOITURES : FILE INDIENNE VS 3-WIDE
# =============================================================================

def test_line_astern_vs_three_wide():
    """
    Vérifie la distinction entre deux voitures en file indienne et deux voitures côte à côte.
    """
    evaluator = CartesianOverlapEvaluator(car_width_m=1.9)

    # Cas 1 : Deux voitures à gauche (X=2.0m et X=2.2m -> delta = 0.2m < 1.9m) -> File indienne = 1 voiture
    left_cars, right_cars = evaluator.analyze_multi_car_distribution(
        left_separations=[2.0, 2.2],
        right_separations=[],
    )
    assert left_cars == 1
    assert right_cars == 0

    # Cas 2 : Deux voitures à gauche espacées (X=2.0m et X=4.5m -> delta = 2.5m >= 1.9m) -> 3-Wide = 2 voitures
    left_cars, right_cars = evaluator.analyze_multi_car_distribution(
        left_separations=[2.0, 4.5],
        right_separations=[],
    )
    assert left_cars == 2
    assert right_cars == 0


# =============================================================================
# 4. TESTS MACHINE À ÉTATS ET ÉMISSION AUDIO
# =============================================================================

def test_fight_spotter_car_left_and_clear_lifecycle():
    """
    Vérifie le cycle complet d'alerte :
    1. Piste dégagée.
    2. Voiture à gauche -> "car_left" émis immédiatement.
    3. Overlap maintenu -> "still_there" émis après 3s.
    4. Dégagement avec délai -> "clear_left".
    """
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = FightSpotterRole(
        audio_engine=mock_audio,
        clear_message_delay_sec=0.3,
        repeat_hold_freq_sec=3.0,
    )

    t0 = 100.0

    # 1. Piste dégagée (aucun adversaire)
    sc_clear = make_spotter_packet(player_pos=(0.0, 1000.0), opponents=[])
    msg = role.update(EngineerContext(scoring=sc_clear, timestamp=t0))
    assert msg is None
    assert not role.is_busy()

    # 2. Adversaire apparaît à gauche (X=2.5m, Z=1.0m)
    opp_left = [{"pos": (2.5, 1001.0), "vel": (0.0, 30.0)}]
    sc_overlap = make_spotter_packet(player_pos=(0.0, 1000.0), opponents=opp_left)

    msg = role.update(EngineerContext(scoring=sc_overlap, timestamp=t0 + 0.05))
    assert msg is not None
    assert msg.phrase_key == "car_left"
    assert role.is_busy()
    assert ("car_left", True) in played

    # 3. Maintien de l'overlap sans nouvelle alerte immédiate (anti-spam)
    msg = role.update(EngineerContext(scoring=sc_overlap, timestamp=t0 + 1.0))
    assert msg is None

    # 4. Après 3.1 secondes -> Rappel "still_there"
    msg = role.update(EngineerContext(scoring=sc_overlap, timestamp=t0 + 3.2))
    assert msg is not None
    assert msg.phrase_key == "still_there"

    # 5. La voiture dépasse et prend le large (Z=10.0m devant -> dégagement)
    sc_gone = make_spotter_packet(player_pos=(0.0, 1000.0), opponents=[{"pos": (2.5, 1010.0), "vel": (0.0, 30.0)}])

    # Début du délai de confirmation Clear (0.3s)
    msg = role.update(EngineerContext(scoring=sc_gone, timestamp=t0 + 4.0))
    assert msg is None  # En attente de confirmation
    assert role.is_busy()

    # Expiration du délai de confirmation -> Annonce "clear_left"
    msg = role.update(EngineerContext(scoring=sc_gone, timestamp=t0 + 4.4))
    assert msg is not None
    assert msg.phrase_key == "clear_left"
    assert ("clear_left", True) in played


def test_fight_spotter_three_wide_middle():
    """
    Vérifie la détection d'une situation 3-Wide au milieu (voiture à gauche et voiture à droite).
    """
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = FightSpotterRole(audio_engine=mock_audio)

    opponents_both_sides = [
        {"pos": (2.2, 1000.0), "vel": (0.0, 30.0)},   # Gauche
        {"pos": (-2.2, 1000.0), "vel": (0.0, 30.0)},  # Droite
    ]
    sc = make_spotter_packet(player_pos=(0.0, 1000.0), opponents=opponents_both_sides)

    msg = role.update(EngineerContext(scoring=sc, timestamp=10.0))
    assert msg is not None
    assert msg.phrase_key == "three_wide"
    assert ("three_wide", True) in played


def test_fight_spotter_oval_phrasing_strategy():
    """
    Vérifie l'utilisation des termes 'Inside' et 'Outside' en mode Ovale.
    """
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = FightSpotterRole(
        audio_engine=mock_audio,
        use_oval_logic=True,
    )

    # Adversaire à droite (-2.5m) en mode Ovale -> "car_outside"
    opp_right = [{"pos": (-2.5, 1000.0), "vel": (0.0, 30.0)}]
    sc = make_spotter_packet(player_pos=(0.0, 1000.0), opponents=opp_right)

    msg = role.update(EngineerContext(scoring=sc, timestamp=10.0))
    assert msg is not None
    assert msg.phrase_key == "car_outside"
    assert ("car_outside", True) in played


def test_fight_spotter_inactive_in_pitlane():
    """
    Vérifie que le spotter est inactif lorsque le joueur est dans les stands.
    """
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = FightSpotterRole(audio_engine=mock_audio)

    opp_left = [{"pos": (2.5, 1000.0), "vel": (0.0, 30.0)}]
    sc_pits = make_spotter_packet(player_pos=(0.0, 1000.0), player_in_pits=True, opponents=opp_left)

    msg = role.update(EngineerContext(scoring=sc_pits, timestamp=10.0))
    assert msg is None
    assert not role.is_busy()
    assert len(played) == 0
