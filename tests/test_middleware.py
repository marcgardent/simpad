import unittest
import struct
from src.telemetry.lmu_parser import LMUParser
from src.physics.effects import PhysicsToHaptic
from src.core.config import DEFAULT_CONFIG


class TestLMUMiddleware(unittest.TestCase):

    def test_lmu_parser(self):
        # 4 floats long_vel (0.1, 0.2, 0.3, 0.4) + 4 floats lat_vel (0.5, 0.6, 0.7, 0.8)
        raw_data = struct.pack("<8f", 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)
        parsed = LMUParser.parse(raw_data)

        self.assertIsNotNone(parsed)
        self.assertAlmostEqual(parsed.longitudinal_patch_vel[0], 0.1, places=4)
        self.assertAlmostEqual(parsed.longitudinal_patch_vel[3], 0.4, places=4)
        self.assertAlmostEqual(parsed.lateral_patch_vel[2], 0.7, places=4)

    def test_physics_processor(self):
        processor = PhysicsToHaptic(DEFAULT_CONFIG)

        # Simulation sous le seuil -> vibrations = 0.0
        raw_data = struct.pack("<8f", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        parsed = LMUParser.parse(raw_data)
        l_low, l_high, r_low, r_high = processor.process(parsed)
        self.assertEqual((l_low, l_high, r_low, r_high), (0.0, 0.0, 0.0, 0.0))

        # Simulation ABS Roue Avant Gauche forte -> Haute fréquence Gauche (l_high) > 0.0
        raw_data = struct.pack("<8f", 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        parsed = LMUParser.parse(raw_data)
        l_low, l_high, r_low, r_high = processor.process(parsed)
        self.assertGreater(l_high, 0.0)
        self.assertEqual(r_high, 0.0)


if __name__ == "__main__":
    unittest.main()
