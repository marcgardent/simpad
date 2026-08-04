"""
Unit tests for NodeEditor auto-arrange layout algorithm in SimPad.
"""

import unittest
from unittest.mock import MagicMock, patch

# Mock DearPyGui context if headless test environment
try:
    import dearpygui.dearpygui as dpg
except ImportError:
    dpg = None

from src.gui.node_editor import NodeEditorTab


class TestNodeArrangeLayout(unittest.TestCase):

    def setUp(self):
        if dpg:
            dpg.create_context()
            with dpg.window(tag="dummy_test_window"):
                dpg.add_node_editor(tag="node_editor_canvas")
        # Create NodeEditorTab instance with dummy synth engine
        self.synth_engine = MagicMock()
        self.editor = NodeEditorTab(self.synth_engine)
        self.editor.recompile_and_update_synth = MagicMock()

    def tearDown(self):
        if dpg:
            dpg.destroy_context()

    def test_node_dimension_estimator(self):
        """Test node dimension estimates for built-in and custom node types."""
        # Built-in sensors and motors
        w_s, h_s = self.editor._get_node_dimensions("node_sensors")
        self.assertGreater(w_s, 200)
        self.assertGreater(h_s, 400)

        w_m, h_m = self.editor._get_node_dimensions("node_xinput")
        self.assertGreater(w_m, 200)
        self.assertGreater(h_m, 100)

        # Custom registered node types mock
        self.editor._custom_nodes = {
            "node_c1": {"type": "constant", "val": 0.5, "out_attr": "attr_c1"},
            "node_t1": {"type": "transform", "thresh": 0.1, "gain": 1.0, "gamma": 1.0, "in_attr": "attr_in1", "out_attr": "attr_out1"},
            "node_m1": {"type": "math", "op": "Multiply (*)", "in_a": "in_a1", "in_b": "in_b1", "out_attr": "attr_out2"},
            "node_s1": {"type": "shape", "shape": "Square (Pulsed)", "freq": 20.0, "duty": 0.4, "in_attr": "in_s1", "out_attr": "out_s1"}
        }

        dim_c = self.editor._get_node_dimensions("node_c1")
        dim_t = self.editor._get_node_dimensions("node_t1")
        dim_m = self.editor._get_node_dimensions("node_m1")
        dim_s = self.editor._get_node_dimensions("node_s1")

        # Transform and Shape nodes should be taller than basic constant nodes
        self.assertGreater(dim_t[1], dim_c[1])
        self.assertGreater(dim_s[1], dim_c[1])
        self.assertGreater(dim_m[1], dim_c[1])

    @patch("dearpygui.dearpygui.does_item_exist")
    @patch("dearpygui.dearpygui.set_item_pos")
    def test_auto_arrange_non_overlapping(self, mock_set_pos, mock_does_exist):
        """Test auto-arrange places nodes into non-overlapping bounding boxes."""
        mock_does_exist.return_value = True

        self.editor._custom_nodes = {
            "node_t1": {"type": "transform", "in_attr": "t1_in", "out_attr": "t1_out"},
            "node_m1": {"type": "math", "in_a": "m1_a", "in_b": "m1_b", "out_attr": "m1_out"},
            "node_s1": {"type": "shape", "in_attr": "s1_in", "out_attr": "s1_out"}
        }

        # Mock links connecting sensors -> transform -> math -> xinput
        self.editor._node_links = {
            "link_1": ("attr_out_abs", "t1_in"),
            "link_2": ("t1_out", "m1_a"),
            "link_3": ("s1_out", "m1_b"),
            "link_4": ("m1_out", "attr_in_low")
        }

        # Execute auto-arrange
        self.editor.auto_arrange_nodes()

        # Collect set_item_pos calls
        placed_positions = {}
        for call in mock_set_pos.call_args_list:
            ntag, (x, y) = call[0]
            placed_positions[ntag] = (x, y)

        # Ensure all nodes received positions
        expected_nodes = {"node_sensors", "node_t1", "node_m1", "node_s1", "node_xinput"}
        self.assertTrue(expected_nodes.issubset(set(placed_positions.keys())))

        # Verify bounding box separation for all pairs of nodes
        for n1 in expected_nodes:
            for n2 in expected_nodes:
                if n1 >= n2:
                    continue

                x1, y1 = placed_positions[n1]
                w1, h1 = self.editor._get_node_dimensions(n1)

                x2, y2 = placed_positions[n2]
                w2, h2 = self.editor._get_node_dimensions(n2)

                # Bounding boxes check: if they are in the same column (X range overlaps), they must not overlap in Y
                x_overlap = not (x1 + w1 <= x2 or x2 + w2 <= x1)
                y_overlap = not (y1 + h1 <= y2 or y2 + h2 <= y1)

                self.assertFalse(
                    x_overlap and y_overlap,
                    f"Nodes {n1} [x={x1}, y={y1}, w={w1}, h={h1}] and {n2} [x={x2}, y={y2}, w={w2}, h={h2}] overlap!"
                )

    def test_toolbox_button_callback_type_safety(self):
        """Test that node creation callbacks safely handle integer DPG sender IDs."""
        # DPG button callbacks pass sender (int) as first argument
        dpg_sender_id = 12485

        # Should not raise TypeError: 'int' object is not subscriptable
        n1 = self.editor._add_node_constant(dpg_sender_id)
        n2 = self.editor._add_node_float_constant(dpg_sender_id)
        n3 = self.editor._add_node_multiply(dpg_sender_id)
        n4 = self.editor._add_node_array_multiply(dpg_sender_id)
        n5 = self.editor._add_node_normalize(dpg_sender_id)
        n6 = self.editor._add_node_math(dpg_sender_id)
        n7 = self.editor._add_node_transform(dpg_sender_id)
        n8 = self.editor._add_node_shape(dpg_sender_id)

        self.assertIsNotNone(n1)
        self.assertIsNotNone(n2)
        self.assertIsNotNone(n3)
        self.assertIsNotNone(n4)
        self.assertIsNotNone(n5)
        self.assertIsNotNone(n6)
        self.assertIsNotNone(n7)
        self.assertIsNotNone(n8)


if __name__ == "__main__":
    unittest.main()
