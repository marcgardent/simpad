"""
Unit tests for PaceNotesRole (Race Engineer pace notes and track markers announcer).
"""

import unittest
from unittest.mock import MagicMock
from isimotor_rawudp_client import FullScoringSession, VehicleScoring, TelemVect3
from simpad_qt.builtin_plugins.race_engineer.context import EngineerContext
from simpad_qt.builtin_plugins.race_engineer.subplugins.pace_notes import PaceNotesRole
from simpad_qt.core.telemetry.reference_profile import ReferenceLapProfile, TrackAnnotation, AnnotationType


class TestPaceNotesRole(unittest.TestCase):
    def setUp(self):
        self.mock_audio = MagicMock()
        self.role = PaceNotesRole(audio_engine=self.mock_audio, anticipation_time_sec=1.0)

        # Profile with 1000m track and markers:
        # Brake at 200m, Turn-in at 230m, Turn (T1) at 250m, Gear 2 at 220m
        self.profile = ReferenceLapProfile(
            track_name="TestTrack",
            track_length=1000.0,
            annotations=[
                TrackAnnotation(id="b1", type=AnnotationType.BRAKE, distance=200.0),
                TrackAnnotation(id="g1", type=AnnotationType.GEAR, distance=220.0, gear=2),
                TrackAnnotation(id="i1", type=AnnotationType.TURN_IN, distance=230.0),
                TrackAnnotation(id="t1", type=AnnotationType.TURN, distance=250.0),
            ]
        )
        self.role.set_reference_profile(self.profile)

    def test_anticipation_and_triggering(self):
        """At 20 m/s with 1.0s anticipation (lead=20m), when car is at 185m, Brake (200m) should trigger!"""
        context = EngineerContext(
            scoring=FullScoringSession(
                lap_dist=1000.0,
                vehicles=[
                    VehicleScoring(
                        id=1,
                        is_player=True,
                        lap_dist=185.0,  # 15m before 200m -> within 20m window
                        total_laps=1,
                        local_vel=TelemVect3(0.0, 0.0, 20.0),
                    )
                ]
            ),
            timestamp=10.0,
            audio_engine=self.mock_audio,
        )

        msg = self.role.update(context)
        self.assertIsNotNone(msg)
        self.assertEqual(msg.phrase_key, "brake")
        self.mock_audio.play_phrase.assert_called_with("brake", interrupt=False)

        # Second update at 186m in same lap should NOT re-trigger brake
        context.timestamp = 10.1
        context.scoring.vehicles[0].lap_dist = 186.0
        msg2 = self.role.update(context)
        self.assertIsNone(msg2)

    def test_subsequent_markers_triggering(self):
        """As the vehicle progresses along track, gear 2, turn-in, and turn 1 trigger sequentially."""
        # Vehicle at 210m (lead=20m -> reaches gear at 220m)
        context = EngineerContext(
            scoring=FullScoringSession(
                lap_dist=1000.0,
                vehicles=[
                    VehicleScoring(
                        id=1,
                        is_player=True,
                        lap_dist=210.0,
                        total_laps=1,
                        local_vel=TelemVect3(0.0, 0.0, 20.0),
                    )
                ]
            ),
            timestamp=12.0,
            audio_engine=self.mock_audio,
        )
        msg = self.role.update(context)
        self.assertIsNotNone(msg)
        self.assertEqual(msg.phrase_key, "gear_2")

        # Vehicle at 235m (lead=20m -> reaches turn 1 at 250m)
        context.timestamp = 13.0
        context.scoring.vehicles[0].lap_dist = 235.0
        msg = self.role.update(context)
        self.assertIsNotNone(msg)
        self.assertEqual(msg.phrase_key, "turn_1")

    def test_lap_reset(self):
        """When a new lap starts (mTotalLaps changes), markers should be reset and can trigger again."""
        # Trigger brake at 185m
        context = EngineerContext(
            scoring=FullScoringSession(
                lap_dist=1000.0,
                vehicles=[
                    VehicleScoring(
                        id=1,
                        is_player=True,
                        lap_dist=185.0,
                        total_laps=1,
                        local_vel=TelemVect3(0.0, 0.0, 20.0),
                    )
                ]
            ),
            timestamp=10.0,
            audio_engine=self.mock_audio,
        )
        self.role.update(context)
        self.assertTrue("b1" in self.role._triggered_ann_ids)

        # Advance to next lap
        context.scoring.vehicles[0].total_laps = 2
        context.scoring.vehicles[0].lap_dist = 10.0
        context.timestamp = 40.0
        self.role.update(context)

        # Triggered list should be reset!
        self.assertEqual(len(self.role._triggered_ann_ids), 0)

    def test_live_annotation_modifications_sync(self):
        """When user modifies annotations in real time, PaceNotesRole detects signature change and triggers new notes."""
        # 1. Trigger brake at 185m
        context = EngineerContext(
            scoring=FullScoringSession(
                lap_dist=1000.0,
                vehicles=[
                    VehicleScoring(
                        id=1,
                        is_player=True,
                        lap_dist=185.0,
                        total_laps=1,
                        local_vel=TelemVect3(0.0, 0.0, 20.0),
                    )
                ]
            ),
            timestamp=10.0,
            audio_engine=self.mock_audio,
        )
        msg1 = self.role.update(context)
        self.assertIsNotNone(msg1)
        self.assertEqual(msg1.phrase_key, "brake")

        # 2. Add a new Gear 4 marker at 190m in real-time
        self.profile.add_annotation(AnnotationType.GEAR, distance=190.0, gear=4, auto_save=False)
        # Next tick at 185m should immediately recognize the new signature and trigger Gear 4!
        context.timestamp = 11.0
        msg2 = self.role.update(context)
        self.assertIsNotNone(msg2)
        self.assertEqual(msg2.phrase_key, "gear_4")

    def test_all_annotation_types_announcements(self):
        """Verify phrase keys for Brake, Turn-in, Turn, and Gear."""
        ann_brake = TrackAnnotation(type=AnnotationType.BRAKE, distance=100.0)
        ann_turn_in = TrackAnnotation(type=AnnotationType.TURN_IN, distance=200.0)
        ann_turn = TrackAnnotation(type=AnnotationType.TURN, distance=300.0)
        ann_gear = TrackAnnotation(type=AnnotationType.GEAR, distance=400.0, gear=5)

        prof = ReferenceLapProfile(track_name="Test", annotations=[ann_brake, ann_turn_in, ann_turn, ann_gear])
        self.assertEqual(prof.get_annotation_phrase_key(ann_brake), "brake")
        self.assertEqual(prof.get_annotation_phrase_key(ann_turn_in), "turn")
        self.assertEqual(prof.get_annotation_phrase_key(ann_turn), "turn_1")
        self.assertEqual(prof.get_annotation_phrase_key(ann_gear), "gear_5")


if __name__ == "__main__":
    unittest.main()
