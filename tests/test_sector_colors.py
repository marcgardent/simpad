"""
Contract tests for the single shared sector-split colour rule (racing standard).

purple: split at/below best session split;
pink   : split below personal best only (session not beaten);
default: otherwise.
"""
import unittest
from simpulse.core.telemetry.sector_colors import sector_split_status


class TestSectorSplitColour(unittest.TestCase):
    def test_purple_when_beats_session(self):
        # session best_strict smaller than personal best
        self.assertEqual(sector_split_status(38.0, 42.0, 39.0), "purple")
        self.assertEqual(sector_split_status(38.9, 42.0, 39.0), "purple")

    def test_purple_when_equals_session_record(self):
        self.assertEqual(sector_split_status(39.0, 42.0, 39.0), "purple")

    def test_pink_when_personal_best_only(self):
        # 40.0 is worse than the 39.0 session best but under 42 personal.
        self.assertEqual(sector_split_status(40.0, 42.0, 39.0), "pink")
        self.assertEqual(sector_split_status(41.9, 42.0, 39.0), "pink")

    def test_default_when_no_best_beaten(self):
        self.assertEqual(sector_split_status(43.0, 42.0, 39.0), "default")

    def test_invalid_values_default(self):
        self.assertEqual(sector_split_status(0.0, 42.0, 39.0), "default")
        self.assertEqual(sector_split_status(-2.0, 42.0, 39.0), "default")
        self.assertEqual(sector_split_status(999900.0, 42.0, 39.0), "default")

    def test_solo_equal_record_is_not_purple(self):
        # Solo / no genuine session: personal==session must not claim purple.
        self.assertEqual(sector_split_status(38.437, 38.437, 38.437), "pink")

    def test_absent_best_yields_pink(self):
        # No session reference: only the personal best exists -> pink.
        self.assertEqual(sector_split_status(30.0, 32.0, None), "pink")
        self.assertEqual(sector_split_status(30.0, 32.0, 0.0), "pink")


if __name__ == "__main__":
    unittest.main()
