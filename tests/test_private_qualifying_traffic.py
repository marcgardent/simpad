"""
Tests unitaires pour la détection du Private Qualifying et la désactivation des 3 rôles Trafic.
Vérifie que TrafficSpotterRole, TrafficJamRole et PitlaneSpotterRole restent totalement silencieux
lorsque la session est une qualification (session entre 5 et 8 inclus), conformément au protocole LMU.
"""

import pytest
from isimotor_rawudp_client import FullScoringSession, CompactScoring, VehicleScoring, TelemVect3
from simpulse.builtin_plugins.race_engineer.context import EngineerContext
from simpulse.builtin_plugins.race_engineer.manager import RaceEngineer
from simpulse.builtin_plugins.race_engineer.subplugins.traffic_spotter import TrafficSpotterRole, TrafficSpotterState
from simpulse.builtin_plugins.race_engineer.subplugins.traffic_jam import TrafficJamRole
from simpulse.builtin_plugins.race_engineer.subplugins.pitlane_spotter import PitlaneSpotterRole, PitlaneSpotterState
from simpulse.builtin_plugins.race_engineer.subplugins.lap_validity import LapValidityRole


class MockAudioEngine:
    def __init__(self):
        self.played = []

    def play_phrase(self, phrase, interrupt=False, priority="NORMAL"):
        self.played.append(phrase)
        return True


def test_engineer_context_session_types():
    """Vérifie la détection précise des types de sessions depuis session."""
    # TestDay
    ctx_test = EngineerContext(scoring=CompactScoring(session=0))
    assert ctx_test.get_session_type() == 0
    assert not ctx_test.is_qualifying_session()
    assert not ctx_test.is_private_qualifying()

    # Practice FP1..FP4
    for s_id in (1, 2, 3, 4):
        ctx_p = EngineerContext(scoring=CompactScoring(session=s_id))
        assert ctx_p.get_session_type() == s_id
        assert not ctx_p.is_qualifying_session()
        assert not ctx_p.is_private_qualifying()

    # Qualifying Q1..Q4 / Hyperpole / Private Qual
    for s_id in (5, 6, 7, 8):
        ctx_q = EngineerContext(scoring=CompactScoring(session=s_id))
        assert ctx_q.get_session_type() == s_id
        assert ctx_q.is_qualifying_session()
        assert ctx_q.is_private_qualifying()

    # Warmup
    ctx_w = EngineerContext(scoring=CompactScoring(session=9))
    assert ctx_w.get_session_type() == 9
    assert not ctx_w.is_qualifying_session()
    assert not ctx_w.is_private_qualifying()

    # Race 1..4
    for s_id in (10, 11, 12, 13):
        ctx_r = EngineerContext(scoring=CompactScoring(session=s_id))
        assert ctx_r.get_session_type() == s_id
        assert not ctx_r.is_qualifying_session()
        assert not ctx_r.is_private_qualifying()

    # None / Empty scoring
    ctx_none = EngineerContext(scoring=None)
    assert ctx_none.get_session_type() == -1
    assert not ctx_none.is_qualifying_session()
    assert not ctx_none.is_private_qualifying()


def test_traffic_spotter_deactivated_in_private_qualifying():
    """Vérifie que TrafficSpotterRole ne déclenche aucune alerte en Private Qualifying."""
    mock_audio = MockAudioEngine()
    spotter = TrafficSpotterRole(audio_engine=mock_audio)

    # Situation critique : Voiture rapide arrivant à 20m derrière avec un gros delta
    # En Practice (session=1) -> Doit déclencher
    p_veh = VehicleScoring(
        id=1, driver_name="Player", is_player=True, control=0,
        lap_dist=1000.0, local_vel=TelemVect3(0.0, 0.0, 40.0), in_garage_stall=False, in_pits=False, finish_status=0,
    )
    opp_veh = VehicleScoring(
        id=2, driver_name="Opponent", is_player=False, control=1,
        lap_dist=980.0, local_vel=TelemVect3(0.0, 0.0, 60.0), in_garage_stall=False, in_pits=False, finish_status=0,
    )
    session_practice = FullScoringSession(
        session=1, lap_dist=5000.0, vehicles=[p_veh, opp_veh],
    )
    ctx_prac = EngineerContext(scoring=session_practice, audio_engine=mock_audio)
    msg_prac = spotter.update(ctx_prac)
    assert msg_prac is not None
    assert spotter.state != TrafficSpotterState.IDLE

    # En Private Qualifying (session=5..8) -> Doit réinitialiser et retourner None
    for qual_session_id in (5, 6, 7, 8):
        spotter.state = TrafficSpotterState.APPROACHING
        session_qual = FullScoringSession(
            session=qual_session_id, lap_dist=5000.0, vehicles=[p_veh, opp_veh],
        )
        ctx_qual = EngineerContext(scoring=session_qual, audio_engine=mock_audio)

        msg_qual = spotter.update(ctx_qual)
        assert msg_qual is None
        assert spotter.state == TrafficSpotterState.IDLE


def test_traffic_jam_deactivated_in_private_qualifying():
    """Vérifie que TrafficJamRole ne déclenche aucune alerte en Private Qualifying."""
    mock_audio = MockAudioEngine()
    jam = TrafficJamRole(audio_engine=mock_audio, slow_speed_threshold_kmh=60.0, warning_distance_m=150.0)

    # Voiture très lente 40m devant
    p_veh = VehicleScoring(
        id=1, driver_name="Player", is_player=True, control=0,
        lap_dist=1000.0, local_vel=TelemVect3(0.0, 0.0, 50.0), in_garage_stall=False, in_pits=False, finish_status=0,
    )
    slow_veh = VehicleScoring(
        id=2, driver_name="Slow Car", is_player=False, control=1,
        lap_dist=1040.0, local_vel=TelemVect3(0.0, 0.0, 5.0), in_garage_stall=False, in_pits=False, finish_status=0,
    )
    session_race = FullScoringSession(
        session=10, lap_dist=5000.0, vehicles=[p_veh, slow_veh],
    )
    ctx_race = EngineerContext(scoring=session_race, audio_engine=mock_audio)
    msg_race = jam.update(ctx_race)
    assert msg_race is not None
    assert jam.is_busy() is True

    # En Private Qualifying (session=5..8) -> Doit ignorer et retourner None
    for qual_session_id in (5, 6, 7, 8):
        session_qual = FullScoringSession(
            session=qual_session_id, lap_dist=5000.0, vehicles=[p_veh, slow_veh],
        )
        ctx_qual = EngineerContext(scoring=session_qual, audio_engine=mock_audio)

        msg_qual = jam.update(ctx_qual)
        assert msg_qual is None
        assert jam.is_busy() is False


def test_pitlane_spotter_deactivated_in_private_qualifying():
    """Vérifie que PitlaneSpotterRole ne déclenche pas d'alerte unsafe release en Private Qualifying."""
    mock_audio = MockAudioEngine()
    pit_spotter = PitlaneSpotterRole(audio_engine=mock_audio)

    # Joueur dans son box, voiture arrivant à fond dans la pitlane derrière
    p_veh = VehicleScoring(
        id=1, driver_name="Player", is_player=True, control=0,
        lap_dist=4900.0, local_vel=TelemVect3(0.0, 0.0, 0.0), in_garage_stall=True, in_pits=True, finish_status=0,
        pos=TelemVect3(10.0, 0.0, 4900.0),
    )
    opp_veh = VehicleScoring(
        id=2, driver_name="Fast Pit Car", is_player=False, control=1,
        lap_dist=4885.0, local_vel=TelemVect3(0.0, 0.0, 16.0), in_garage_stall=False, in_pits=True, finish_status=0,
        pos=TelemVect3(10.0, 0.0, 4885.0),
    )
    session_practice = FullScoringSession(
        session=2, lap_dist=5000.0, vehicles=[p_veh, opp_veh],
    )
    ctx_prac = EngineerContext(scoring=session_practice, audio_engine=mock_audio)
    msg_prac = pit_spotter.update(ctx_prac)
    assert msg_prac is not None
    assert pit_spotter.state == PitlaneSpotterState.UNSAFE_HAZARD

    # En Private Qualifying (session=5) -> Doit réinitialiser et retourner None
    session_qual = FullScoringSession(
        session=5, lap_dist=5000.0, vehicles=[p_veh, opp_veh],
    )
    ctx_qual = EngineerContext(scoring=session_qual, audio_engine=mock_audio)

    msg_qual = pit_spotter.update(ctx_qual)
    assert msg_qual is None
    assert pit_spotter.state == PitlaneSpotterState.IDLE


def test_race_engineer_manager_in_qualifying():
    """Vérifie que le coordinateur global RaceEngineer désactive les 3 rôles de trafic en qualif mais garde LapValidity."""
    mock_audio = MockAudioEngine()
    engineer = RaceEngineer(audio_engine=mock_audio, auto_load_builtin_roles=True, auto_load_config=False)

    # 1. Premier cycle avec tour valide (count_lap_flag = 2) pour initialiser le rôle
    p_clean = VehicleScoring(
        id=1, driver_name="Player", is_player=True, control=0,
        lap_dist=1000.0, local_vel=TelemVect3(0.0, 0.0, 40.0), in_garage_stall=False, in_pits=False, finish_status=0,
        count_lap_flag=2,
    )
    scoring_qual_clean = FullScoringSession(
        session=5, lap_dist=5000.0, vehicles=[p_clean],
    )
    engineer.update(telemetry=None, scoring=scoring_qual_clean)

    # 2. Deuxième cycle : tour invalidé (count_lap_flag = 0) + menaces trafic en qualif
    p_invalid = VehicleScoring(
        id=1, driver_name="Player", is_player=True, control=0,
        lap_dist=1000.0, local_vel=TelemVect3(0.0, 0.0, 40.0), in_garage_stall=False, in_pits=False, finish_status=0,
        count_lap_flag=0,  # Tour invalidé
    )
    opp_behind = VehicleScoring(
        id=2, driver_name="Ghost Behind", is_player=False, control=1,
        lap_dist=980.0, local_vel=TelemVect3(0.0, 0.0, 60.0), in_garage_stall=False, in_pits=False, finish_status=0,
    )
    opp_ahead = VehicleScoring(
        id=3, driver_name="Ghost Ahead", is_player=False, control=1,
        lap_dist=1030.0, local_vel=TelemVect3(0.0, 0.0, 5.0), in_garage_stall=False, in_pits=False, finish_status=0,
    )
    scoring_qual_invalid = FullScoringSession(
        session=5, lap_dist=5000.0, vehicles=[p_invalid, opp_behind, opp_ahead],
    )

    messages = engineer.update(telemetry=None, scoring=scoring_qual_invalid)

    # Seul le message d'invalidation de tour doit être émis, aucun message de trafic
    phrase_keys = [m.phrase_key for m in messages]
    assert any(k in phrase_keys for k in ("time_deleted", "lap_deleted"))
    assert "car" not in phrase_keys
    assert "alongside" not in phrase_keys
    assert "three" not in phrase_keys
    assert "brake" not in phrase_keys
