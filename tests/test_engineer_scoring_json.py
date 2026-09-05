"""
Test d'intégration du Race Engineer avec les paquets de scoring typés (isimotor_rawudp_client).
"""

import pytest
from isimotor_rawudp_client import VehicleScoring, FullScoringSession, TelemVect3
from simpad_qt.builtin_plugins.race_engineer.manager import RaceEngineer
from simpad_qt.builtin_plugins.race_engineer.context import EngineerContext
from simpad_qt.builtin_plugins.race_engineer.subplugins.traffic_spotter import TrafficSpotterRole
from simpad_qt.builtin_plugins.race_engineer.subplugins.lap_validity import LapValidityRole


def test_engineer_context_pit_and_track_separation_typed():
    """Vérifie la détection et la séparation piste vs pitlane avec un FullScoringSession typé."""
    player = VehicleScoring(
        id=1,
        driver_name="Player",
        is_player=True,
        control=0,
        in_pits=True,
        in_garage_stall=True,
        pit_state=3,
        lap_dist=100.0,
    )
    opp_track = VehicleScoring(
        id=2,
        driver_name="On Track",
        is_player=False,
        control=1,
        in_pits=False,
        in_garage_stall=False,
        pit_state=0,
        lap_dist=1200.0,
        finish_status=0,
    )
    opp_pit = VehicleScoring(
        id=3,
        driver_name="In Pit",
        is_player=False,
        control=1,
        in_pits=True,
        in_garage_stall=False,
        pit_state=2,
        lap_dist=200.0,
        finish_status=0,
    )
    opp_garage = VehicleScoring(
        id=4,
        driver_name="In Garage",
        is_player=False,
        control=1,
        in_pits=True,
        in_garage_stall=True,
        pit_state=3,
        lap_dist=50.0,
        finish_status=0,
    )
    session = FullScoringSession(
        session=10,
        track_name="Bahrain International Circuit",
        lap_dist=5412.0,
        vehicles=[player, opp_track, opp_pit, opp_garage],
    )
    ctx = EngineerContext(scoring=session)

    assert ctx.get_player_vehicle() == player
    assert ctx.is_player_in_garage() is True
    assert ctx.is_player_in_pits() is True

    track_opponents = ctx.get_track_opponents()
    assert len(track_opponents) == 1
    assert track_opponents[0].driver_name == "On Track"

    pit_opponents = ctx.get_pit_opponents()
    assert len(pit_opponents) == 1
    assert pit_opponents[0].driver_name == "In Pit"

    all_opponents = ctx.get_opponent_vehicles(include_pits=True, include_garage=True)
    assert len(all_opponents) == 3


def test_race_engineer_with_typed_full_scoring_session():
    """Vérifie l'exécution complète de tous les rôles du RaceEngineer avec un FullScoringSession typé (isimotor_rawudp_client)."""
    from isimotor_rawudp_client import VehicleScoring, FullScoringSession, TelemVect3

    player = VehicleScoring(
        id=1,
        driver_name="Player 1",
        is_player=True,
        control=0,
        in_pits=False,
        in_garage_stall=False,
        lap_dist=1200.0,
        local_vel=TelemVect3(0.0, 0.0, -60.0),
        total_laps=5,
        count_lap_flag=2,
    )
    opp1 = VehicleScoring(
        id=2,
        driver_name="Opponent Fast",
        is_player=False,
        control=1,
        in_pits=False,
        in_garage_stall=False,
        lap_dist=1150.0,  # 50m behind
        local_vel=TelemVect3(0.0, 0.0, -75.0),  # +15 m/s faster
        total_laps=5,
    )
    opp2 = VehicleScoring(
        id=3,
        driver_name="Opponent Slow",
        is_player=False,
        control=1,
        in_pits=False,
        in_garage_stall=False,
        lap_dist=1300.0,  # 100m ahead
        local_vel=TelemVect3(0.0, 0.0, -10.0),  # very slow ahead
        total_laps=5,
    )
    session = FullScoringSession(
        session=10,
        track_name="Bahrain International Circuit",
        lap_dist=5412.0,
        vehicles=[player, opp1, opp2],
    )

    played = []
    engineer = RaceEngineer(audio_engine=lambda pk, interrupt=False: played.append((pk, interrupt)))

    # Exécution du cycle d'évaluation avec tous les rôles activés
    messages = engineer.update(telemetry=None, scoring=session)
    assert isinstance(messages, list)

