"""
Tests unitaires pour TrafficJamRole (Véhicules lents / drapeaux jaunes devant).
"""

import pytest
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
    scoring_clear = {
        "Type": "ScoringInfoV01",
        "mLapDist": 5000.0,
        "mVehicles": [
            {
                "mID": 1,
                "mIsPlayer": True,
                "mControl": 0,
                "mLapDist": 1000.0,
                "mLocalVel": [0.0, 0.0, 50.0],
                "mFinishStatus": 0,
            },
            # Adversaire 80m devant, roulant à 55 m/s (> 50 km/h)
            {
                "mID": 2,
                "mDriverName": "Fast Car Ahead",
                "mIsPlayer": False,
                "mControl": 1,
                "mLapDist": 1080.0,
                "mLocalVel": [0.0, 0.0, 55.0],
                "mFinishStatus": 0,
            }
        ]
    }

    msg1 = role.update(EngineerContext(scoring=scoring_clear))
    assert msg1 is None
    assert not role.is_busy()

    # 2. Voiture au ralenti ou accidentée devant (80m devant, vitesse = 5 m/s = 18 km/h < 50 km/h)
    scoring_slow = {
        "Type": "ScoringInfoV01",
        "mLapDist": 5000.0,
        "mVehicles": [
            {
                "mID": 1,
                "mIsPlayer": True,
                "mControl": 0,
                "mLapDist": 1000.0,
                "mLocalVel": [0.0, 0.0, 50.0],
                "mFinishStatus": 0,
            },
            {
                "mID": 2,
                "mDriverName": "Slow Car Ahead",
                "mIsPlayer": False,
                "mControl": 1,
                "mLapDist": 1080.0,
                "mLocalVel": [0.0, 0.0, 5.0],
                "mFinishStatus": 0,
            }
        ]
    }

    msg2 = role.update(EngineerContext(scoring=scoring_slow))
    assert msg2 is not None
    assert msg2.phrase_key == "car"
    assert role.is_busy()
    assert ("car", False) in played


def test_traffic_jam_ignores_pit_lane_cars():
    """Vérifie qu'une voiture lente dans la voie des stands (mInPits=True) ne déclenche pas d'alerte pour le joueur en piste."""
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = TrafficJamRole(
        audio_engine=mock_audio,
        slow_speed_threshold_kmh=50.0,
        warning_distance_m=150.0,
    )

    scoring_pit_slow = {
        "Type": "ScoringInfoV01",
        "mLapDist": 5000.0,
        "mVehicles": [
            {
                "mID": 1,
                "mIsPlayer": True,
                "mControl": 0,
                "mLapDist": 1000.0,
                "mLocalVel": [0.0, 0.0, 50.0],
                "mInPits": False,
                "mInGarageStall": False,
                "mFinishStatus": 0,
            },
            # Voiture à 30 km/h mais dans la pitlane (mInPits=True)
            {
                "mID": 2,
                "mDriverName": "Pit Lane Car",
                "mIsPlayer": False,
                "mControl": 1,
                "mLapDist": 1080.0,
                "mLocalVel": [0.0, 0.0, 8.0],  # ~29 km/h
                "mInPits": True,
                "mInGarageStall": False,
                "mFinishStatus": 0,
            }
        ]
    }

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

    scoring_player_in_pits = {
        "Type": "ScoringInfoV01",
        "mLapDist": 5000.0,
        "mVehicles": [
            {
                "mID": 1,
                "mIsPlayer": True,
                "mControl": 0,
                "mLapDist": 1000.0,
                "mLocalVel": [0.0, 0.0, 16.0],
                "mInPits": True,
                "mInGarageStall": False,
                "mFinishStatus": 0,
            },
            {
                "mID": 2,
                "mDriverName": "Slow Track Car",
                "mIsPlayer": False,
                "mControl": 1,
                "mLapDist": 1080.0,
                "mLocalVel": [0.0, 0.0, 5.0],
                "mInPits": False,
                "mInGarageStall": False,
                "mFinishStatus": 0,
            }
        ]
    }

    msg = role.update(EngineerContext(scoring=scoring_player_in_pits))
    assert msg is None
    assert not role.is_busy()
    assert len(played) == 0
