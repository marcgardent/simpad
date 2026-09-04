"""
Tests unitaires pour le système de filtrage par Tour de Référence des Rôles Trafic.
Vérifie la détection du domaine normal et le filtrage (il faut qu'au moins l'un des deux véhicules soit hors domaine).
"""

import unittest
from unittest.mock import MagicMock
from isimotor_rawudp_client import FullScoringSession, VehicleScoring, TelemVect3
from src.engineer.context import EngineerContext
from src.engineer.roles.traffic_spotter import TrafficSpotterRole, TrafficSpotterState
from src.engineer.roles.traffic_jam import TrafficJamRole
from src.telemetry.reference_profile import ReferenceLapProfile


def create_mock_reference_profile(track_length=5000.0, base_speed_kmh=200.0):
    """Crée un profil de référence synthétique avec vitesse personnalisée le long de la piste."""
    step = 10.0
    num_pts = int(track_length / step) + 1
    t_grid = []
    speed_grid = []
    curr_t = 0.0
    v_mps = base_speed_kmh / 3.6

    for i in range(num_pts):
        dist = i * step
        # Simuler une épingle lente entre 1000m et 1200m (vitesse ref = 40 km/h)
        if 1000.0 <= dist <= 1200.0:
            speed_val = 40.0 / 3.6
        else:
            speed_val = v_mps
        speed_grid.append(speed_val)
        t_grid.append(curr_t)
        curr_t += step / max(1.0, speed_val)

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


class TestTrafficDomainFilter(unittest.TestCase):

    def setUp(self):
        self.profile = create_mock_reference_profile(track_length=5000.0, base_speed_kmh=200.0)
        self.mock_audio = MagicMock()

    def test_context_domain_methods(self):
        """Vérifie les méthodes de calcul du domaine de vitesse dans EngineerContext."""
        ctx = EngineerContext(reference_profile=self.profile)

        # 1. Position 500m (ref = 200 km/h = 55.55 m/s)
        # Vitesse à 190 km/h (52.77 m/s) -> delta = 10 km/h <= 30 km/h -> IN DOMAIN
        self.assertTrue(ctx.is_speed_in_normal_domain(speed_mps=52.77, track_dist=500.0, tolerance_kmh=30.0))

        # Vitesse à 120 km/h (33.33 m/s) -> delta = 80 km/h > 30 km/h -> OUT OF DOMAIN
        self.assertFalse(ctx.is_speed_in_normal_domain(speed_mps=33.33, track_dist=500.0, tolerance_kmh=30.0))

        # 2. Position 1100m (épingle, ref = 40 km/h = 11.11 m/s)
        # Vitesse à 42 km/h (11.66 m/s) -> delta = 2 km/h <= 30 km/h -> IN DOMAIN
        self.assertTrue(ctx.is_speed_in_normal_domain(speed_mps=11.66, track_dist=1100.0, tolerance_kmh=30.0))

        # Vitesse à 120 km/h (33.33 m/s) -> delta = 80 km/h > 30 km/h -> OUT OF DOMAIN
        self.assertFalse(ctx.is_speed_in_normal_domain(speed_mps=33.33, track_dist=1100.0, tolerance_kmh=30.0))

    def test_context_has_traffic_domain_anomaly(self):
        """Vérifie la condition d'anomalie : il faut au moins l'un des deux hors domaine."""
        ctx = EngineerContext(reference_profile=self.profile)

        p_in = VehicleScoring(lap_dist=500.0, local_vel=TelemVect3(0.0, 0.0, 55.55))     # 200 km/h (ref 200) -> IN
        o_in = VehicleScoring(lap_dist=470.0, local_vel=TelemVect3(0.0, 0.0, 61.11))     # 220 km/h (ref 200) -> IN (delta 20 <= 30)
        p_out = VehicleScoring(lap_dist=500.0, local_vel=TelemVect3(0.0, 0.0, 25.0))     # 90 km/h (ref 200) -> OUT (delta 110 > 30)
        o_out = VehicleScoring(lap_dist=470.0, local_vel=TelemVect3(0.0, 0.0, 77.77))    # 280 km/h (ref 200) -> OUT (delta 80 > 30)

        # Les deux sont IN -> pas d'anomalie -> False
        self.assertFalse(ctx.has_traffic_domain_anomaly(p_in, o_in, tolerance_kmh=30.0))

        # Joueur OUT, Adversaire IN -> anomalie -> True
        self.assertTrue(ctx.has_traffic_domain_anomaly(p_out, o_in, tolerance_kmh=30.0))

        # Joueur IN, Adversaire OUT -> anomalie -> True
        self.assertTrue(ctx.has_traffic_domain_anomaly(p_in, o_out, tolerance_kmh=30.0))

        # Les deux OUT -> anomalie -> True
        self.assertTrue(ctx.has_traffic_domain_anomaly(p_out, o_out, tolerance_kmh=30.0))

    def test_traffic_spotter_filter_normal_racing_vs_anomaly(self):
        """
        Vérifie que TrafficSpotterRole ignore le trafic si les deux sont dans le domaine normal,
        mais déclenche si le joueur ou l'adversaire est hors domaine.
        """
        spotter = TrafficSpotterRole(audio_engine=self.mock_audio, speed_delta_min_kmh=20.0, ttc_trigger_sec=5.0)
        spotter.set_reference_profile(self.profile)

        # Scénario 1 : Deux voitures roulent à allure normale (Course serrée)
        # Joueur à 200 km/h (55.55 m/s) à 500m (ref 200 km/h)
        # Adversaire à 225 km/h (62.5 m/s) à 470m (30m derrière, delta +25 km/h = 6.94 m/s -> TTC = 4.32s <= 5s)
        # Delta TTC déclencherait normalement, MAIS les deux sont dans le domaine normal (200 et 225 vs ref 200).
        ctx_both_in = EngineerContext(
            reference_profile=self.profile,
            scoring=FullScoringSession(
                lap_dist=5000.0,
                vehicles=[
                    VehicleScoring(
                        id=1,
                        is_player=True,
                        lap_dist=500.0,
                        local_vel=TelemVect3(0.0, 0.0, 55.55),
                    ),
                    VehicleScoring(
                        id=2,
                        is_player=False,
                        control=1,
                        driver_name="Opponent 1",
                        lap_dist=470.0,
                        local_vel=TelemVect3(0.0, 0.0, 62.5),
                    )
                ]
            )
        )

        msg = spotter.update(ctx_both_in)
        self.assertIsNone(msg)
        self.assertEqual(spotter.state, TrafficSpotterState.IDLE)

        # Scénario 2 : Le joueur a fait une erreur / est au ralenti (Hors domaine !)
        # Joueur à 80 km/h (22.22 m/s), Adversaire à 200 km/h (55.55 m/s, allure normale) à 40m derrière
        # Delta = +120 km/h (33.33 m/s) -> TTC = 40 / 33.33 = 1.2s
        # Le joueur est HORS DOMAINE -> L'alerte spotter doit se déclencher !
        ctx_player_out = EngineerContext(
            reference_profile=self.profile,
            scoring=FullScoringSession(
                lap_dist=5000.0,
                vehicles=[
                    VehicleScoring(
                        id=1,
                        is_player=True,
                        lap_dist=500.0,
                        local_vel=TelemVect3(0.0, 0.0, 22.22),
                    ),
                    VehicleScoring(
                        id=2,
                        is_player=False,
                        control=1,
                        driver_name="Fast Opponent",
                        lap_dist=460.0,
                        local_vel=TelemVect3(0.0, 0.0, 55.55),
                    )
                ]
            )
        )

        msg2 = spotter.update(ctx_player_out)
        self.assertIsNotNone(msg2)
        self.assertEqual(spotter.state, TrafficSpotterState.APPROACHING)

        # Scénario 3 : Désactivation explicite du filtre du tour de référence
        # Même scénario 1 (les deux dans le domaine), mais avec enable_ref_lap_filter=False
        spotter.reset()
        spotter.enable_ref_lap_filter = False
        msg3 = spotter.update(ctx_both_in)
        self.assertIsNotNone(msg3)
        self.assertEqual(spotter.state, TrafficSpotterState.APPROACHING)

    def test_traffic_jam_filter_slow_corner_vs_anomaly(self):
        """
        Vérifie que TrafficJamRole ne crée pas de fausse alerte dans une épingle lente normale,
        mais détecte un véhicule ralenti sur une portion rapide.
        """
        jam_role = TrafficJamRole(
            audio_engine=self.mock_audio,
            slow_speed_threshold_kmh=50.0,
            warning_distance_m=180.0,
            cooldown_sec=5.0,
        )
        jam_role.set_reference_profile(self.profile)

        # Scénario 1 : Épingle lente à 1100m (ref = 40 km/h)
        # Joueur à 1050m roulant à 38 km/h (10.55 m/s)
        # Adversaire à 1100m (50m devant) roulant à 36 km/h (10.0 m/s < seuil 50 km/h)
        # Sans référence, cela déclencherait l'alerte car 36 km/h < 50 km/h.
        # Avec le filtre de référence, les deux sont dans le domaine normal (38 et 36 vs 40) -> Pas d'alerte !
        ctx_hairpin = EngineerContext(
            reference_profile=self.profile,
            scoring=FullScoringSession(
                lap_dist=5000.0,
                vehicles=[
                    VehicleScoring(
                        id=1,
                        is_player=True,
                        lap_dist=1050.0,
                        local_vel=TelemVect3(0.0, 0.0, 10.55),
                    ),
                    VehicleScoring(
                        id=2,
                        is_player=False,
                        control=1,
                        driver_name="Hairpin Driver",
                        lap_dist=1100.0,
                        local_vel=TelemVect3(0.0, 0.0, 10.0),
                    )
                ]
            )
        )

        msg = jam_role.update(ctx_hairpin)
        self.assertIsNone(msg)
        self.assertFalse(jam_role.is_busy())

        # Scénario 2 : Ligne droite à 2000m (ref = 200 km/h)
        # Joueur à 1950m à 195 km/h (54.16 m/s)
        # Adversaire à 2050m (100m devant) à 35 km/h (9.72 m/s) -> HORS DOMAINE !
        # Doit déclencher l'alerte "car" !
        ctx_straight = EngineerContext(
            reference_profile=self.profile,
            scoring=FullScoringSession(
                lap_dist=5000.0,
                vehicles=[
                    VehicleScoring(
                        id=1,
                        is_player=True,
                        lap_dist=1950.0,
                        local_vel=TelemVect3(0.0, 0.0, 54.16),
                    ),
                    VehicleScoring(
                        id=2,
                        is_player=False,
                        control=1,
                        driver_name="Broken Car",
                        lap_dist=2050.0,
                        local_vel=TelemVect3(0.0, 0.0, 9.72),
                    )
                ]
            )
        )

        msg2 = jam_role.update(ctx_straight)
        self.assertIsNotNone(msg2)
        self.assertEqual(msg2.phrase_key, "car")
        self.assertTrue(jam_role.is_busy())


if __name__ == "__main__":
    unittest.main()
