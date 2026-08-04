"""
Unit tests for dedicated nodes and NodeFactory in SimPad.
"""

import unittest
from src.nodes import (
    NodeFactory,
    ConstantNode,
    FloatConstantNode,
    MultiplyNode,
    ArrayMultiplyNode,
    NormalizeNode,
    MathNode,
    TransformNode,
    ShapeNode
)
from src.core.compiler import GraphCompiler


class TestNodeFactoryAndNodes(unittest.TestCase):

    def test_factory_registration(self):
        registered_types = NodeFactory.get_registered_types()
        expected_types = {
            "constant", "float_constant", "multiply", "array_multiply",
            "normalize", "math", "transform", "shape"
        }
        self.assertTrue(expected_types.issubset(registered_types))

    def test_constant_node_generation(self):
        node = NodeFactory.get_node("constant")
        self.assertIsNotNone(node)
        lines = node.generate_code("node_1", {"out_attr": "attr_1", "val": 0.75}, {})
        code_str = "\n".join(lines)
        self.assertIn("val_map['attr_1'] = 0.7500", code_str)

    def test_multiply_node_generation(self):
        node = NodeFactory.get_node("multiply")
        self.assertIsNotNone(node)
        lines = node.generate_code("node_2", {"out_attr": "attr_out", "in_a": "in_a_pin", "in_b": "in_b_pin"}, {"in_a_pin": ["src_a"], "in_b_pin": ["src_b"]})
        code_str = "\n".join(lines)
        self.assertIn("min(1.0, max(0.0, va_node_2 * vb_node_2))", code_str)

    def test_transform_node_generation(self):
        node = NodeFactory.get_node("transform")
        self.assertIsNotNone(node)
        lines = node.generate_code("node_3", {"out_attr": "attr_out", "in_attr": "in_pin", "gain": 1.5, "gamma": 2.0, "thresh": 0.1}, {"in_pin": ["src_pin"]})
        code_str = "\n".join(lines)
        self.assertIn("math.pow", code_str)

    def test_full_graph_compilation_with_factory(self):
        graph_data = {
            "nodes": {
                "node_1": {"type": "constant", "val": 0.8, "out_attr": "out_c1"},
                "node_2": {"type": "transform", "in_attr": "in_t1", "out_attr": "out_t1", "gain": 1.0, "gamma": 1.0, "thresh": 0.0}
            },
            "links": [
                ["attr_out_abs", "in_t1"],
                ["out_t1", "attr_in_low"]
            ]
        }
        func = GraphCompiler.compile_graph(graph_data)
        self.assertTrue(callable(func))

        low_val, high_val = func({"abs": 0.5}, 0.0)
        self.assertAlmostEqual(low_val, 0.5, places=4)
        self.assertEqual(high_val, 0.0)


if __name__ == "__main__":
    unittest.main()
