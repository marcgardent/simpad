"""
Unit tests for Role Parameters (SOLID declarative parameter system)
and dynamic configuration in Race Engineer roles.
"""

import unittest
from unittest.mock import MagicMock
from simpad_qt.builtin_plugins.race_engineer.params import RoleParam, BoolParam, IntRangeParam, FloatRangeParam
from simpad_qt.builtin_plugins.race_engineer.base import BaseRole, RoleStatus, EngineerMessage
from simpad_qt.builtin_plugins.race_engineer.context import EngineerContext
from simpad_qt.builtin_plugins.race_engineer.subplugins.pace_notes import PaceNotesRole
from simpad_qt.builtin_plugins.race_engineer.subplugins.traffic_spotter import TrafficSpotterRole, TrafficSpotterState
from simpad_qt.core.telemetry.reference_profile import ReferenceLapProfile, TrackAnnotation, AnnotationType
from isimotor_rawudp_client import FullScoringSession, VehicleScoring, TelemVect3


class DummyCustomRole(BaseRole):
    """Test role with declared params."""
    def __init__(self, **kwargs):
        super().__init__(role_id="dummy_role", name="Dummy Role", **kwargs)
        self.chk_option = True
        self.slider_count = 5
        self.slider_threshold = 12.5

    def get_parameters(self):
        return [
            BoolParam(name="chk_option", label="Option Toggle", default=True),
            IntRangeParam(name="slider_count", label="Count", min_val=1, max_val=10, step=1, unit="items", default=5),
            FloatRangeParam(name="slider_threshold", label="Threshold", min_val=0.0, max_val=50.0, step=0.5, unit="m", default=12.5),
        ]

    def is_busy(self) -> bool:
        return False

    def update(self, context):
        return None


class TestRoleParameters(unittest.TestCase):
    def test_param_descriptors_validation_and_clamping(self):
        """Test casting, clamping and default values for BoolParam, IntRangeParam, FloatRangeParam."""
        bp = BoolParam(name="b", label="B", default=True)
        self.assertTrue(bp.cast_and_validate(True))
        self.assertFalse(bp.cast_and_validate(False))
        self.assertTrue(bp.cast_and_validate("true"))
        self.assertFalse(bp.cast_and_validate("false"))

        ip = IntRangeParam(name="i", label="I", min_val=5, max_val=20, default=10)
        self.assertEqual(ip.cast_and_validate(12), 12)
        self.assertEqual(ip.cast_and_validate(2), 5)    # clamped to min
        self.assertEqual(ip.cast_and_validate(100), 20) # clamped to max
        self.assertEqual(ip.cast_and_validate("invalid"), 10) # default fallback

        fp = FloatRangeParam(name="f", label="F", min_val=1.0, max_val=10.0, default=5.0)
        self.assertEqual(fp.cast_and_validate(7.5), 7.5)
        self.assertEqual(fp.cast_and_validate(0.5), 1.0)  # clamped to min
        self.assertEqual(fp.cast_and_validate(50.0), 10.0) # clamped to max
        self.assertEqual(fp.cast_and_validate("bad"), 5.0) # default fallback

    def test_base_role_get_set_config_integration(self):
        """Test that BaseRole automatically serializes and deserializes declared parameters."""
        role = DummyCustomRole()
        params = role.get_parameters()
        self.assertEqual(len(params), 3)

        self.assertEqual(role.get_param_value("chk_option"), True)
        self.assertEqual(role.get_param_value("slider_count"), 5)
        self.assertEqual(role.get_param_value("slider_threshold"), 12.5)

        # Set values
        role.set_param_value("chk_option", False)
        role.set_param_value("slider_count", 8)
        role.set_param_value("slider_threshold", 33.2)

        self.assertEqual(role.chk_option, False)
        self.assertEqual(role.slider_count, 8)
        self.assertEqual(role.slider_threshold, 33.2)

        # Config export
        cfg = role.get_config()
        self.assertFalse(cfg["chk_option"])
        self.assertEqual(cfg["slider_count"], 8)
        self.assertEqual(cfg["slider_threshold"], 33.2)

        # Config reload into a new instance
        role2 = DummyCustomRole()
        role2.set_config(cfg)
        self.assertFalse(role2.chk_option)
        self.assertEqual(role2.slider_count, 8)
        self.assertEqual(role2.slider_threshold, 33.2)

    def test_pace_notes_enable_toggles(self):
        """Test enabling/disabling individual marker types in PaceNotesRole."""
        mock_audio = MagicMock()
        role = PaceNotesRole(audio_engine=mock_audio, anticipation_time_sec=1.0)

        profile = ReferenceLapProfile(
            track_name="TestTrack",
            track_length=1000.0,
            annotations=[
                TrackAnnotation(id="b1", type=AnnotationType.BRAKE, distance=200.0),
                TrackAnnotation(id="g1", type=AnnotationType.GEAR, distance=210.0, gear=3),
                TrackAnnotation(id="i1", type=AnnotationType.TURN_IN, distance=220.0),
                TrackAnnotation(id="t1", type=AnnotationType.TURN, distance=230.0),
            ]
        )
        role.set_reference_profile(profile)

        context = EngineerContext(
            scoring=FullScoringSession(
                lap_dist=1000.0,
                vehicles=[
                    VehicleScoring(
                        id=1,
                        is_player=True,
                        lap_dist=185.0,  # within lead distance of 200m
                        total_laps=1,
                        local_vel=TelemVect3(0.0, 0.0, 20.0),
                    )
                ]
            ),
            timestamp=10.0,
            audio_engine=mock_audio,
        )

        # 1. With enable_brake=False, brake marker at 200m should be ignored!
        role.set_param_value("enable_brake", False)
        msg = role.update(context)
        # Should NOT trigger brake!
        self.assertIsNone(msg)

        # 2. Re-enable brake -> should trigger!
        role.set_param_value("enable_brake", True)
        msg2 = role.update(context)
        self.assertIsNotNone(msg2)
        self.assertEqual(msg2.phrase_key, "brake")

        # 3. Advance vehicle to 205m -> approaching Gear 3 (210m)
        context.scoring.vehicles[0].lap_dist = 205.0
        context.timestamp = 12.0
        # Disable gear announcements
        role.set_param_value("enable_gear", False)
        # It should skip gear 3 and trigger turn-in or nothing within range
        # lead=20m -> reaches 225m (includes turn-in at 220m)
        msg3 = role.update(context)
        self.assertIsNotNone(msg3)
        self.assertEqual(msg3.phrase_key, "turn")  # Turn-in announced instead of Gear!

    def test_traffic_spotter_configurable_delta_threshold(self):
        """Test configuring the delta speed threshold in TrafficSpotterRole."""
        mock_audio = MagicMock()
        # Default speed_delta_min_kmh is 20.0 km/h
        spotter = TrafficSpotterRole(audio_engine=mock_audio, speed_delta_min_kmh=20.0)

        # Opponent behind by 30m approaching at +30 km/h (8.33 m/s) -> TTC = 30 / 8.33 = 3.6s
        # Player at 100 km/h (27.77 m/s), Opponent at 130 km/h (36.11 m/s)
        context = EngineerContext(
            scoring=FullScoringSession(
                lap_dist=5000.0,
                vehicles=[
                    VehicleScoring(
                        id=1,
                        is_player=True,
                        driver_name="Player",
                        vehicle_name="Ferrari",
                        lap_dist=1000.0,
                        local_vel=TelemVect3(0.0, 0.0, 27.77),
                    ),
                    VehicleScoring(
                        id=2,
                        is_player=False,
                        control=1,
                        driver_name="Opponent",
                        vehicle_name="Porsche",
                        lap_dist=970.0,  # 30m behind
                        local_vel=TelemVect3(0.0, 0.0, 36.11),  # +30 km/h
                    )
                ]
            ),
            timestamp=10.0,
            audio_engine=mock_audio,
        )

        # 1. Delta = 30 km/h >= 20 km/h threshold -> Spotter triggers APPROACHING!
        spotter.update(context)
        self.assertEqual(spotter.state, TrafficSpotterState.APPROACHING)

        # 2. Now increase speed_delta_min_kmh to 45.0 km/h
        spotter.reset()
        spotter.set_param_value("speed_delta_min_kmh", 45.0)
        self.assertEqual(spotter.speed_delta_min_kmh, 45.0)

        # 3. Re-evaluate: delta (30 km/h) is now BELOW threshold (45 km/h) -> stays IDLE!
        spotter.update(context)
        self.assertEqual(spotter.state, TrafficSpotterState.IDLE)


if __name__ == "__main__":
    unittest.main()
