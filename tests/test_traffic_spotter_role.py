"""
Tests unitaires complets pour TrafficSpotterRole (Machine à états TTC, Countdown, Overlap, Clear).
"""

import pytest
from simpad_qt.core.engineer.context import EngineerContext
from simpad_qt.core.engineer.roles.traffic_spotter import TrafficSpotterRole, TrafficSpotterState
from simpad_qt.core.engineer.base import RoleStatus
from simpad_qt.core.telemetry.lmu_parser import TelemetryData


from isimotor_rawudp_client import FullScoringSession, VehicleScoring, TelemVect3


def make_scoring_packet(player_dist, player_speed_mps, opp_dist, opp_speed_mps, track_len=5000.0, opp_id=2):
    """Helper pour construire un paquet de scoring LMU réaliste."""
    p_veh = VehicleScoring(
        id=1,
        driver_name="Player Driver",
        vehicle_name="Ferrari 499P #50",
        is_player=True,
        control=0,
        lap_dist=float(player_dist),
        local_vel=TelemVect3(0.0, 0.0, float(player_speed_mps)),
        in_garage_stall=False,
        in_pits=False,
        finish_status=0,
    )
    opp = VehicleScoring(
        id=opp_id,
        driver_name="Ian James",
        vehicle_name="Aston Martin Vantage #27",
        is_player=False,
        control=1,
        lap_dist=float(opp_dist),
        local_vel=TelemVect3(0.0, 0.0, float(opp_speed_mps)),
        in_garage_stall=False,
        in_pits=False,
        finish_status=0,
    )
    return FullScoringSession(
        session=10,
        track_name="Test Track",
        lap_dist=float(track_len),
        vehicles=[p_veh, opp],
    )


def test_distance_behind_calculation_with_wraparound():
    """Vérifie le calcul correct de distance relative avec passage de ligne de départ/arrivée."""
    ctx = EngineerContext(scoring=FullScoringSession(lap_dist=5000.0))
    p_veh = VehicleScoring(lap_dist=100.0)
    o_veh = VehicleScoring(lap_dist=80.0)

    # Adversaire 20m derrière
    dist = ctx.compute_distance_behind(p_veh, o_veh, 5000.0)
    assert dist == pytest.approx(20.0, 0.01)

    # Rebouclage : Joueur à 20m, adversaire à 4980m (donc 40m derrière le joueur)
    p_veh2 = VehicleScoring(lap_dist=20.0)
    o_veh2 = VehicleScoring(lap_dist=4980.0)
    dist2 = ctx.compute_distance_behind(p_veh2, o_veh2, 5000.0)
    assert dist2 == pytest.approx(40.0, 0.01)

    # Adversaire 30m devant
    p_veh3 = VehicleScoring(lap_dist=100.0)
    o_veh3 = VehicleScoring(lap_dist=130.0)
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
    scoring_multi = FullScoringSession(
        session=10,
        lap_dist=5000.0,
        vehicles=[
            VehicleScoring(
                id=1, is_player=True, control=0, lap_dist=1000.0,
                local_vel=TelemVect3(0.0, 0.0, 50.0), finish_status=0,
            ),
            # Voiture 1 : Overlap (0.5m derrière)
            VehicleScoring(
                id=2, driver_name="Car 1", is_player=False, control=1, lap_dist=999.5,
                local_vel=TelemVect3(0.0, 0.0, 60.0), finish_status=0,
            ),
            # Voiture 2 : Juste derrière la 1ère (20m derrière le joueur à +10 m/s -> TTC = 2s)
            VehicleScoring(
                id=3, driver_name="Car 2", is_player=False, control=1, lap_dist=980.0,
                local_vel=TelemVect3(0.0, 0.0, 60.0), finish_status=0,
            ),
        ],
    )

    # 1. Initie le suivi sur Voiture 1
    role.update(EngineerContext(scoring=scoring_multi))
    assert role.state in (TrafficSpotterState.APPROACHING, TrafficSpotterState.OVERLAP)
    role.state = TrafficSpotterState.OVERLAP
    role.target_vehicle_id = 2

    # 2. Voiture 1 passe devant (15m devant), mais Voiture 2 est à 15m derrière avec TTC = 1.5s
    scoring_multi_pass = FullScoringSession(
        session=10,
        lap_dist=5000.0,
        vehicles=[
            VehicleScoring(
                id=1, is_player=True, control=0, lap_dist=1050.0,
                local_vel=TelemVect3(0.0, 0.0, 50.0), finish_status=0,
            ),
            # Voiture 1 : 15m devant
            VehicleScoring(
                id=2, driver_name="Car 1", is_player=False, control=1, lap_dist=1065.0,
                local_vel=TelemVect3(0.0, 0.0, 60.0), finish_status=0,
            ),
            # Voiture 2 : 15m derrière à 60 m/s (TTC = 1.5s)
            VehicleScoring(
                id=3, driver_name="Car 2", is_player=False, control=1, lap_dist=1035.0,
                local_vel=TelemVect3(0.0, 0.0, 60.0), finish_status=0,
            ),
        ],
    )

    msg = role.update(EngineerContext(scoring=scoring_multi_pass))
    # Ne doit PAS avoir dit clear, mais avoir basculé sur la Voiture 2 !
    assert msg is None or msg.phrase_key != "clear"
    assert role.target_vehicle_id == 3
    assert role.state == TrafficSpotterState.APPROACHING


def test_traffic_spotter_ignores_pit_lane_opponents():
    """Vérifie que les adversaires dans la pitlane (in_pits=True) sont ignorés par le spotter en piste."""
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = TrafficSpotterRole(audio_engine=mock_audio)

    # Adversaire rapide juste derrière le joueur, mais dans la pitlane (in_pits=True)
    scoring_pit_opp = FullScoringSession(
        session=10,
        lap_dist=5000.0,
        vehicles=[
            VehicleScoring(
                id=1, is_player=True, control=0, lap_dist=1000.0,
                local_vel=TelemVect3(0.0, 0.0, 50.0), in_pits=False, in_garage_stall=False, finish_status=0,
            ),
            VehicleScoring(
                id=2, driver_name="Pit Lane Car", is_player=False, control=1, lap_dist=970.0,
                local_vel=TelemVect3(0.0, 0.0, 60.0), in_pits=True, in_garage_stall=False, finish_status=0,
            ),
        ],
    )

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

    # Joueur dans les stands (in_pits=True), une voiture arrive très vite sur la ligne droite des stands
    scoring_player_in_pits = FullScoringSession(
        session=10,
        lap_dist=5000.0,
        vehicles=[
            VehicleScoring(
                id=1, is_player=True, control=0, lap_dist=1000.0,
                local_vel=TelemVect3(0.0, 0.0, 16.0), in_pits=True, in_garage_stall=False, finish_status=0,
            ),
            VehicleScoring(
                id=2, driver_name="Track Car", is_player=False, control=1, lap_dist=960.0,
                local_vel=TelemVect3(0.0, 0.0, 70.0), in_pits=False, in_garage_stall=False, finish_status=0,
            ),
        ],
    )

    msg = role.update(EngineerContext(scoring=scoring_player_in_pits))
    assert msg is None
    assert role.state == TrafficSpotterState.IDLE
    assert not role.is_busy()
    assert len(played) == 0


def test_traffic_spotter_tracked_car_enters_pits_aborts():
    """Vérifie que si la voiture suivie rentre aux stands (in_pits devient True), le spotter lâche la cible proprement."""
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = TrafficSpotterRole(audio_engine=mock_audio)

    # 1. Approche en piste
    sc1 = make_scoring_packet(player_dist=500.0, player_speed_mps=50.0, opp_dist=460.0, opp_speed_mps=60.0)
    role.update(EngineerContext(scoring=sc1))
    assert role.state == TrafficSpotterState.APPROACHING
    assert role.target_vehicle_id == 2

    # 2. La voiture suivie prend la voie des stands (in_pits=True)
    sc2 = make_scoring_packet(player_dist=550.0, player_speed_mps=50.0, opp_dist=530.0, opp_speed_mps=30.0)
    sc2.vehicles[1].in_pits = True

    msg = role.update(EngineerContext(scoring=sc2))
    assert msg is None
    assert role.state == TrafficSpotterState.IDLE
    assert role.target_vehicle_id is None


def test_traffic_spotter_with_rawudp_typed_models():
    """Vérifie le fonctionnement de TrafficSpotterRole avec les modèles typés FullScoringSession et VehicleScoring."""
    from isimotor_rawudp_client import VehicleScoring, FullScoringSession, TelemVect3

    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = TrafficSpotterRole(audio_engine=mock_audio)

    player = VehicleScoring(
        id=1,
        driver_name="Player Driver",
        is_player=True,
        control=0,
        in_pits=False,
        in_garage_stall=False,
        lap_dist=1000.0,
        local_vel=TelemVect3(0.0, 0.0, -50.0),
        finish_status=0,
    )
    opp = VehicleScoring(
        id=2,
        driver_name="Fast Opponent",
        is_player=False,
        control=1,
        in_pits=False,
        in_garage_stall=False,
        lap_dist=960.0,  # 40m derrière
        local_vel=TelemVect3(0.0, 0.0, -60.0),  # +10 m/s plus rapide -> TTC = 4.0s
        finish_status=0,
    )
    session = FullScoringSession(
        session=10,
        track_name="Le Mans",
        lap_dist=5000.0,
        num_vehicles=2,
        vehicles=[player, opp],
    )

    # 1. Première détection -> Déclenchement "incoming"
    msg = role.update(EngineerContext(scoring=session))
    assert msg is not None
    assert msg.phrase_key == "incoming"
    assert role.state == TrafficSpotterState.APPROACHING
    assert role.target_vehicle_id == 2


def test_traffic_spotter_cooldown_prevents_incoming_loop():
    """Vérifie que l'anti-chatter empêche 'incoming' de boucler indéfiniment lors d'oscillations de vitesse."""
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = TrafficSpotterRole(audio_engine=mock_audio, ttc_trigger_sec=5.0, target_memory_sec=6.0)

    # 1. Déclenchement initial à t=100s -> "incoming"
    sc1 = make_scoring_packet(player_dist=500.0, player_speed_mps=50.0, opp_dist=460.0, opp_speed_mps=60.0)
    msg1 = role.update(EngineerContext(scoring=sc1, timestamp=100.0))
    assert msg1 is not None
    assert msg1.phrase_key == "incoming"
    assert len(played) == 1

    # 2. Fluctuation de vitesse : l'adversaire ralentit légèrement à t=100.1s -> Abort
    sc_slow = make_scoring_packet(player_dist=505.0, player_speed_mps=50.0, opp_dist=464.0, opp_speed_mps=50.5)
    msg_slow = role.update(EngineerContext(scoring=sc_slow, timestamp=100.1))
    assert msg_slow is None
    assert role.state == TrafficSpotterState.IDLE

    # 3. Au tick suivant t=100.2s, l'adversaire ré-accélère à 60 m/s
    # Grâce au cooldown (6.0s), "incoming" ne doit PAS être re-émis en boucle !
    sc_fast_again = make_scoring_packet(player_dist=510.0, player_speed_mps=50.0, opp_dist=470.0, opp_speed_mps=60.0)
    msg_retrigger = role.update(EngineerContext(scoring=sc_fast_again, timestamp=100.2))
    assert msg_retrigger is None
    assert len(played) == 1  # Toujours 1 seul incoming joué


def test_traffic_spotter_configurable_memory_seconds():
    """Vérifie que le paramètre target_memory_sec est exposé, configurable et sérialisable."""
    role = TrafficSpotterRole(target_memory_sec=8.0)
    assert role.target_memory_sec == 8.0
    assert role.incoming_cooldown_sec == 8.0

    # Vérification dans get_parameters
    params = {p.name: p for p in role.get_parameters()}
    assert "target_memory_sec" in params
    assert params["target_memory_sec"].min_val == 1.0
    assert params["target_memory_sec"].max_val == 30.0

    # Modification via set_param_value
    role.set_param_value("target_memory_sec", 12.0)
    assert role.target_memory_sec == 12.0

    # Export / Import de configuration
    cfg = role.get_config()
    assert cfg["target_memory_sec"] == 12.0

    role2 = TrafficSpotterRole()
    role2.set_config({"target_memory_sec": 15.0})
    assert role2.target_memory_sec == 15.0


def test_traffic_spotter_incoming_only_once_within_n_seconds():
    """
    Vérifie l'exigence 2 :
    Le traffic spotter ne doit faire l'annonce 'incoming' qu'une seule fois
    pendant ses N secondes si c'est toujours la même voiture.
    """
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    # N = 5 secondes de mémoire
    role = TrafficSpotterRole(audio_engine=mock_audio, ttc_trigger_sec=5.0, target_memory_sec=5.0)

    # 1. t=10.0s : Première approche (delta=10m/s, dist=45m -> TTC=4.5s) -> Annonce "incoming"
    sc1 = make_scoring_packet(player_dist=500.0, player_speed_mps=50.0, opp_dist=455.0, opp_speed_mps=60.0, opp_id=42)
    msg1 = role.update(EngineerContext(scoring=sc1, timestamp=10.0))
    assert msg1 is not None
    assert msg1.phrase_key == "incoming"
    assert [p[0] for p in played] == ["incoming"]

    # 2. t=11.0s : La voiture ralentit (delta=0.5m/s) -> Abort vers IDLE
    sc2 = make_scoring_packet(player_dist=550.0, player_speed_mps=50.0, opp_dist=500.0, opp_speed_mps=50.5, opp_id=42)
    msg2 = role.update(EngineerContext(scoring=sc2, timestamp=11.0))
    assert msg2 is None
    assert role.state == TrafficSpotterState.IDLE

    # 3. t=12.0s : La même voiture ré-accélère (TTC=4.5s) dans la fenêtre des 5 secondes (< 15.0s)
    sc3 = make_scoring_packet(player_dist=600.0, player_speed_mps=50.0, opp_dist=555.0, opp_speed_mps=60.0, opp_id=42)
    msg3 = role.update(EngineerContext(scoring=sc3, timestamp=12.0))
    # Ne doit PAS annoncer 'incoming' à nouveau !
    assert msg3 is None
    assert [p[0] for p in played] == ["incoming"]

    # 4. t=13.0s : La même voiture ralentit encore -> Abort
    msg4 = role.update(EngineerContext(scoring=sc2, timestamp=13.0))
    assert msg4 is None
    assert role.state == TrafficSpotterState.IDLE

    # 5. t=14.0s : Ré-accélération (TTC=4.2s) toujours dans les 5 secondes
    sc5 = make_scoring_packet(player_dist=700.0, player_speed_mps=50.0, opp_dist=658.0, opp_speed_mps=60.0, opp_id=42)
    msg5 = role.update(EngineerContext(scoring=sc5, timestamp=14.0))
    # Toujours 1 seule annonce "incoming" au total !
    assert msg5 is None
    assert [p[0] for p in played] == ["incoming"]


def test_traffic_spotter_progression_only_rules():
    """
    Vérifie l'exigence 2 (autrement dit) :
    Le spotter fait une annonce UNIQUEMENT si la voiture progresse.
    Il ne peut pas annoncer deux fois '3' ou 'incoming' ou '2'.
    """
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = TrafficSpotterRole(audio_engine=mock_audio, ttc_trigger_sec=5.0, target_memory_sec=10.0)

    # 1. t=10.0s : Approche initiale TTC = 4.5s (Stade 5) -> "incoming"
    sc1 = make_scoring_packet(player_dist=500.0, player_speed_mps=50.0, opp_dist=455.0, opp_speed_mps=60.0, opp_id=7)
    msg1 = role.update(EngineerContext(scoring=sc1, timestamp=10.0))
    assert msg1 is not None
    assert msg1.phrase_key == "incoming"

    # 2. t=11.0s : Progression TTC = 2.8s (Stade 3) -> "three"
    sc2 = make_scoring_packet(player_dist=600.0, player_speed_mps=50.0, opp_dist=572.0, opp_speed_mps=60.0, opp_id=7)
    msg2 = role.update(EngineerContext(scoring=sc2, timestamp=11.0))
    assert msg2 is not None
    assert msg2.phrase_key == "three"
    assert [p[0] for p in played] == ["incoming", "three"]

    # 3. t=12.0s : Fluctuation de distance TTC = 2.9s (Toujours Stade 3) -> AUCUNE annonce
    sc3 = make_scoring_packet(player_dist=650.0, player_speed_mps=50.0, opp_dist=621.0, opp_speed_mps=60.0, opp_id=7)
    msg3 = role.update(EngineerContext(scoring=sc3, timestamp=12.0))
    assert msg3 is None
    assert [p[0] for p in played] == ["incoming", "three"]

    # 4. t=13.0s : La voiture ralentit fort et s'écarte -> Abort vers IDLE
    sc_slow = make_scoring_packet(player_dist=700.0, player_speed_mps=50.0, opp_dist=650.0, opp_speed_mps=50.0, opp_id=7)
    msg_slow = role.update(EngineerContext(scoring=sc_slow, timestamp=13.0))
    assert msg_slow is None
    assert role.state == TrafficSpotterState.IDLE

    # 5. t=14.0s : La voiture revient à TTC = 2.8s (Stade 3)
    # Puisque 'three' a déjà été annoncé pour cette voiture, elle n'a PAS progressé -> Silence !
    sc_re_3 = make_scoring_packet(player_dist=750.0, player_speed_mps=50.0, opp_dist=722.0, opp_speed_mps=60.0, opp_id=7)
    msg_re_3 = role.update(EngineerContext(scoring=sc_re_3, timestamp=14.0))
    assert msg_re_3 is None
    assert [p[0] for p in played] == ["incoming", "three"]

    # 6. t=15.0s : La voiture accélère et atteint TTC = 1.8s (Stade 2)
    # 2 < 3 -> Progression validée -> Annonce "two" !
    sc_prog_2 = make_scoring_packet(player_dist=800.0, player_speed_mps=50.0, opp_dist=782.0, opp_speed_mps=60.0, opp_id=7)
    msg_prog_2 = role.update(EngineerContext(scoring=sc_prog_2, timestamp=15.0))
    assert msg_prog_2 is not None
    assert msg_prog_2.phrase_key == "two"
    assert [p[0] for p in played] == ["incoming", "three", "two"]

    # 7. t=16.0s : Oscillation à TTC = 1.9s (Toujours Stade 2) -> Silence !
    sc_osc_2 = make_scoring_packet(player_dist=850.0, player_speed_mps=50.0, opp_dist=831.0, opp_speed_mps=60.0, opp_id=7)
    msg_osc_2 = role.update(EngineerContext(scoring=sc_osc_2, timestamp=16.0))
    assert msg_osc_2 is None
    assert [p[0] for p in played] == ["incoming", "three", "two"]

    # 8. t=17.0s : Progression à TTC = 0.8s (Stade 1) -> Annonce "one" !
    sc_prog_1 = make_scoring_packet(player_dist=900.0, player_speed_mps=50.0, opp_dist=892.0, opp_speed_mps=60.0, opp_id=7)
    msg_prog_1 = role.update(EngineerContext(scoring=sc_prog_1, timestamp=17.0))
    assert msg_prog_1 is not None
    assert msg_prog_1.phrase_key == "one"
    assert [p[0] for p in played] == ["incoming", "three", "two", "one"]


def test_traffic_spotter_memory_expiry_allows_new_incoming():
    """Vérifie qu'après l'expiration des N secondes, une nouvelle approche ré-émet 'incoming'."""
    played = []

    def mock_audio(phrase_key, interrupt=False):
        played.append((phrase_key, interrupt))

    role = TrafficSpotterRole(audio_engine=mock_audio, ttc_trigger_sec=5.0, target_memory_sec=4.0)

    # 1. t=10.0s : Détection initiale -> "incoming"
    sc1 = make_scoring_packet(player_dist=500.0, player_speed_mps=50.0, opp_dist=455.0, opp_speed_mps=60.0, opp_id=9)
    msg1 = role.update(EngineerContext(scoring=sc1, timestamp=10.0))
    assert msg1 is not None
    assert msg1.phrase_key == "incoming"
    assert len(played) == 1

    # 2. t=11.0s : Abort
    sc_slow = make_scoring_packet(player_dist=550.0, player_speed_mps=50.0, opp_dist=500.0, opp_speed_mps=50.0, opp_id=9)
    role.update(EngineerContext(scoring=sc_slow, timestamp=11.0))
    assert role.state == TrafficSpotterState.IDLE

    # 3. t=15.0s : 4.0 secondes plus tard (15.0 - 10.0 = 5.0s > target_memory_sec=4.0s)
    # La mémoire est expirée : l'approche est traitée comme un nouvel événement -> Annonce "incoming" !
    sc_new = make_scoring_packet(player_dist=700.0, player_speed_mps=50.0, opp_dist=655.0, opp_speed_mps=60.0, opp_id=9)
    msg_new = role.update(EngineerContext(scoring=sc_new, timestamp=15.0))
    assert msg_new is not None
    assert msg_new.phrase_key == "incoming"
    assert len(played) == 2


