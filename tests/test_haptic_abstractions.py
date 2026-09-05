import unittest
from simpad_qt.builtin_plugins.haptic_feedback.base import HapticController
from simpad_qt.builtin_plugins.haptic_feedback.mock_controller import MockHapticController
from simpad_qt.builtin_plugins.haptic_feedback.mapper import DirectMixMapper, XInputSeparatedMapper
from simpad_qt.builtin_plugins.haptic_feedback.factory import HapticBackendFactory


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

    def test_sdl3_controller_auto_reconnect_simulation(self):
        from simpad_qt.builtin_plugins.haptic_feedback.sdl3_controller import SDL3HapticController
        from unittest.mock import MagicMock
        import ctypes

        controller = SDL3HapticController()
        mock_sdl = MagicMock()
        controller._sdl_mod = mock_sdl
        controller._sdl_cdll = None

        current_ids = [1001]

        def fake_get_gamepads(count_ptr):
            if count_ptr and current_ids:
                count_ptr._obj.value = len(current_ids)
                return (ctypes.c_uint32 * len(current_ids))(*current_ids)
            elif count_ptr:
                count_ptr._obj.value = 0
            return None

        mock_sdl.SDL_GetGamepads.side_effect = fake_get_gamepads
        mock_sdl.SDL_OpenGamepad.return_value = 0x12345678
        mock_sdl.SDL_GetGamepadName.return_value = b"Xbox Wireless Controller"
        mock_sdl.SDL_GamepadConnected.return_value = True
        mock_sdl.SDL_RumbleGamepad.return_value = True

        # 1. Acquire and test connection
        self.assertTrue(controller.is_connected())
        self.assertEqual(controller.get_gamepad_name(), "Xbox Wireless Controller")

        # 2. Simulate gamepad disconnection (SDL_RumbleGamepad fails or SDL_GamepadConnected returns False)
        mock_sdl.SDL_GamepadConnected.return_value = False
        mock_sdl.SDL_RumbleGamepad.return_value = False
        self.assertFalse(controller._is_handle_alive())

        # When no gamepads are available (controller is OFF)
        current_ids = []
        self.assertFalse(controller.is_connected())
        self.assertEqual(controller.get_gamepad_name(), "No Gamepad")

        # 3. Simulate controller turned back ON (reconnects with new instance id 1002)
        current_ids = [1002]
        mock_sdl.SDL_OpenGamepad.return_value = 0x87654321
        mock_sdl.SDL_GetGamepadName.return_value = b"Xbox Wireless Controller"
        mock_sdl.SDL_GamepadConnected.return_value = True
        mock_sdl.SDL_RumbleGamepad.return_value = True

        # Next call to is_connected or set_vibration immediately recovers
        self.assertTrue(controller.is_connected())
        self.assertEqual(controller.get_gamepad_name(), "Xbox Wireless Controller")

        # Sending vibration succeeds on the new handle
        controller.set_vibration(left_low=0.75, right_high=0.50)
        self.assertEqual(controller.left_low, 0.75)
        self.assertEqual(controller.right_high, 0.50)


    def test_native_windows_xinput_disconnect_reconnect(self):
        from simpad_qt.builtin_plugins.haptic_feedback.windows import NativeWindowsXInputController
        from unittest.mock import MagicMock

        ctrl = NativeWindowsXInputController(device_index=0)
        mock_dll = MagicMock()
        ctrl._dll = mock_dll

        # 1. Connected state (XInputGetState returns ERROR_SUCCESS = 0)
        mock_dll.XInputGetState.return_value = 0
        mock_dll.XInputSetState.return_value = 0
        self.assertTrue(ctrl.is_connected())

        # 2. Disconnected state (controller powers off -> returns 1167)
        mock_dll.XInputGetState.return_value = 1167
        mock_dll.XInputSetState.return_value = 1167
        self.assertFalse(ctrl.is_connected())
        self.assertEqual(ctrl.get_gamepad_name(), "No Gamepad")

        # 3. Reconnected state (controller powers back on -> returns 0)
        mock_dll.XInputGetState.return_value = 0
        mock_dll.XInputSetState.return_value = 0
        self.assertTrue(ctrl.is_connected())
        ctrl.set_vibration(left_low=0.8, right_high=0.6)
        self.assertEqual(ctrl.left_low, 0.8)


if __name__ == "__main__":
    unittest.main()

