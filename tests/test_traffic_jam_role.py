"""
Tests unitaires pour TrafficJamRole (Véhicules lents / drapeaux jaunes devant).
"""

import pytest
from isimotor_rawudp_client import FullScoringSession, VehicleScoring, TelemVect3
from src.engineer.context import EngineerContext
from src.engineer.roles.traffic_jam import TrafficJamRole


def test_traffic_jam_detection():
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = TrafficJamRole(
        audio_engine=mock_audio,
        slow_speed_threshold_kmh=50.0,  # 13.88 m/s
        warning_distance_m=150.0,
        cooldown_sec=5.0,
    )

    # 1. Piste dégagée
    p_veh = VehicleScoring(
        id=1, is_player=True, control=0,
        lap_dist=1000.0, local_vel=TelemVect3(0.0, 0.0, 50.0), finish_status=0,
    )
    opp_fast = VehicleScoring(
        id=2, driver_name="Fast Car Ahead", is_player=False, control=1,
        lap_dist=1080.0, local_vel=TelemVect3(0.0, 0.0, 55.0), finish_status=0,
    )
    scoring_clear = FullScoringSession(
        session=10, lap_dist=5000.0, vehicles=[p_veh, opp_fast],
    )

    msg1 = role.update(EngineerContext(scoring=scoring_clear))
    assert msg1 is None
    assert not role.is_busy()

    # 2. Voiture au ralenti ou accidentée devant (80m devant, vitesse = 5 m/s = 18 km/h < 50 km/h)
    opp_slow = VehicleScoring(
        id=2, driver_name="Slow Car Ahead", is_player=False, control=1,
        lap_dist=1080.0, local_vel=TelemVect3(0.0, 0.0, 5.0), finish_status=0,
    )
    scoring_slow = FullScoringSession(
        session=10, lap_dist=5000.0, vehicles=[p_veh, opp_slow],
    )

    msg2 = role.update(EngineerContext(scoring=scoring_slow))
    assert msg2 is not None
    assert msg2.phrase_key == "car"
    assert role.is_busy()
    assert ("car", False) in played


def test_traffic_jam_ignores_pit_lane_cars():
    """Vérifie qu'une voiture lente dans la voie des stands (in_pits=True) ne déclenche pas d'alerte pour le joueur en piste."""
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = TrafficJamRole(
        audio_engine=mock_audio,
        slow_speed_threshold_kmh=50.0,
        warning_distance_m=150.0,
    )

    p_veh = VehicleScoring(
        id=1, is_player=True, control=0,
        lap_dist=1000.0, local_vel=TelemVect3(0.0, 0.0, 50.0),
        in_pits=False, in_garage_stall=False, finish_status=0,
    )
    opp_pit = VehicleScoring(
        id=2, driver_name="Pit Lane Car", is_player=False, control=1,
        lap_dist=1080.0, local_vel=TelemVect3(0.0, 0.0, 8.0),
        in_pits=True, in_garage_stall=False, finish_status=0,
    )
    scoring_pit_slow = FullScoringSession(
        session=10, lap_dist=5000.0, vehicles=[p_veh, opp_pit],
    )

    msg = role.update(EngineerContext(scoring=scoring_pit_slow))
    assert msg is None
    assert not role.is_busy()
    assert len(played) == 0


def test_traffic_jam_deactivated_when_player_in_pits():
    """Vérifie que l'alerte traffic jam est désactivée quand le joueur est dans la pitlane."""
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = TrafficJamRole(
        audio_engine=mock_audio,
        slow_speed_threshold_kmh=50.0,
        warning_distance_m=150.0,
    )

    p_pit = VehicleScoring(
        id=1, is_player=True, control=0,
        lap_dist=1000.0, local_vel=TelemVect3(0.0, 0.0, 16.0),
        in_pits=True, in_garage_stall=False, finish_status=0,
    )
    opp_track = VehicleScoring(
        id=2, driver_name="Slow Track Car", is_player=False, control=1,
        lap_dist=1080.0, local_vel=TelemVect3(0.0, 0.0, 5.0),
        in_pits=False, in_garage_stall=False, finish_status=0,
    )
    scoring_player_in_pits = FullScoringSession(
        session=10, lap_dist=5000.0, vehicles=[p_pit, opp_track],
    )

    msg = role.update(EngineerContext(scoring=scoring_player_in_pits))
    assert msg is None
    assert not role.is_busy()
    assert len(played) == 0
