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
    ShapeNode,
    OverBrakingSensorNode,
    OverAccelSensorNode,
    OversteerSensorNode,
    UndersteerSensorNode,
    XInputOutputNode,
)
from src.core.compiler import GraphCompiler


class TestNodeFactoryAndNodes(unittest.TestCase):

    def test_factory_registration(self):
        registered_types = NodeFactory.get_registered_types()
        expected_types = {
            "constant", "float_constant", "multiply", "array_multiply",
            "normalize", "math", "transform", "shape", "logic_bool", "invert",
            "sensor_over_braking", "sensor_over_accel", "sensor_oversteer", "sensor_understeer",
            "sensor_engine_regime", "sensor_wheel_travel", "sensor_gear", "sensor_grip_fract",
            "sensor_electronics",
            "output_xinput"
        }
        self.assertTrue(expected_types.issubset(registered_types))

    def test_invert_node_evaluation(self):
        graph_data = {
            "nodes": {
                "inv_node": {"type": "invert", "val_in": 0.25, "in_attr": "in_pin", "out_attr": "out_inv"},
                "out": {"type": "output_xinput", "in_low": "in_l_pin"}
            },
            "links": [
                ["out_inv", "in_l_pin"]
            ]
        }
        func = GraphCompiler.compile_graph(graph_data)
        low, high = func({}, 0.0)
        self.assertAlmostEqual(low, 0.75, places=4)

    def test_grip_fract_sensor_node_evaluation(self):
        graph_data = {
            "nodes": {
                "grip_node": {"type": "sensor_grip_fract", "out_attr": "out_g", "out_l": "out_gl", "out_r": "out_gr"},
                "out": {"type": "output_xinput", "in_low": "in_l_pin", "in_high": "in_h_pin"}
            },
            "links": [
                ["out_g", "in_l_pin"],
                ["out_gl", "in_h_pin"]
            ]
        }
        func = GraphCompiler.compile_graph(graph_data)
        low, high = func({"grip": 0.85, "grip_l": 0.95, "grip_r": 0.75}, 0.0)
        self.assertAlmostEqual(low, 0.85, places=4)
        self.assertAlmostEqual(high, 0.95, places=4)

    def test_boolean_node_evaluation(self):
        graph_data = {
            "nodes": {
                "bool_and": {"type": "logic_bool", "op": "AND", "val_a": 1.0, "val_b": 1.0, "out_attr": "out_and", "in_a": "in_a", "in_b": "in_b"},
                "bool_or": {"type": "logic_bool", "op": "OR", "val_a": 0.0, "val_b": 1.0, "out_attr": "out_or", "in_a": "in_a2", "in_b": "in_b2"},
                "out": {"type": "output_xinput", "in_low": "in_l_pin", "in_high": "in_h_pin"}
            },
            "links": [
                ["out_and", "in_l_pin"],
                ["out_or", "in_h_pin"]
            ]
        }
        func = GraphCompiler.compile_graph(graph_data)
        low, high = func({}, 0.0)
        self.assertEqual(low, 1.0)
        self.assertEqual(high, 1.0)

    def test_gear_sensor_node_evaluation(self):
        graph_data = {
            "nodes": {
                "gear_node": {"type": "sensor_gear", "out_gear": "out_g"},
                "out": {"type": "output_xinput", "in_low": "in_l_pin"}
            },
            "links": [
                ["out_g", "in_l_pin"]
            ]
        }
        func = GraphCompiler.compile_graph(graph_data)
        low, high = func({"gear": 3.0}, 0.0)
        self.assertEqual(low, 1.0)  # clamped 3.0 -> 1.0

    def test_lmu_parser_and_sensors_realtime_gear(self):
        from src.telemetry.lmu_parser import LMUParser
        from isimotor_rawudp_client import TelemInfo, SystemEvent

        # Garage / exit realtime
        LMUParser.process_system_event(SystemEvent(event_id=2))
        telem_garage = TelemInfo(gear=0, engine_rpm=3000.0, engine_max_rpm=7500.0)
        parsed = LMUParser.process_telemetry(telem_garage)
        self.assertIsNotNone(parsed)
        self.assertFalse(parsed.in_realtime)
        self.assertEqual(parsed.gear, 0)

        sensors = parsed.to_sensors()
        self.assertFalse(sensors.in_realtime)
        self.assertEqual(sensors.underrev_intensity, 0.0)
        self.assertEqual(sensors.overrev_intensity, 0.0)

        # On track, neutral gear -> underrev/overrev must be 0.0
        LMUParser.process_system_event(SystemEvent(event_id=1))
        telem_on_track = TelemInfo(gear=0, engine_rpm=1500.0, engine_max_rpm=7500.0)
        parsed_on_track = LMUParser.process_telemetry(telem_on_track)
        sensors_on_track = parsed_on_track.to_sensors()
        self.assertTrue(sensors_on_track.in_realtime)
        self.assertEqual(sensors_on_track.underrev_intensity, 0.0)


    def test_sensor_nodes_generation(self):
        sensor_types = [
            "sensor_over_braking", "sensor_over_accel", "sensor_oversteer", "sensor_understeer",
            "sensor_engine_regime", "sensor_wheel_travel"
        ]
        for stype in sensor_types:
            node = NodeFactory.get_node(stype)
            self.assertIsNotNone(node)
            lines = node.generate_code(f"test_{stype}", {}, {})
            code_str = "\n".join(lines)
            self.assertIn("val_map[", code_str)

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



    def test_math_node_min_max_evaluation(self):
        graph_data = {
            "nodes": {
                "math_min": {"type": "math", "op": "Min (min)", "val_a": 0.3, "val_b": 0.7, "out_attr": "out_min", "in_a": "in_a", "in_b": "in_b"},
                "math_max": {"type": "math", "op": "Max (max)", "val_a": 0.3, "val_b": 0.7, "out_attr": "out_max", "in_a": "in_a2", "in_b": "in_b2"},
                "out": {"type": "output_xinput", "in_low": "in_l_pin", "in_high": "in_h_pin"}
            },
            "links": [
                ["out_min", "in_l_pin"],
                ["out_max", "in_h_pin"]
            ]
        }
        func = GraphCompiler.compile_graph(graph_data)
        low, high = func({}, 0.0)
        self.assertAlmostEqual(low, 0.3)
        self.assertAlmostEqual(high, 0.7)

    def test_electronics_sensor_node_evaluation(self):
        graph_data = {
            "nodes": {
                "elec_node": {"type": "sensor_electronics", "out_abs": "out_abs_active", "out_tc": "out_tc_active"},
                "out": {"type": "output_xinput", "in_low": "in_l_pin", "in_high": "in_h_pin"}
            },
            "links": [
                ["out_abs_active", "in_l_pin"],
                ["out_tc_active", "in_h_pin"]
            ]
        }
        func = GraphCompiler.compile_graph(graph_data)
        low, high = func({"ecu_abs": 0.85, "ecu_tc": 0.60}, 0.0)
        self.assertAlmostEqual(low, 0.85, places=4)
        self.assertAlmostEqual(high, 0.60, places=4)

    def test_topological_sort_reversed_nodes(self):
        """Verify that nodes defined in reverse dependency order in dict are compiled in topological order."""
        graph_data = {
            "nodes": {
                "out": {"type": "output_xinput", "in_low": "in_l_pin"},
                "shape_node": {"type": "shape", "shape": "Sine (Smooth)", "freq": 20.0, "duty": 1.0, "in_attr": "in_s_pin", "out_attr": "out_s_pin"},
                "tf_node": {"type": "transform", "gain": 1.0, "gamma": 1.0, "thresh": 0.0, "in_attr": "in_tf_pin", "out_attr": "in_s_pin"},
                "elec_node": {"type": "sensor_electronics", "out_abs": "in_tf_pin"}
            },
            "links": [
                ["in_tf_pin", "in_tf_pin"],
                ["in_s_pin", "in_s_pin"],
                ["out_s_pin", "in_l_pin"]
            ]
        }
        func = GraphCompiler.compile_graph(graph_data)
        low, high = func({"ecu_abs": 1.0}, 0.01)
        self.assertGreater(low, 0.0)

    def test_marc_profile_electronics_evaluation(self):
        """Verify that Marc Profile produces vibration output when ECU ABS and TC are active."""
        import json
        with open("profiles/Marc Profile.json") as f:
            data = json.load(f)

        func = GraphCompiler.compile_graph(data["graph_data"])
        low_abs, _ = func({"ecu_abs": 1.0, "ecu_tc": 0.0}, 0.01)
        _, high_tc = func({"ecu_abs": 0.0, "ecu_tc": 1.0}, 0.01)
        self.assertGreater(low_abs, 0.0)
        self.assertGreater(high_tc, 0.0)


if __name__ == "__main__":
    unittest.main()

