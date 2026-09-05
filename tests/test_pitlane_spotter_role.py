"""
Tests unitaires pour PitlaneSpotterRole (Machine à états Unsafe Release & Pitlane Spotter).
"""

import pytest
from simpad_qt.builtin_plugins.race_engineer.context import EngineerContext
from simpad_qt.builtin_plugins.race_engineer.subplugins.pitlane_spotter import PitlaneSpotterRole, PitlaneSpotterState
from simpad_qt.builtin_plugins.race_engineer.manager import RaceEngineer


from isimotor_rawudp_client import FullScoringSession, VehicleScoring, TelemVect3


def make_pitlane_packet(
    player_speed_mps: float = 0.0,
    player_in_pits: bool = True,
    player_pit_state: int = 3,  # 3=stopped in box
    player_lap_dist: float = 1000.0,
    opp_speed_mps: float = 16.0,  # ~58 km/h under limiter
    opp_in_pits: bool = True,
    opp_pit_state: int = 2,  # 2=entering/in-lap/fast lane
    opp_lap_dist: float = 980.0,  # 20m behind player in pitlane
    track_len: float = 5000.0,
):
    """Construit un paquet de scoring LMU réaliste en voie des stands."""
    p_veh = VehicleScoring(
        id=1,
        driver_name="Player Driver",
        vehicle_name="Ferrari 499P #50",
        is_player=True,
        control=0,
        lap_dist=player_lap_dist,
        local_vel=TelemVect3(0.0, 0.0, player_speed_mps),
        in_garage_stall=False,
        in_pits=player_in_pits,
        pit_state=player_pit_state,
        pos=TelemVect3(10.0, 0.0, player_lap_dist),
        finish_status=0,
    )
    opp_veh = VehicleScoring(
        id=2,
        driver_name="Ian James",
        vehicle_name="Aston Martin #27",
        is_player=False,
        control=1,
        lap_dist=opp_lap_dist,
        local_vel=TelemVect3(0.0, 0.0, opp_speed_mps),
        in_garage_stall=False,
        in_pits=opp_in_pits,
        pit_state=opp_pit_state,
        pos=TelemVect3(10.0, 0.0, opp_lap_dist),
        finish_status=0,
    )
    return FullScoringSession(
        session=10,
        track_name="Test Track",
        lap_dist=track_len,
        vehicles=[p_veh, opp_veh],
    )


def test_pitlane_spotter_inactive_when_player_on_track():
    """Vérifie que le spotter de pitlane est totalement inactif (IDLE) quand le joueur est en piste."""
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = PitlaneSpotterRole(audio_engine=mock_audio)

    # Joueur en piste (mInPits=False), adversaire dans les stands
    sc = make_pitlane_packet(player_speed_mps=70.0, player_in_pits=False, player_pit_state=0)
    msg = role.update(EngineerContext(scoring=sc))

    assert msg is None
    assert role.state == PitlaneSpotterState.IDLE
    assert not role.is_busy()
    assert len(played) == 0


def test_unsafe_release_hazard_and_clear_lifecycle():
    """
    Vérifie le cycle complet de protection Unsafe Release :
    1. Joueur au box -> Surveillance active.
    2. Voiture déboule dans la Fast Lane derrière le box -> Alerte "car" avec interrupt=True (UNSAFE_HAZARD).
    3. Voiture passe devant / Fast Lane libérée -> Annonce "clear" (RELEASE_CLEAR).
    """
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = PitlaneSpotterRole(
        audio_engine=mock_audio,
        unsafe_release_distance_m=28.0,
        unsafe_release_ttc_sec=2.5,
    )

    # 1. Joueur arrêté au box (mPitState=3), aucune voiture proche (adversaire 100m derrière)
    sc_clear = make_pitlane_packet(
        player_speed_mps=0.0,
        player_in_pits=True,
        player_pit_state=3,
        player_lap_dist=1000.0,
        opp_speed_mps=16.0,
        opp_lap_dist=900.0,  # 100m derrière
    )
    msg1 = role.update(EngineerContext(scoring=sc_clear))
    assert msg1 is None
    assert role.state == PitlaneSpotterState.BOX_MONITORING
    assert not role.is_busy()

    # 2. Une voiture arrive à 16 m/s (~58 km/h) à 20m derrière le box (TTC = 20 / 16 = 1.25s <= 2.5s)
    # -> Déclenchement de l'alerte UNSAFE_HAZARD ("car", interrupt=True)
    sc_hazard = make_pitlane_packet(
        player_speed_mps=0.0,
        player_in_pits=True,
        player_pit_state=3,
        player_lap_dist=1000.0,
        opp_speed_mps=16.0,
        opp_lap_dist=980.0,  # 20m derrière
    )
    msg2 = role.update(EngineerContext(scoring=sc_hazard))

    assert msg2 is not None
    assert msg2.phrase_key == "car"
    assert msg2.interrupt is True
    assert role.state == PitlaneSpotterState.UNSAFE_HAZARD
    assert role.is_busy()
    assert ("car", True) in played

    # 3. La voiture est passée devant le box (10m devant) -> Fast Lane libre -> Annonce "clear"
    sc_passed = make_pitlane_packet(
        player_speed_mps=0.0,
        player_in_pits=True,
        player_pit_state=3,
        player_lap_dist=1000.0,
        opp_speed_mps=16.0,
        opp_lap_dist=1015.0,  # 15m devant
    )
    msg3 = role.update(EngineerContext(scoring=sc_passed))

    assert msg3 is not None
    assert msg3.phrase_key == "clear"
    assert msg3.interrupt is True
    assert role.state == PitlaneSpotterState.RELEASE_CLEAR
    assert ("clear", True) in played


def test_pitlane_driving_traffic_slow_car_ahead():
    """Vérifie l'alerte sur un véhicule arrêté ou au ralenti devant dans la pitlane lors du roulage."""
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = PitlaneSpotterRole(
        audio_engine=mock_audio,
        pit_slow_ahead_distance_m=35.0,
        pit_slow_speed_threshold_kmh=20.0,
    )

    # Joueur roulant à 16 m/s (58 km/h) dans la pitlane (mPitState=2)
    # Voiture devant à 20m au ralenti (3 m/s = 10.8 km/h < 20 km/h)
    sc_slow_ahead = make_pitlane_packet(
        player_speed_mps=16.0,
        player_in_pits=True,
        player_pit_state=2,
        player_lap_dist=1000.0,
        opp_speed_mps=3.0,
        opp_lap_dist=1020.0,  # 20m devant
    )

    msg = role.update(EngineerContext(scoring=sc_slow_ahead))
    assert msg is not None
    assert msg.phrase_key == "car"
    assert role.state == PitlaneSpotterState.PIT_TRAFFIC_AHEAD
    assert role.is_busy()
    assert ("car", False) in played


def test_pitlane_overlap_alongside():
    """Vérifie l'alerte de véhicule bord à bord (Alongside) dans la voie des stands."""
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = PitlaneSpotterRole(audio_engine=mock_audio)

    # Joueur roulant dans la pitlane, une voiture sort d'un box juste à côté (distance 2m)
    sc_overlap = make_pitlane_packet(
        player_speed_mps=15.0,
        player_in_pits=True,
        player_pit_state=2,
        player_lap_dist=1000.0,
        opp_speed_mps=12.0,
        opp_lap_dist=1001.0,  # 1m de différence (côte à côte)
    )

    msg = role.update(EngineerContext(scoring=sc_overlap))
    assert msg is not None
    assert msg.phrase_key == "alongside"
    assert msg.interrupt is True
    assert role.state == PitlaneSpotterState.PIT_OVERLAP
    assert ("alongside", True) in played


def test_race_engineer_loads_pitlane_spotter_by_default():
    """Vérifie que RaceEngineer instancie et gère PitlaneSpotterRole par défaut."""
    engineer_no_cfg = RaceEngineer(auto_load_builtin_roles=True, auto_load_config=False)
    pit_role_default = engineer_no_cfg.get_role("pitlane_spotter")
    assert pit_role_default is not None
    assert isinstance(pit_role_default, PitlaneSpotterRole)
    assert pit_role_default.priority == 95

    engineer = RaceEngineer(auto_load_builtin_roles=True)
    pit_role = engineer.get_role("pitlane_spotter")
    assert pit_role is not None
    assert isinstance(pit_role, PitlaneSpotterRole)
    assert pit_role.enabled is True


def test_pitlane_spotter_with_typed_vehicle_scoring():
    """Vérifie que PitlaneSpotterRole et EngineerContext gèrent parfaitement les objets typés VehicleScoring et FullScoringSession."""
    from isimotor_rawudp_client import VehicleScoring, FullScoringSession, TelemVect3

    player = VehicleScoring(
        id=1,
        driver_name="Player Driver",
        is_player=True,
        control=0,
        in_pits=True,
        pit_state=3,  # Stopped at box
        in_garage_stall=False,
        lap_dist=500.0,
        local_vel=TelemVect3(0.0, 0.0, 0.0),
    )
    opp = VehicleScoring(
        id=2,
        driver_name="Fast Pit Opponent",
        is_player=False,
        control=1,
        in_pits=True,
        pit_state=2,
        in_garage_stall=False,
        lap_dist=480.0,  # 20m behind (within 28m unsafe release threshold)
        local_vel=TelemVect3(0.0, 0.0, -16.0),  # 58 km/h fast lane
    )
    session = FullScoringSession(
        session=10,
        track_name="Bahrain International Circuit",
        lap_dist=5412.0,
        vehicles=[player, opp],
    )

    played = []
    role = PitlaneSpotterRole(audio_engine=lambda pk, interrupt=False: played.append((pk, interrupt)))
    ctx = EngineerContext(scoring=session)

    msg = role.update(ctx)
    assert msg is not None
    assert msg.phrase_key == "car"
    assert role.state == PitlaneSpotterState.UNSAFE_HAZARD
    assert ("car", True) in played

