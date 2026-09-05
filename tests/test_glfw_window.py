"""
Tests for GLFW window management, screen resolution queries, and overlay window creation.
"""

import unittest
from simpulse.core.utils.glfw_manager import GLFWWindowManager, _GLFW_AVAILABLE
from simpulse.core.utils.window_utils import get_screen_dimensions


class TestGLFWWindow(unittest.TestCase):

    def test_glfw_available(self):
        """Verifies that the glfw Python package is installed and importable."""
        self.assertTrue(_GLFW_AVAILABLE, "The 'glfw' package should be installed and available.")

    def test_glfw_init_and_screen_dimensions(self):
        """Verifies that GLFW initializes and returns valid screen dimensions."""
        width, height = get_screen_dimensions()
        self.assertIsInstance(width, int)
        self.assertIsInstance(height, int)
        self.assertGreater(width, 0, "Screen width must be positive.")
        self.assertGreater(height, 0, "Screen height must be positive.")

    def test_glfw_overlay_window_creation(self):
        """Verifies GLFW transparent overlay window creation with specified window hints."""
        import glfw

        window = GLFWWindowManager.create_overlay_window(
            width=400,
            height=300,
            title="Test SimPulse GLFW Overlay",
            visible=False
        )
        self.assertIsNotNone(window, "GLFW window handle should not be None.")

        # Cleanup window
        glfw.destroy_window(window)

    def test_foreground_window_detection(self):
        """Verifies foreground window title and process name detection functions execute without error."""
        from simpulse.core.utils.window_utils import get_foreground_window_title, get_foreground_process_name, is_lmu_foreground

        title = get_foreground_window_title()
        self.assertIsInstance(title, str)

        proc = get_foreground_process_name()
        self.assertIsInstance(proc, str)

        is_fg = is_lmu_foreground()
        self.assertIsInstance(is_fg, bool)


if __name__ == "__main__":
    unittest.main()
