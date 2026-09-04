import unittest
from isimotor_rawudp_client import TelemInfo, TelemWheel, TelemVect3
from simpad_qt.core.telemetry.lmu_parser import LMUParser
from simpad_qt.core.physics.effects import PhysicsToHaptic


def make_wheel(lpv=0.0, lgv=0.0, lat_pv=0.0, lat_gv=0.0, susp_deflection=0.0):
    return TelemWheel(
        longitudinal_patch_vel=lpv,
        longitudinal_ground_vel=lgv,
        lateral_patch_vel=lat_pv,
        lateral_ground_vel=lat_gv,
        suspension_deflection=susp_deflection,
    )


class TestLMUMiddleware(unittest.TestCase):

    def test_lmu_parser(self):
        wheels = (
            make_wheel(lpv=0.1, lat_pv=0.5),
            make_wheel(lpv=0.2, lat_pv=0.6),
            make_wheel(lpv=0.3, lat_pv=0.7),
            make_wheel(lpv=0.4, lat_pv=0.8),
        )
        telem = TelemInfo(wheels=wheels)
        parsed = LMUParser.process_telemetry(telem)

        self.assertIsNotNone(parsed)
        self.assertAlmostEqual(parsed.longitudinal_patch_vel[0], 0.1, places=4)
        self.assertAlmostEqual(parsed.longitudinal_patch_vel[3], 0.4, places=4)
        self.assertAlmostEqual(parsed.lateral_patch_vel[2], 0.7, places=4)

    def test_physics_processor(self):
        processor = PhysicsToHaptic()

        # Simulation sous le seuil -> vibrations = 0.0
        telem = TelemInfo(wheels=tuple(make_wheel(0.0, 0.0) for _ in range(4)))
        parsed = LMUParser.process_telemetry(telem)
        l_low, l_high, r_low, r_high = processor.process(parsed)
        self.assertEqual((l_low, l_high, r_low, r_high), (0.0, 0.0, 0.0, 0.0))

        # Simulation ABS Roue Avant Gauche forte (lpv=0.5, lgv=2.0 m/s) -> Haute fréquence Gauche (l_high) > 0.0
        wheels = (
            make_wheel(lpv=0.5, lgv=2.0),
            make_wheel(lpv=2.0, lgv=2.0),
            make_wheel(lpv=2.0, lgv=2.0),
            make_wheel(lpv=2.0, lgv=2.0),
        )
        telem_abs = TelemInfo(
            local_vel=TelemVect3(0.0, 0.0, -2.0),
            wheels=wheels,
            unfiltered_brake=1.0,
        )
        parsed_abs = LMUParser.process_telemetry(telem_abs)
        l_low, l_high, r_low, r_high = processor.process(parsed_abs)
        self.assertGreater(l_high, 0.0)
        self.assertEqual(r_high, 0.0)

    def test_engine_and_travel_telemetry(self):
        wheels = (
            make_wheel(susp_deflection=0.09),
            make_wheel(susp_deflection=0.01),
            make_wheel(susp_deflection=0.05),
            make_wheel(susp_deflection=0.01),
        )
        telem = TelemInfo(
            gear=3,
            engine_rpm=7200.0,
            engine_max_rpm=7500.0,
            wheels=wheels,
        )
        parsed = LMUParser.process_telemetry(telem)
        self.assertIsNotNone(parsed)
        sensors = parsed.to_sensors()
        self.assertAlmostEqual(sensors.engine_rpm, 7200.0)
        self.assertAlmostEqual(sensors.engine_max_rpm, 7500.0)
        self.assertAlmostEqual(sensors.rpm_ratio, 0.96, places=2)
        self.assertGreater(sensors.overrev_intensity, 0.0)
        self.assertAlmostEqual(sensors.travel_left, 0.9, places=2)

    def test_wheel_lockup_detection(self):
        # 100% lockup on Front Left (patch vel = 0.0 while ground vel = 30.0 m/s)
        wheels = (
            make_wheel(lpv=0.0, lgv=30.0),
            make_wheel(lpv=30.0, lgv=30.0),
            make_wheel(lpv=30.0, lgv=30.0),
            make_wheel(lpv=30.0, lgv=30.0),
        )
        telem = TelemInfo(
            local_vel=TelemVect3(0.0, 0.0, -30.0),
            wheels=wheels,
            unfiltered_brake=1.0,
        )
        parsed = LMUParser.process_telemetry(telem)
        self.assertIsNotNone(parsed)
        sensors = parsed.to_sensors()
        self.assertAlmostEqual(sensors.front_left_lock, 1.0, places=2)
        self.assertAlmostEqual(sensors.lock_intensity, 1.0, places=2)

    def test_real_game_frame_integration(self):
        wheels = (
            make_wheel(lpv=-22.115, lgv=-22.115),
            make_wheel(lpv=-22.064, lgv=-22.064),
            make_wheel(lpv=-22.111, lgv=-22.111),
            make_wheel(lpv=-22.069, lgv=-22.069),
        )
        telem = TelemInfo(
            local_vel=TelemVect3(0.0, 0.0, -22.11),
            wheels=wheels,
        )
        parsed = LMUParser.process_telemetry(telem)
        self.assertIsNotNone(parsed)
        sensors = parsed.to_sensors()
        self.assertEqual(sensors.lock_intensity, 0.0)
        self.assertEqual(sensors.spin_intensity, 0.0)

    def test_real_game_frame_22_13(self):
        wheels = (
            make_wheel(lpv=-18.777, lgv=-18.777),
            make_wheel(lpv=-18.699, lgv=-18.699),
            make_wheel(lpv=-18.780, lgv=-18.780),
            make_wheel(lpv=-18.697, lgv=-18.697),
        )
        telem = TelemInfo(
            local_vel=TelemVect3(0.0, 0.0, -18.77),
            wheels=wheels,
        )
        parsed = LMUParser.process_telemetry(telem)
        self.assertIsNotNone(parsed)
        sensors = parsed.to_sensors()
        self.assertEqual(sensors.lock_intensity, 0.0)
        self.assertEqual(sensors.spin_intensity, 0.0)


if __name__ == "__main__":
    unittest.main()


