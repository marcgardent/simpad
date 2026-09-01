"""
Test d'intégration : Manager → EngineerContext → Filtre de Domaine du Traffic Spotter.
Vérifie que le profil de référence est correctement injecté par le Manager
et que le filtre de domaine fonctionne en conditions réelles (pas d'injection manuelle).
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from src.engineer.manager import RaceEngineer
from src.engineer.roles.traffic_spotter import TrafficSpotterRole, TrafficSpotterState
from src.telemetry.reference_profile import ReferenceLapProfile


def _make_profile(track_length=5000.0, base_speed_kmh=200.0):
    """Crée un profil de référence synthétique avec vitesse uniforme."""
    step = 10.0
    num_pts = int(track_length / step) + 1
    v_mps = base_speed_kmh / 3.6
    t_grid = []
    speed_grid = []
    curr_t = 0.0
    for i in range(num_pts):
        speed_grid.append(v_mps)
        t_grid.append(curr_t)
        curr_t += step / max(1.0, v_mps)
    return ReferenceLapProfile(
        track_name="TestCircuit",
        track_length=track_length,
        spatial_step=step,
        num_points=num_pts,
        t_grid=t_grid,
        speed_grid=speed_grid,
        throttle_grid=[1.0] * num_pts,
        brake_grid=[0.0] * num_pts,
        steering_grid=[0.0] * num_pts,
    )


def _scoring_both_in_domain(track_len=5000.0):
    """
    Deux voitures dans le domaine normal (joueur 200 km/h, adversaire 225 km/h, ref 200 km/h).
    Delta = 25 km/h > seuil 20 km/h, TTC = 30 / 6.94 = 4.3s <= 5.0s.
    Sans filtre domaine, le spotter se déclenche. Avec filtre, il ne doit PAS.
    """
    return {
        "mLapDist": track_len,
        "mVehicles": [
            {
                "mID": 1,
                "mIsPlayer": True,
                "mLapDist": 500.0,
                "mLocalVel": [0.0, 0.0, 55.55],  # 200 km/h
            },
            {
                "mID": 2,
                "mIsPlayer": False,
                "mDriverName": "Normal Racer",
                "mLapDist": 470.0,  # 30m derrière
                "mLocalVel": [0.0, 0.0, 62.5],  # 225 km/h
            },
        ],
    }


def _scoring_player_crashed(track_len=5000.0):
    """
    Joueur ralenti (80 km/h, hors domaine), adversaire à allure normale (200 km/h).
    Le filtre doit laisser passer l'alerte.
    """
    return {
        "mLapDist": track_len,
        "mVehicles": [
            {
                "mID": 1,
                "mIsPlayer": True,
                "mLapDist": 500.0,
                "mLocalVel": [0.0, 0.0, 22.22],  # 80 km/h
            },
            {
                "mID": 2,
                "mIsPlayer": False,
                "mDriverName": "Fast Opponent",
                "mLapDist": 460.0,  # 40m derrière
                "mLocalVel": [0.0, 0.0, 55.55],  # 200 km/h
            },
        ],
    }


def test_manager_injects_reference_profile_into_context():
    """
    Vérifie que le Manager résout et injecte le profil de référence dans l'EngineerContext.
    Le filtre de domaine doit filtrer les alertes quand les deux voitures sont dans le domaine.
    """
    profile = _make_profile()
    mock_audio = MagicMock()

    # Simuler le DeltaEngine global avec un profil valide
    mock_delta_engine = MagicMock()
    mock_delta_engine.all_time_best_profile = profile
    mock_delta_engine.current_profile = None

    engineer = RaceEngineer(audio_engine=mock_audio, auto_load_builtin_roles=False)

    # Créer un spotter avec filtre domaine activé
    spotter = TrafficSpotterRole(
        audio_engine=mock_audio,
        speed_delta_min_kmh=20.0,
        ttc_trigger_sec=5.0,
        enable_ref_lap_filter=True,
        domain_speed_tolerance_kmh=30.0,
    )
    engineer.add_role(spotter)

    scoring_normal = _scoring_both_in_domain()

    with patch("src.telemetry.lmu_parser.LMUParser") as MockLMU:
        MockLMU._delta_engine = mock_delta_engine

        # Les deux dans le domaine → doit être filtré (pas d'alerte)
        messages = engineer.update(scoring=scoring_normal)

        assert len(messages) == 0, (
            f"Le spotter ne devrait PAS se déclencher quand les deux voitures sont dans le domaine. "
            f"Messages reçus : {[m.phrase_key for m in messages]}"
        )
        assert spotter.state == TrafficSpotterState.IDLE


def test_manager_domain_filter_allows_anomaly():
    """
    Vérifie que le filtre laisse passer quand le joueur est hors domaine (crash/erreur).
    """
    profile = _make_profile()
    mock_audio = MagicMock()

    mock_delta_engine = MagicMock()
    mock_delta_engine.all_time_best_profile = profile
    mock_delta_engine.current_profile = None

    engineer = RaceEngineer(audio_engine=mock_audio, auto_load_builtin_roles=False)

    spotter = TrafficSpotterRole(
        audio_engine=mock_audio,
        speed_delta_min_kmh=20.0,
        ttc_trigger_sec=5.0,
        enable_ref_lap_filter=True,
        domain_speed_tolerance_kmh=30.0,
    )
    engineer.add_role(spotter)

    scoring_crash = _scoring_player_crashed()

    with patch("src.telemetry.lmu_parser.LMUParser") as MockLMU:
        MockLMU._delta_engine = mock_delta_engine

        # Joueur hors domaine → l'alerte DOIT passer
        messages = engineer.update(scoring=scoring_crash)

        assert len(messages) == 1
        assert messages[0].phrase_key == "incoming"
        assert spotter.state == TrafficSpotterState.APPROACHING


def test_manager_no_profile_bypasses_filter():
    """
    Vérifie le comportement fail-open : sans profil de référence,
    le filtre est bypassé et le spotter fonctionne normalement.
    """
    mock_audio = MagicMock()

    mock_delta_engine = MagicMock()
    mock_delta_engine.all_time_best_profile = None
    mock_delta_engine.current_profile = None

    engineer = RaceEngineer(audio_engine=mock_audio, auto_load_builtin_roles=False)

    spotter = TrafficSpotterRole(
        audio_engine=mock_audio,
        speed_delta_min_kmh=20.0,
        ttc_trigger_sec=5.0,
        enable_ref_lap_filter=True,
    )
    engineer.add_role(spotter)

    scoring = _scoring_both_in_domain()

    with patch("src.telemetry.lmu_parser.LMUParser") as MockLMU:
        MockLMU._delta_engine = mock_delta_engine

        # Sans profil, le filtre est bypassé → l'alerte passe (fail-open)
        messages = engineer.update(scoring=scoring)

        assert len(messages) == 1
        assert messages[0].phrase_key == "incoming"
