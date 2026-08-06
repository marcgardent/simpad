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

        # Simulation ABS Roue Avant Gauche forte (lpv=0.0, lgv=2.0 m/s) -> Haute fréquence Gauche (l_high) > 0.0
        raw_data = struct.pack("<8f", 0.0, 2.0, 2.0, 2.0, 0.0, 0.0, 0.0, 0.0)
        parsed = LMUParser.parse(raw_data)
        l_low, l_high, r_low, r_high = processor.process(parsed)
        self.assertGreater(l_high, 0.0)
        self.assertEqual(r_high, 0.0)


    def test_engine_and_travel_telemetry(self):
        json_data = b'{"Type":"TelemInfoV01","mEngineRPM":7200.0,"mEngineMaxRPM":7500.0,"wheels":[{"mSuspensionVelocity":0.36,"mSuspensionDeflection":0.09},{"mSuspensionDeflection":0.01},{"mSuspensionDeflection":0.05},{"mSuspensionDeflection":0.01}]}'
        parsed = LMUParser.parse(json_data)
        self.assertIsNotNone(parsed)
        sensors = parsed.to_sensors()
        self.assertAlmostEqual(sensors.engine_rpm, 7200.0)
        self.assertAlmostEqual(sensors.engine_max_rpm, 7500.0)
        self.assertAlmostEqual(sensors.rpm_ratio, 0.96, places=2)
        self.assertGreater(sensors.overrev_intensity, 0.0)
        self.assertAlmostEqual(sensors.travel_left, 0.9, places=2)


    def test_wheel_lockup_detection(self):
        # 100% lockup on Front Left (patch vel = 0.0 while vehicle speed = 30.0 m/s)
        json_data = b'{"Type":"TelemInfoV01","mSpeed":30.0,"wheels":[{"mLongitudinalPatchVel":0.0},{"mLongitudinalPatchVel":30.0},{"mLongitudinalPatchVel":30.0},{"mLongitudinalPatchVel":30.0}]}'
        parsed = LMUParser.parse(json_data)
        self.assertIsNotNone(parsed)
        sensors = parsed.to_sensors()
        self.assertAlmostEqual(sensors.front_left_lock, 1.0, places=2)
        self.assertAlmostEqual(sensors.lock_intensity, 1.0, places=2)


    def test_real_game_frame_integration(self):
        # Trame réelle N°4473 enregistrée à 22:09:22 (Vitesse du sol = -22.11 m/s, i.e. 79.6 km/h)
        json_data = b'{"Type":"TelemInfoV01","mSpeed":22.11,"wheels":[{"mLongitudinalPatchVel":-0.7687,"mLongitudinalGroundVel":-22.115},{"mLongitudinalPatchVel":-0.2690,"mLongitudinalGroundVel":-22.064},{"mLongitudinalPatchVel":-1.8841,"mLongitudinalGroundVel":-22.111},{"mLongitudinalPatchVel":-0.6960,"mLongitudinalGroundVel":-22.069}]}'
        parsed = LMUParser.parse(json_data)
        self.assertIsNotNone(parsed)
        sensors = parsed.to_sensors()
        
        # Vérification stricte : en roulement normal à 80 km/h, lock_intensity doit être 0.0 (pas 1.0 !)
        self.assertEqual(sensors.lock_intensity, 0.0)
        self.assertEqual(sensors.spin_intensity, 0.0)


    def test_real_game_frame_22_13(self):
        # Trame N°7255 enregistrée à 22:13:45 (Vitesse du sol = -18.77 m/s (~67.5 km/h))
        # wheels_raw_patch: [-0.6883, -0.2713, -1.6286, -0.6499] rad/s
        # wheels_raw_ground: [-18.777, -18.699, -18.780, -18.697] m/s
        json_data = b'{"Type":"TelemInfoV01","mSpeed":18.77,"wheels":[{"mLongitudinalPatchVel":-0.6883,"mLongitudinalGroundVel":-18.777},{"mLongitudinalPatchVel":-0.2713,"mLongitudinalGroundVel":-18.699},{"mLongitudinalPatchVel":-1.6286,"mLongitudinalGroundVel":-18.780},{"mLongitudinalPatchVel":-0.6499,"mLongitudinalGroundVel":-18.697}]}'
        parsed = LMUParser.parse(json_data)
        self.assertIsNotNone(parsed)
        sensors = parsed.to_sensors()
        
        # En roulement normal à 67 km/h, la voiture ne bloque pas ses roues : lock_intensity = 0.0
        self.assertEqual(sensors.lock_intensity, 0.0)
        self.assertEqual(sensors.spin_intensity, 0.0)


if __name__ == "__main__":
    unittest.main()


