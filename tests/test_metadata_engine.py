"""Unit tests for MetadataEngine (simpulse/core/telemetry/metadata_engine.py)."""

import unittest
from pathlib import Path

from simpulse.core.telemetry.metadata_engine import MetadataEngine


class TestMetadataEngine(unittest.TestCase):
    def test_none_before_track_resolved(self):
        meta = MetadataEngine(base_dir=Path("/tmp/refs"))
        self.assertIsNone(meta.get_profile_filepath())
        self.assertIsNone(meta.get_energy_history_filepath())

    def test_resolves_profile_and_energy_filepaths(self):
        meta = MetadataEngine(base_dir=Path("/tmp/refs"))
        meta.update("Spa-Francorchamps", vehicle_class="Hypercar", vehicle_name="Ferrari 499P")
        self.assertEqual(
            meta.get_profile_filepath(), Path("/tmp/refs/ref_spa-francorchamps_hypercar.json")
        )
        self.assertEqual(
            meta.get_energy_history_filepath(),
            Path("/tmp/refs/ref_spa-francorchamps_hypercar.energy.json"),
        )

    def test_falls_back_to_vehicle_name_when_no_class(self):
        meta = MetadataEngine(base_dir=Path("/tmp/refs"))
        meta.update("Spa", vehicle_class="", vehicle_name="Ferrari 499P")
        self.assertEqual(meta.get_profile_filepath(), Path("/tmp/refs/ref_spa_ferrari_499p.json"))

    def test_falls_back_to_unknown_when_no_identity(self):
        # clean_name_identifier("") already returns "unknown" (not ""), so the
        # `v_identifier or "default"` fallback below it never actually fires —
        # preserved as-is from DeltaEngine._get_profile_filepath()'s original
        # behavior rather than "fixed" as part of this SRP extraction.
        meta = MetadataEngine(base_dir=Path("/tmp/refs"))
        meta.update("Spa", vehicle_class="", vehicle_name="")
        self.assertEqual(meta.get_profile_filepath(), Path("/tmp/refs/ref_spa_unknown.json"))

    def test_update_reports_combo_change(self):
        meta = MetadataEngine(base_dir=Path("/tmp/refs"))
        self.assertTrue(meta.update("Spa", "Hypercar", "Ferrari 499P"))  # first resolution
        self.assertFalse(meta.update("Spa", "Hypercar", "Ferrari 499P"))  # unchanged
        self.assertTrue(meta.update("Monza", "Hypercar", "Ferrari 499P"))  # track changed
        self.assertTrue(meta.update("Monza", "LMP2", "Oreca 07"))  # vehicle changed

    def test_reset_clears_identity_but_keeps_base_dir(self):
        meta = MetadataEngine(base_dir=Path("/tmp/refs"))
        meta.update("Spa", "Hypercar", "Ferrari 499P")
        meta.reset()
        self.assertEqual(meta.track_name, "")
        self.assertEqual(meta.vehicle_class, "")
        self.assertEqual(meta.vehicle_name, "")
        self.assertEqual(meta.base_dir, Path("/tmp/refs"))
        self.assertIsNone(meta.get_profile_filepath())

    def test_base_dir_can_be_updated_dynamically(self):
        meta = MetadataEngine(base_dir=Path("/tmp/refs"))
        meta.update("Spa", "Hypercar", base_dir=Path("/tmp/other"))
        self.assertEqual(meta.get_profile_filepath(), Path("/tmp/other/ref_spa_hypercar.json"))


if __name__ == "__main__":
    unittest.main()
