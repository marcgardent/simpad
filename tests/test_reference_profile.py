"""
Unit tests for ReferenceLapProfile and TrackAnnotation domain model.
"""

import tempfile
import unittest
import json
from pathlib import Path

from src.telemetry.reference_profile import (
    ReferenceLapProfile,
    TrackAnnotation,
    AnnotationType,
    get_marks_filepath,
)


class TestReferenceProfile(unittest.TestCase):
    def setUp(self):
        self.profile = ReferenceLapProfile(
            track_name="Spa",
            vehicle_name="Ferrari 499P",
            vehicle_class="Hypercar",
            lap_time=120.0,
            track_length=1000.0,
            spatial_step=1.0,
            num_points=1001,
            t_grid=[(i / 1000.0) * 120.0 for i in range(1001)],
            speed_grid=[20.0 + (i / 1000.0) * 30.0 for i in range(1001)],  # 20 to 50 m/s
            throttle_grid=[(i % 100) / 100.0 for i in range(1001)],
            brake_grid=[1.0 - (i % 100) / 100.0 for i in range(1001)],
            steering_grid=[((i % 200) - 100) / 100.0 for i in range(1001)],
        )

    def test_interpolation_at_distance(self):
        """Test linear O(1) interpolation for all 5 telemetry signals."""
        vals = self.profile.get_value_at_dist(500.0)
        self.assertAlmostEqual(vals["time_into"], 60.0, places=2)
        self.assertAlmostEqual(vals["speed_ms"], 35.0, places=2)
        self.assertAlmostEqual(vals["speed_kmh"], 35.0 * 3.6, places=2)
        self.assertTrue(0.0 <= vals["throttle"] <= 1.0)
        self.assertTrue(0.0 <= vals["brake"] <= 1.0)
        self.assertTrue(-1.0 <= vals["steering"] <= 1.0)

    def test_add_and_remove_annotations(self):
        """Test adding annotations of various types and removing them."""
        ann_brake = self.profile.add_annotation(AnnotationType.BRAKE, distance=300.0, auto_save=False)
        ann_turn = self.profile.add_annotation(AnnotationType.TURN, distance=400.0, auto_save=False)
        ann_gear = self.profile.add_annotation(AnnotationType.GEAR, distance=350.0, gear=3, auto_save=False)
        ann_turn_in = self.profile.add_annotation(AnnotationType.TURN_IN, distance=380.0, auto_save=False)

        self.assertEqual(len(self.profile.annotations), 4)
        # Verify sorted order by distance
        self.assertEqual([a.distance for a in self.profile.annotations], [300.0, 350.0, 380.0, 400.0])

        # Test remove
        self.assertTrue(self.profile.remove_annotation(ann_brake.id, auto_save=False))
        self.assertEqual(len(self.profile.annotations), 3)

    def test_dynamic_turn_numbering_recalculation(self):
        """Verify that Turn numbers (T1, T2, T3...) are dynamically recalculated by distance."""
        t1 = self.profile.add_annotation(AnnotationType.TURN, distance=100.0, auto_save=False)
        t3 = self.profile.add_annotation(AnnotationType.TURN, distance=500.0, auto_save=False)

        self.assertEqual(self.profile.get_turn_number(t1.id), 1)
        self.assertEqual(self.profile.get_turn_number(t3.id), 2)
        self.assertEqual(self.profile.get_annotation_display_label(t1), "T1")
        self.assertEqual(self.profile.get_annotation_display_label(t3), "T2")

        # Insert a turn in between (at distance 250m)
        t2 = self.profile.add_annotation(AnnotationType.TURN, distance=250.0, auto_save=False)

        # Now t2 should be Turn 2, and t3 should become Turn 3 automatically!
        self.assertEqual(self.profile.get_turn_number(t1.id), 1)
        self.assertEqual(self.profile.get_turn_number(t2.id), 2)
        self.assertEqual(self.profile.get_turn_number(t3.id), 3)
        self.assertEqual(self.profile.get_annotation_display_label(t2), "T2")
        self.assertEqual(self.profile.get_annotation_display_label(t3), "T3")

        # Move t3 before t1 (to distance 50m)
        self.profile.move_annotation(t3.id, 50.0, auto_save=False)
        # Now t3 is at 50m -> Turn 1, t1 at 100m -> Turn 2, t2 at 250m -> Turn 3
        self.assertEqual(self.profile.get_turn_number(t3.id), 1)
        self.assertEqual(self.profile.get_turn_number(t1.id), 2)
        self.assertEqual(self.profile.get_turn_number(t2.id), 3)

    def test_annotation_phrase_keys(self):
        """Verify audio phrase keys for all annotation types."""
        ann_brk = self.profile.add_annotation(AnnotationType.BRAKE, distance=100.0, auto_save=False)
        ann_turn_in = self.profile.add_annotation(AnnotationType.TURN_IN, distance=150.0, auto_save=False)
        ann_turn1 = self.profile.add_annotation(AnnotationType.TURN, distance=200.0, auto_save=False)
        ann_turn2 = self.profile.add_annotation(AnnotationType.TURN, distance=300.0, auto_save=False)
        ann_gear2 = self.profile.add_annotation(AnnotationType.GEAR, distance=180.0, gear=2, auto_save=False)
        ann_gear6 = self.profile.add_annotation(AnnotationType.GEAR, distance=600.0, gear=6, auto_save=False)

        self.assertEqual(self.profile.get_annotation_phrase_key(ann_brk), "brake")
        self.assertEqual(self.profile.get_annotation_phrase_key(ann_turn_in), "turn")
        self.assertEqual(self.profile.get_annotation_phrase_key(ann_turn1), "turn_1")
        self.assertEqual(self.profile.get_annotation_phrase_key(ann_turn2), "turn_2")
        self.assertEqual(self.profile.get_annotation_phrase_key(ann_gear2), "gear_2")
        self.assertEqual(self.profile.get_annotation_phrase_key(ann_gear6), "gear_6")
        self.assertEqual(self.profile.get_annotation_display_label(ann_gear2), "G2")
        self.assertEqual(self.profile.get_annotation_display_label(ann_gear6), "G6")

    def test_segregated_telemetry_and_marks_persistence(self):
        """Test separated persistence for telemetry (.json) and auto-saved marks (.marks.json)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            telem_path = Path(tmpdir) / "ref_spa_hypercar.json"
            marks_path = get_marks_filepath(telem_path)
            self.assertEqual(marks_path.name, "ref_spa_hypercar.marks.json")

            # 1. Save telemetry
            self.profile.save_telemetry_to_file(telem_path)
            self.assertTrue(telem_path.exists())
            self.assertFalse(marks_path.exists())

            # 2. Add annotation with auto-save to marks_path
            self.profile.set_marks_filepath(marks_path)
            ann1 = self.profile.add_annotation(AnnotationType.BRAKE, distance=200.0, auto_save=True)
            self.assertTrue(marks_path.exists())

            # Check marks content
            content = json.loads(marks_path.read_text(encoding="utf-8"))
            self.assertEqual(len(content["annotations"]), 1)
            self.assertEqual(content["annotations"][0]["type"], "brake")

            # 3. Add second annotation (auto-save immediately)
            ann2 = self.profile.add_annotation(AnnotationType.GEAR, distance=250.0, gear=3, auto_save=True)
            content = json.loads(marks_path.read_text(encoding="utf-8"))
            self.assertEqual(len(content["annotations"]), 2)

            # 4. Move annotation (auto-save immediately)
            self.profile.move_annotation(ann2.id, 280.0, auto_save=True)
            content = json.loads(marks_path.read_text(encoding="utf-8"))
            self.assertEqual(content["annotations"][1]["distance"], 280.0)

            # 5. Load telemetry from file -> automatically loads associated .marks.json!
            loaded = ReferenceLapProfile.load_from_file(telem_path)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.lap_time, self.profile.lap_time)
            self.assertEqual(len(loaded.annotations), 2)
            self.assertEqual(loaded.annotations[0].type, AnnotationType.BRAKE)
            self.assertEqual(loaded.annotations[1].type, AnnotationType.GEAR)
            self.assertEqual(loaded.annotations[1].gear, 3)

            # 6. Delete annotation (auto-save immediately)
            loaded.remove_annotation(ann1.id, auto_save=True)
            content_after = json.loads(marks_path.read_text(encoding="utf-8"))
            self.assertEqual(len(content_after["annotations"]), 1)


if __name__ == "__main__":
    unittest.main()
