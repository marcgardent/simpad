"""
Tests unitaires complets pour TrafficSpotterRole (Machine à états TTC, Countdown, Overlap, Clear).
"""

import pytest
from src.engineer.context import EngineerContext
from src.engineer.roles.traffic_spotter import TrafficSpotterRole, TrafficSpotterState
from src.engineer.base import RoleStatus
from src.telemetry.lmu_parser import TelemetryData


def make_scoring_packet(player_dist, player_speed_mps, opp_dist, opp_speed_mps, track_len=5000.0, opp_id=2):
    """Helper pour construire un paquet de scoring LMU réaliste."""
    return {
        "Type": "ScoringInfoV01",
        "mLapDist": track_len,
        "mVehicles": [
            {
                "mID": 1,
                "mDriverName": "Player Driver",
                "mVehicleName": "Ferrari 499P #50",
                "mIsPlayer": True,
                "mControl": 0,
                "mLapDist": player_dist,
                "mLocalVel": [0.0, 0.0, player_speed_mps],
                "mInGarageStall": False,
                "mInPits": False,
                "mFinishStatus": 0,
            },
            {
                "mID": opp_id,
                "mDriverName": "Ian James",
                "mVehicleName": "Aston Martin Vantage #27",
                "mIsPlayer": False,
                "mControl": 1,
                "mLapDist": opp_dist,
                "mLocalVel": [0.0, 0.0, opp_speed_mps],
                "mInGarageStall": False,
                "mInPits": False,
                "mFinishStatus": 0,
            }
        ]
    }


def test_distance_behind_calculation_with_wraparound():
    """Vérifie le calcul correct de distance relative avec passage de ligne de départ/arrivée."""
    ctx = EngineerContext(scoring={"mLapDist": 5000.0})
    p_veh = {"mLapDist": 100.0}
    o_veh = {"mLapDist": 80.0}

    # Adversaire 20m derrière
    dist = ctx.compute_distance_behind(p_veh, o_veh, 5000.0)
    assert dist == pytest.approx(20.0, 0.01)

    # Rebouclage : Joueur à 20m, adversaire à 4980m (donc 40m derrière le joueur)
    p_veh2 = {"mLapDist": 20.0}
    o_veh2 = {"mLapDist": 4980.0}
    dist2 = ctx.compute_distance_behind(p_veh2, o_veh2, 5000.0)
    assert dist2 == pytest.approx(40.0, 0.01)

    # Adversaire 30m devant
    p_veh3 = {"mLapDist": 100.0}
    o_veh3 = {"mLapDist": 130.0}
    dist3 = ctx.compute_distance_behind(p_veh3, o_veh3, 5000.0)
    assert dist3 == pytest.approx(-30.0, 0.01)


def test_traffic_spotter_full_fsm_lifecycle():
    """
    Vérifie le cycle complet de la FSM :
    IDLE -> APPROACHING ("incoming") -> COUNTDOWN ("three", "two", "one") -> OVERLAP ("alongside") -> CLEAR ("clear") -> IDLE.
    """
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = TrafficSpotterRole(
        audio_engine=mock_audio,
        ttc_trigger_sec=5.0,
        speed_delta_min_kmh=20.0,  # 5.55 m/s
        overlap_dist_threshold_m=4.0,
        clear_dist_threshold_m=10.0,
        phrase_mode="alongside",
    )

    # Initialement IDLE
    assert role.state == TrafficSpotterState.IDLE
    assert not role.is_busy()

    # 1. Joueur à 50 m/s (180 km/h), adversaire à 60 m/s (216 km/h) -> delta = 10 m/s (36 km/h > 20 km/h)
    # Distance behind = 45m -> TTC = 45 / 10 = 4.5s (<= 5.0s)
    # Déclenchement : IDLE -> APPROACHING ("incoming")
    sc1 = make_scoring_packet(player_dist=500.0, player_speed_mps=50.0, opp_dist=455.0, opp_speed_mps=60.0)
    msg1 = role.update(EngineerContext(scoring=sc1))

    assert msg1 is not None
    assert msg1.phrase_key == "incoming"
    assert role.state == TrafficSpotterState.APPROACHING
    assert role.is_busy()
    assert ("incoming", False) in played

    # 2. Rapprochement : Distance behind = 28m -> TTC = 2.8s (<= 3.0s)
    # Déclenchement : COUNTDOWN ("three")
    sc2 = make_scoring_packet(player_dist=600.0, player_speed_mps=50.0, opp_dist=572.0, opp_speed_mps=60.0)
    msg2 = role.update(EngineerContext(scoring=sc2))

    assert msg2 is not None
    assert msg2.phrase_key == "three"
    assert role.state == TrafficSpotterState.COUNTDOWN
    assert role.last_announced_sec == 3

    # 3. Rapprochement : Distance behind = 19m -> TTC = 1.9s (<= 2.0s)
    # Déclenchement : COUNTDOWN ("two")
    sc3 = make_scoring_packet(player_dist=700.0, player_speed_mps=50.0, opp_dist=681.0, opp_speed_mps=60.0)
    msg3 = role.update(EngineerContext(scoring=sc3))

    assert msg3 is not None
    assert msg3.phrase_key == "two"
    assert role.last_announced_sec == 2

    # 4. Rapprochement : Distance behind = 9m -> TTC = 0.9s (<= 1.0s)
    # Déclenchement : COUNTDOWN ("one")
    sc4 = make_scoring_packet(player_dist=800.0, player_speed_mps=50.0, opp_dist=791.0, opp_speed_mps=60.0)
    msg4 = role.update(EngineerContext(scoring=sc4))

    assert msg4 is not None
    assert msg4.phrase_key == "one"
    assert role.last_announced_sec == 1

    # 5. Overlap : Distance behind = 0.5m (bord à bord)
    # Déclenchement : OVERLAP ("alongside" avec interrupt=True)
    sc5 = make_scoring_packet(player_dist=900.0, player_speed_mps=50.0, opp_dist=899.5, opp_speed_mps=60.0)
    msg5 = role.update(EngineerContext(scoring=sc5))

    assert msg5 is not None
    assert msg5.phrase_key == "alongside"
    assert msg5.interrupt is True
    assert role.state == TrafficSpotterState.OVERLAP
    assert ("alongside", True) in played

    # 6. Dépassement terminé : Adversaire passé devant, distance = -12m (12m devant)
    # Déclenchement : CLEAR ("clear" avec interrupt=True)
    sc6 = make_scoring_packet(player_dist=1000.0, player_speed_mps=50.0, opp_dist=1012.0, opp_speed_mps=60.0)
    msg6 = role.update(EngineerContext(scoring=sc6))

    assert msg6 is not None
    assert msg6.phrase_key == "clear"
    assert msg6.interrupt is True
    assert role.state == TrafficSpotterState.CLEAR
    assert ("clear", True) in played

    # 7. Tick suivant -> Retour immédiat à IDLE
    sc7 = make_scoring_packet(player_dist=1100.0, player_speed_mps=50.0, opp_dist=1140.0, opp_speed_mps=60.0)
    msg7 = role.update(EngineerContext(scoring=sc7))
    assert msg7 is None
    assert role.state == TrafficSpotterState.IDLE
    assert not role.is_busy()


def test_traffic_spotter_abort_on_slowdown():
    """Vérifie que la FSM annule l'approche sans spam si l'adversaire ralentit (TTC > 6s)."""
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = TrafficSpotterRole(audio_engine=mock_audio)

    # 1. Déclenchement approche (delta = 10 m/s, dist = 40m -> TTC = 4.0s)
    sc1 = make_scoring_packet(player_dist=500.0, player_speed_mps=50.0, opp_dist=460.0, opp_speed_mps=60.0)
    role.update(EngineerContext(scoring=sc1))
    assert role.state == TrafficSpotterState.APPROACHING

    # 2. L'adversaire freine fort : vitesse adverse = 52 m/s (delta = 2 m/s), dist = 35m -> TTC = 17.5s (> 6s)
    sc2 = make_scoring_packet(player_dist=600.0, player_speed_mps=50.0, opp_dist=565.0, opp_speed_mps=52.0)
    msg2 = role.update(EngineerContext(scoring=sc2))

    # Doit revenir à IDLE silencieusement sans spam
    assert msg2 is None
    assert role.state == TrafficSpotterState.IDLE
    assert not role.is_busy()


def test_traffic_spotter_multi_car_chaining():
    """Vérifie que si une 2e voiture colle la 1ère lors du dépassement, l'ingénieur ne dit pas Clear et suit la 2e."""
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = TrafficSpotterRole(audio_engine=mock_audio)

    # Paquet avec 2 adversaires
    scoring_multi = {
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
            # Voiture 1 : Overlap (0.5m derrière)
            {
                "mID": 2,
                "mDriverName": "Car 1",
                "mIsPlayer": False,
                "mControl": 1,
                "mLapDist": 999.5,
                "mLocalVel": [0.0, 0.0, 60.0],
                "mFinishStatus": 0,
            },
            # Voiture 2 : Juste derrière la 1ère (20m derrière le joueur à +10 m/s -> TTC = 2s)
            {
                "mID": 3,
                "mDriverName": "Car 2",
                "mIsPlayer": False,
                "mControl": 1,
                "mLapDist": 980.0,
                "mLocalVel": [0.0, 0.0, 60.0],
                "mFinishStatus": 0,
            }
        ]
    }

    # 1. Initie le suivi sur Voiture 1
    role.update(EngineerContext(scoring=scoring_multi))
    assert role.state in (TrafficSpotterState.APPROACHING, TrafficSpotterState.OVERLAP)
    role.state = TrafficSpotterState.OVERLAP
    role.target_vehicle_id = 2

    # 2. Voiture 1 passe devant (15m devant), mais Voiture 2 est à 15m derrière avec TTC = 1.5s
    scoring_multi_pass = {
        "Type": "ScoringInfoV01",
        "mLapDist": 5000.0,
        "mVehicles": [
            {
                "mID": 1,
                "mIsPlayer": True,
                "mControl": 0,
                "mLapDist": 1050.0,
                "mLocalVel": [0.0, 0.0, 50.0],
                "mFinishStatus": 0,
            },
            # Voiture 1 : 15m devant
            {
                "mID": 2,
                "mDriverName": "Car 1",
                "mIsPlayer": False,
                "mControl": 1,
                "mLapDist": 1065.0,
                "mLocalVel": [0.0, 0.0, 60.0],
                "mFinishStatus": 0,
            },
            # Voiture 2 : 15m derrière à 60 m/s (TTC = 1.5s)
            {
                "mID": 3,
                "mDriverName": "Car 2",
                "mIsPlayer": False,
                "mControl": 1,
                "mLapDist": 1035.0,
                "mLocalVel": [0.0, 0.0, 60.0],
                "mFinishStatus": 0,
            }
        ]
    }

    msg = role.update(EngineerContext(scoring=scoring_multi_pass))
    # Ne doit PAS avoir dit clear, mais avoir basculé sur la Voiture 2 !
    assert msg is None or msg.phrase_key != "clear"
    assert role.target_vehicle_id == 3
    assert role.state == TrafficSpotterState.APPROACHING


def test_traffic_spotter_ignores_pit_lane_opponents():
    """Vérifie que les adversaires dans la pitlane (mInPits=True) sont ignorés par le spotter en piste."""
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = TrafficSpotterRole(audio_engine=mock_audio)

    # Adversaire rapide juste derrière le joueur, mais dans la pitlane (mInPits=True)
    scoring_pit_opp = {
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
            {
                "mID": 2,
                "mDriverName": "Pit Lane Car",
                "mIsPlayer": False,
                "mControl": 1,
                "mLapDist": 970.0,
                "mLocalVel": [0.0, 0.0, 60.0],  # Vitesse plus rapide mais en pitlane
                "mInPits": True,
                "mInGarageStall": False,
                "mFinishStatus": 0,
            }
        ]
    }

    msg = role.update(EngineerContext(scoring=scoring_pit_opp))
    assert msg is None
    assert role.state == TrafficSpotterState.IDLE
    assert not role.is_busy()
    assert len(played) == 0


def test_traffic_spotter_deactivated_when_player_in_pits():
    """Vérifie que le spotter est inactif lorsque le joueur est dans la pitlane ou au garage."""
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = TrafficSpotterRole(audio_engine=mock_audio)

    # Joueur dans les stands (mInPits=True), une voiture arrive très vite sur la ligne droite des stands
    scoring_player_in_pits = {
        "Type": "ScoringInfoV01",
        "mLapDist": 5000.0,
        "mVehicles": [
            {
                "mID": 1,
                "mIsPlayer": True,
                "mControl": 0,
                "mLapDist": 1000.0,
                "mLocalVel": [0.0, 0.0, 16.0],  # 60 km/h en pitlane
                "mInPits": True,
                "mInGarageStall": False,
                "mFinishStatus": 0,
            },
            {
                "mID": 2,
                "mDriverName": "Track Car",
                "mIsPlayer": False,
                "mControl": 1,
                "mLapDist": 960.0,
                "mLocalVel": [0.0, 0.0, 70.0],  # 250 km/h sur piste
                "mInPits": False,
                "mInGarageStall": False,
                "mFinishStatus": 0,
            }
        ]
    }

    msg = role.update(EngineerContext(scoring=scoring_player_in_pits))
    assert msg is None
    assert role.state == TrafficSpotterState.IDLE
    assert not role.is_busy()
    assert len(played) == 0


def test_traffic_spotter_tracked_car_enters_pits_aborts():
    """Vérifie que si la voiture suivie rentre aux stands (mInPits devient True), le spotter lâche la cible proprement."""
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = TrafficSpotterRole(audio_engine=mock_audio)

    # 1. Approche en piste
    sc1 = make_scoring_packet(player_dist=500.0, player_speed_mps=50.0, opp_dist=460.0, opp_speed_mps=60.0)
    role.update(EngineerContext(scoring=sc1))
    assert role.state == TrafficSpotterState.APPROACHING
    assert role.target_vehicle_id == 2

    # 2. La voiture suivie prend la voie des stands (mInPits=True)
    sc2 = make_scoring_packet(player_dist=550.0, player_speed_mps=50.0, opp_dist=530.0, opp_speed_mps=30.0)
    sc2["mVehicles"][1]["mInPits"] = True

    msg = role.update(EngineerContext(scoring=sc2))
    assert msg is None
    assert role.state == TrafficSpotterState.IDLE
    assert role.target_vehicle_id is None
