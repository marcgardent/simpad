import unittest
from src.haptics.base import HapticController
from src.haptics.mock_controller import MockHapticController
from src.haptics.mapper import DirectMixMapper, XInputSeparatedMapper
from src.haptics.factory import HapticBackendFactory


class TestHapticAbstractions(unittest.TestCase):

    def test_mock_controller(self):
        controller = MockHapticController()
        self.assertTrue(controller.is_connected())
        self.assertEqual(controller.get_gamepad_name(), "SimPad Virtual Gamepad (Mock)")

        controller.set_vibration(0.5, 0.2, 0.1, 0.8, duration_ms=100)
        self.assertEqual(controller.left_low, 0.5)
        self.assertEqual(controller.left_high, 0.2)
        self.assertEqual(controller.right_low, 0.1)
        self.assertEqual(controller.right_high, 0.8)

        controller.stop()
        self.assertEqual(controller.left_low, 0.0)

    def test_direct_mix_mapper(self):
        mapper = DirectMixMapper()
        lf, hf = mapper.map_channels(0.3, 0.4, 0.2, 0.5)
        self.assertAlmostEqual(lf, 0.7)
        self.assertAlmostEqual(hf, 0.7)

        # Test clipping
        lf_clip, hf_clip = mapper.map_channels(0.8, 0.5, 0.9, 0.9)
        self.assertEqual(lf_clip, 1.0)
        self.assertEqual(hf_clip, 1.0)

    def test_xinput_separated_mapper(self):
        mapper = XInputSeparatedMapper()
        lf, hf = mapper.map_channels(left_low=0.6, left_high=0.0, right_low=0.2, right_high=0.8)
        # unified_low = max(0.6, 0.2) = 0.6
        # unified_high = max(0.0, 0.8) = 0.8
        self.assertAlmostEqual(lf, 0.6)
        self.assertAlmostEqual(hf, 0.8)

    def test_factory_force_mock(self):
        backend = HapticBackendFactory.create_backend(force_mock=True)
        self.assertIsInstance(backend, MockHapticController)
        self.assertTrue(backend.is_connected())

    def test_synthesizer_slider_retention(self):
        from src.core.synthesizer import HapticSynthesizerEngine

        mock_backend = MockHapticController()
        synth = HapticSynthesizerEngine(mock_backend)

        def dummy_compiler(telemetry, t):
            # Returns low_out = abs_l, high_out = tc_r
            return telemetry.get("abs_l", 0.0), telemetry.get("tc_r", 0.0)

        synth.set_compiled_func(dummy_compiler)

        # Simulate user moving slider
        synth.update_telemetry(abs_l=0.75, tc_r=0.40, in_realtime=True)

        # Output check
        low, high = synth.get_current_outputs()
        self.assertEqual(synth._telemetry["abs_l"], 0.75)
        self.assertEqual(synth._telemetry["tc_r"], 0.40)


if __name__ == "__main__":
    unittest.main()
