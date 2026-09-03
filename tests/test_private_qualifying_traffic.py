"""
Tests unitaires pour la détection du Private Qualifying et la désactivation des 3 rôles Trafic.
Vérifie que TrafficSpotterRole, TrafficJamRole et PitlaneSpotterRole restent totalement silencieux
lorsque la session est une qualification (mSession entre 5 et 8 inclus), conformément au protocole LMU.
"""

import pytest
from src.engineer.context import EngineerContext
from src.engineer.manager import RaceEngineer
from src.engineer.roles.traffic_spotter import TrafficSpotterRole, TrafficSpotterState
from src.engineer.roles.traffic_jam import TrafficJamRole
from src.engineer.roles.pitlane_spotter import PitlaneSpotterRole, PitlaneSpotterState
from src.engineer.roles.lap_validity import LapValidityRole
from src.telemetry.lmu_parser import TelemetryData


class MockAudioEngine:
    def __init__(self):
        self.played = []

    def play_phrase(self, phrase, interrupt=False, priority="NORMAL"):
        self.played.append(phrase)
        return True


def test_engineer_context_session_types():
    """Vérifie la détection précise des types de sessions depuis mSession."""
    # TestDay
    ctx_test = EngineerContext(scoring={"mSession": 0})
    assert ctx_test.get_session_type() == 0
    assert not ctx_test.is_qualifying_session()
    assert not ctx_test.is_private_qualifying()

    # Practice FP1..FP4
    for s_id in (1, 2, 3, 4):
        ctx_p = EngineerContext(scoring={"mSession": s_id})
        assert ctx_p.get_session_type() == s_id
        assert not ctx_p.is_qualifying_session()
        assert not ctx_p.is_private_qualifying()

    # Qualifying Q1..Q4 / Hyperpole / Private Qual
    for s_id in (5, 6, 7, 8):
        ctx_q = EngineerContext(scoring={"mSession": s_id})
        assert ctx_q.get_session_type() == s_id
        assert ctx_q.is_qualifying_session()
        assert ctx_q.is_private_qualifying()

    # Warmup
    ctx_w = EngineerContext(scoring={"mSession": 9})
    assert ctx_w.get_session_type() == 9
    assert not ctx_w.is_qualifying_session()
    assert not ctx_w.is_private_qualifying()

    # Race 1..4
    for s_id in (10, 11, 12, 13):
        ctx_r = EngineerContext(scoring={"mSession": s_id})
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
    # En Practice (mSession=1) -> Doit déclencher
    scoring_practice = {
        "mSession": 1,
        "mLapDist": 5000.0,
        "mVehicles": [
            {
                "mID": 1, "mDriverName": "Player", "mIsPlayer": True, "mControl": 0,
                "mLapDist": 1000.0, "mLocalVel": [0.0, 0.0, 40.0],
                "mInGarageStall": False, "mInPits": False, "mFinishStatus": 0,
            },
            {
                "mID": 2, "mDriverName": "Opponent", "mIsPlayer": False, "mControl": 1,
                "mLapDist": 980.0, "mLocalVel": [0.0, 0.0, 60.0],  # +20 m/s delta, dist=20m, TTC=1s
                "mInGarageStall": False, "mInPits": False, "mFinishStatus": 0,
            },
        ],
    }
    ctx_prac = EngineerContext(scoring=scoring_practice, audio_engine=mock_audio)
    msg_prac = spotter.update(ctx_prac)
    assert msg_prac is not None
    assert spotter.state != TrafficSpotterState.IDLE

    # En Private Qualifying (mSession=5..8) -> Doit réinitialiser et retourner None
    for qual_session_id in (5, 6, 7, 8):
        spotter.state = TrafficSpotterState.APPROACHING
        scoring_qual = dict(scoring_practice)
        scoring_qual["mSession"] = qual_session_id
        ctx_qual = EngineerContext(scoring=scoring_qual, audio_engine=mock_audio)

        msg_qual = spotter.update(ctx_qual)
        assert msg_qual is None
        assert spotter.state == TrafficSpotterState.IDLE


def test_traffic_jam_deactivated_in_private_qualifying():
    """Vérifie que TrafficJamRole ne déclenche aucune alerte en Private Qualifying."""
    mock_audio = MockAudioEngine()
    jam = TrafficJamRole(audio_engine=mock_audio, slow_speed_threshold_kmh=60.0, warning_distance_m=150.0)

    # Voiture très lente 40m devant
    scoring_race = {
        "mSession": 10,
        "mLapDist": 5000.0,
        "mVehicles": [
            {
                "mID": 1, "mDriverName": "Player", "mIsPlayer": True, "mControl": 0,
                "mLapDist": 1000.0, "mLocalVel": [0.0, 0.0, 50.0],
                "mInGarageStall": False, "mInPits": False, "mFinishStatus": 0,
            },
            {
                "mID": 2, "mDriverName": "Slow Car", "mIsPlayer": False, "mControl": 1,
                "mLapDist": 1040.0, "mLocalVel": [0.0, 0.0, 5.0],  # Seulement 5 m/s (~18 km/h)
                "mInGarageStall": False, "mInPits": False, "mFinishStatus": 0,
            },
        ],
    }
    ctx_race = EngineerContext(scoring=scoring_race, audio_engine=mock_audio)
    msg_race = jam.update(ctx_race)
    assert msg_race is not None
    assert jam.is_busy() is True

    # En Private Qualifying (mSession=5..8) -> Doit ignorer et retourner None
    for qual_session_id in (5, 6, 7, 8):
        scoring_qual = dict(scoring_race)
        scoring_qual["mSession"] = qual_session_id
        ctx_qual = EngineerContext(scoring=scoring_qual, audio_engine=mock_audio)

        msg_qual = jam.update(ctx_qual)
        assert msg_qual is None
        assert jam.is_busy() is False


def test_pitlane_spotter_deactivated_in_private_qualifying():
    """Vérifie que PitlaneSpotterRole ne déclenche pas d'alerte unsafe release en Private Qualifying."""
    mock_audio = MockAudioEngine()
    pit_spotter = PitlaneSpotterRole(audio_engine=mock_audio)

    # Joueur dans son box, voiture arrivant à fond dans la pitlane derrière
    scoring_practice = {
        "mSession": 2,
        "mLapDist": 5000.0,
        "mVehicles": [
            {
                "mID": 1, "mDriverName": "Player", "mIsPlayer": True, "mControl": 0,
                "mLapDist": 4900.0, "mLocalVel": [0.0, 0.0, 0.0],
                "mInGarageStall": True, "mInPits": True, "mFinishStatus": 0,
            },
            {
                "mID": 2, "mDriverName": "Fast Pit Car", "mIsPlayer": False, "mControl": 1,
                "mLapDist": 4885.0, "mLocalVel": [0.0, 0.0, 16.0],  # 60 km/h dans la pitlane, 15m derrière
                "mInGarageStall": False, "mInPits": True, "mFinishStatus": 0,
            },
        ],
    }
    ctx_prac = EngineerContext(scoring=scoring_practice, audio_engine=mock_audio)
    msg_prac = pit_spotter.update(ctx_prac)
    assert msg_prac is not None
    assert pit_spotter.state == PitlaneSpotterState.UNSAFE_HAZARD

    # En Private Qualifying (mSession=5) -> Doit réinitialiser et retourner None
    scoring_qual = dict(scoring_practice)
    scoring_qual["mSession"] = 5
    ctx_qual = EngineerContext(scoring=scoring_qual, audio_engine=mock_audio)

    msg_qual = pit_spotter.update(ctx_qual)
    assert msg_qual is None
    assert pit_spotter.state == PitlaneSpotterState.IDLE


def test_race_engineer_manager_in_qualifying():
    """Vérifie que le coordinateur global RaceEngineer désactive les 3 rôles de trafic en qualif mais garde LapValidity."""
    mock_audio = MockAudioEngine()
    engineer = RaceEngineer(audio_engine=mock_audio, auto_load_builtin_roles=True, auto_load_config=False)

    # 1. Premier cycle avec tour valide (lap_flag = 2) pour initialiser le rôle
    scoring_qual_clean = {
        "mSession": 5,
        "mLapDist": 5000.0,
        "mVehicles": [
            {
                "mID": 1, "mDriverName": "Player", "mIsPlayer": True, "mControl": 0,
                "mLapDist": 1000.0, "mLocalVel": [0.0, 0.0, 40.0],
                "mInGarageStall": False, "mInPits": False, "mFinishStatus": 0,
                "mCountLapFlag": 2,
            },
        ],
    }
    telem_clean = TelemetryData(in_realtime=True, lap_flag=2)
    engineer.update(telemetry=telem_clean, scoring=scoring_qual_clean)

    # 2. Deuxième cycle : tour invalidé (lap_flag = 0) + menaces trafic en qualif
    scoring_qual_dirty = {
        "mSession": 5,
        "mLapDist": 5000.0,
        "mVehicles": [
            {
                "mID": 1, "mDriverName": "Player", "mIsPlayer": True, "mControl": 0,
                "mLapDist": 1000.0, "mLocalVel": [0.0, 0.0, 40.0],
                "mInGarageStall": False, "mInPits": False, "mFinishStatus": 0,
                "mCountLapFlag": 0,  # Tour invalidé
            },
            {
                "mID": 2, "mDriverName": "Ghost Behind", "mIsPlayer": False, "mControl": 1,
                "mLapDist": 980.0, "mLocalVel": [0.0, 0.0, 60.0],
                "mInGarageStall": False, "mInPits": False, "mFinishStatus": 0,
            },
            {
                "mID": 3, "mDriverName": "Ghost Ahead", "mIsPlayer": False, "mControl": 1,
                "mLapDist": 1030.0, "mLocalVel": [0.0, 0.0, 5.0],
                "mInGarageStall": False, "mInPits": False, "mFinishStatus": 0,
            },
        ],
    }

    telem_dirty = TelemetryData(in_realtime=True, lap_flag=0)
    messages = engineer.update(telemetry=telem_dirty, scoring=scoring_qual_dirty)

    # Seul le message d'invalidation de tour doit être émis, aucun message de trafic
    phrase_keys = [m.phrase_key for m in messages]
    assert any(k in phrase_keys for k in ("dirty_lap", "lap_deleted"))
    assert "car" not in phrase_keys
    assert "alongside" not in phrase_keys
    assert "three" not in phrase_keys
    assert "brake" not in phrase_keys
