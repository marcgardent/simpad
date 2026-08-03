"""
SimPad Haptic Middleware — Graph Compiler Module.
Translates visual Node Editor graph topologies into clean, standalone Python source code
and compiles them into executable bytecode for high-frequency real-time haptic synthesis.
"""

import math
import time
from typing import Dict, Any, List, Tuple, Callable


class GraphCompiler:
    """Compiles a node graph topology dictionary into executable Python functions."""

    @staticmethod
    def generate_python_source(graph_data: dict) -> str:
        """
        Generates standalone, human-readable Python source code from the node graph data.
        Signature: def evaluate_haptics(telemetry: dict, t: float) -> Tuple[float, float]
        """
        nodes = graph_data.get("nodes", {})
        links = graph_data.get("links", [])  # List of (attr_out, attr_in)

        # Build link mapping: target_input -> list of source_outputs
        in_to_outs: Dict[str, List[str]] = {}
        for src_out, tgt_in in links:
            if tgt_in not in in_to_outs:
                in_to_outs[tgt_in] = []
            in_to_outs[tgt_in].append(src_out)

        lines = [
            "import math",
            "",
            "def evaluate_haptics(telemetry: dict, t: float):",
            "    # Input Telemetry Sensors (Combined & Left/Right Channels)",
            "    abs_val  = telemetry.get('abs', 0.0)",
            "    abs_l    = telemetry.get('abs_l', abs_val)",
            "    abs_r    = telemetry.get('abs_r', abs_val)",
            "    tc_val   = telemetry.get('tc', 0.0)",
            "    tc_l     = telemetry.get('tc_l', tc_val)",
            "    tc_r     = telemetry.get('tc_r', tc_val)",
            "    over_val = telemetry.get('oversteer', 0.0)",
            "    over_l   = telemetry.get('over_l', over_val)",
            "    over_r   = telemetry.get('over_r', over_val)",
            "    und_val  = telemetry.get('understeer', 0.0)",
            "    und_l    = telemetry.get('und_l', und_val)",
            "    und_r    = telemetry.get('und_r', und_val)",
            "",
            "    val_map = {",
            "        'attr_out_abs': abs_val,",
            "        'attr_out_abs_l': abs_l,",
            "        'attr_out_abs_r': abs_r,",
            "        'attr_out_tc': tc_val,",
            "        'attr_out_tc_l': tc_l,",
            "        'attr_out_tc_r': tc_r,",
            "        'attr_out_over': over_val,",
            "        'attr_out_over_l': over_l,",
            "        'attr_out_over_r': over_r,",
            "        'attr_out_und': und_val,",
            "        'attr_out_und_l': und_l,",
            "        'attr_out_und_r': und_r,",
            "    }",
            ""
        ]

        # Process Nodes
        for ntag, ninfo in nodes.items():
            ntype = ninfo.get("type")
            out_attr = ninfo.get("out_attr")

            if ntype in ["constant", "float_constant"]:
                v = float(ninfo.get("val", 0.5))
                lines.append(f"    # Constant Node {ntag}")
                lines.append(f"    val_map['{out_attr}'] = {v:.4f}")
                lines.append("")

            elif ntype == "normalize":
                in_attr = ninfo.get("in_attr")
                min_v = float(ninfo.get("min", 0.0))
                max_v = float(ninfo.get("max", 100.0))
                do_clamp = bool(ninfo.get("clamp", True))
                span = max(0.00001, max_v - min_v)

                lines.append(f"    # Normalize Node {ntag}")
                lines.append(f"    in_src_{ntag} = {in_to_outs.get(in_attr, [None])}")
                lines.append(f"    vin_{ntag} = val_map.get(in_src_{ntag}[0], 0.0) if in_src_{ntag} else 0.0")
                lines.append(f"    norm_{ntag} = (vin_{ntag} - {min_v}) / {span}")
                if do_clamp:
                    lines.append(f"    norm_{ntag} = min(1.0, max(0.0, norm_{ntag}))")
                lines.append(f"    val_map['{out_attr}'] = norm_{ntag}")
                lines.append("")

            elif ntype == "math":
                in_a = ninfo.get("in_a")
                in_b = ninfo.get("in_b")
                op = ninfo.get("op", "Multiply (*)")

                lines.append(f"    # Math Mix Node {ntag} ({op})")
                lines.append(f"    src_a = {in_to_outs.get(in_a, [None])}")
                lines.append(f"    src_b = {in_to_outs.get(in_b, [None])}")
                lines.append(f"    va_{ntag} = val_map.get(src_a[0], 0.0) if src_a else 0.0")
                lines.append(f"    vb_{ntag} = val_map.get(src_b[0], 0.0) if src_b else 0.0")

                if "Add" in op:
                    lines.append(f"    res_{ntag} = va_{ntag} + vb_{ntag}")
                elif "Multiply" in op:
                    lines.append(f"    res_{ntag} = va_{ntag} * vb_{ntag}")
                elif "Subtract" in op:
                    lines.append(f"    res_{ntag} = va_{ntag} - vb_{ntag}")
                elif "Divide" in op:
                    lines.append(f"    res_{ntag} = va_{ntag} / (vb_{ntag} if abs(vb_{ntag}) > 1e-5 else 1.0)")
                else:
                    lines.append(f"    res_{ntag} = va_{ntag} * vb_{ntag}")

                lines.append(f"    val_map['{out_attr}'] = min(1.0, max(0.0, res_{ntag}))")
                lines.append("")

            elif ntype == "multiply":
                in_a = ninfo.get("in_a")
                in_b = ninfo.get("in_b")

                lines.append(f"    # Multiply [0,1] Node {ntag}")
                lines.append(f"    src_a = {in_to_outs.get(in_a, [None])}")
                lines.append(f"    src_b = {in_to_outs.get(in_b, [None])}")
                lines.append(f"    va_{ntag} = val_map.get(src_a[0], 0.0) if src_a else 0.0")
                lines.append(f"    vb_{ntag} = val_map.get(src_b[0], 0.0) if src_b else 0.0")
                lines.append(f"    val_map['{out_attr}'] = min(1.0, max(0.0, va_{ntag} * vb_{ntag}))")
                lines.append("")

            elif ntype == "array_multiply":
                in_attr = ninfo.get("in_attr")
                sources = in_to_outs.get(in_attr, [])

                lines.append(f"    # Array Multiplier Node {ntag}")
                lines.append(f"    array_srcs_{ntag} = {sources}")
                lines.append(f"    if array_srcs_{ntag}:")
                lines.append(f"        arr_prod_{ntag} = 1.0")
                lines.append(f"        for s in array_srcs_{ntag}:")
                lines.append(f"            arr_prod_{ntag} *= val_map.get(s, 0.0)")
                lines.append(f"        arr_prod_{ntag} = min(1.0, max(0.0, arr_prod_{ntag}))")
                lines.append(f"    else:")
                lines.append(f"        arr_prod_{ntag} = 0.0")
                lines.append(f"    val_map['{out_attr}'] = arr_prod_{ntag}")
                lines.append("")

            elif ntype == "transform":
                in_attr = ninfo.get("in_attr")
                gain = float(ninfo.get("gain", 1.0))
                gamma = float(ninfo.get("gamma", 1.0))
                thresh = float(ninfo.get("thresh", 0.0))

                lines.append(f"    # Transform & Curve Node {ntag}")
                lines.append(f"    in_src_{ntag} = {in_to_outs.get(in_attr, [None])}")
                lines.append(f"    vin_{ntag} = val_map.get(in_src_{ntag}[0], 0.0) if in_src_{ntag} else 0.0")
                lines.append(f"    if vin_{ntag} < {thresh}:")
                lines.append(f"        res_{ntag} = 0.0")
                lines.append(f"    else:")
                lines.append(f"        norm_x_{ntag} = (vin_{ntag} - {thresh}) / max(0.001, 1.0 - {thresh})")
                lines.append(f"        res_{ntag} = min(1.0, max(0.0, math.pow(max(0.0, min(1.0, norm_x_{ntag})), {gamma}) * {gain}))")
                lines.append(f"    val_map['{out_attr}'] = res_{ntag}")
                lines.append("")

            elif ntype == "shape":
                shape_choice = ninfo.get("shape", "Square (Pulsed)")
                base_freq = float(ninfo.get("freq", 20.0))
                base_duty = float(ninfo.get("duty", 0.40))
                in_attr = ninfo.get("in_attr")
                in_freq = ninfo.get("in_freq")

                lines.append(f"    # Waveform Shape Node {ntag} ({shape_choice})")
                lines.append(f"    in_src_{ntag} = {in_to_outs.get(in_attr, [None])}")
                lines.append(f"    in_freq_src_{ntag} = {in_to_outs.get(in_freq, [None])}")
                lines.append(f"    vin_{ntag} = val_map.get(in_src_{ntag}[0], 0.0) if in_src_{ntag} else 0.0")
                lines.append(f"    freq_{ntag} = float(val_map.get(in_freq_src_{ntag}[0], {base_freq})) if in_freq_src_{ntag} else {base_freq}")
                lines.append(f"    freq_{ntag} = max(0.1, freq_{ntag})")
                lines.append(f"    duty_{ntag} = max(0.01, min(1.0, {base_duty:.4f}))")
                lines.append(f"    if vin_{ntag} > 0.01:")
                lines.append(f"        period_s_{ntag} = 1.0 / freq_{ntag}")
                lines.append(f"        phase_{ntag} = (t % period_s_{ntag}) / period_s_{ntag}")
                lines.append(f"        if phase_{ntag} <= duty_{ntag}:")
                lines.append(f"            phi_{ntag} = phase_{ntag} / max(0.001, duty_{ntag})")
                if "Square" in shape_choice:
                    lines.append(f"            mod_{ntag} = 1.0")
                elif "Sawtooth" in shape_choice:
                    lines.append(f"            mod_{ntag} = phi_{ntag}")
                elif "Sine" in shape_choice:
                    lines.append(f"            mod_{ntag} = 0.5 * (1.0 + math.sin(2.0 * math.pi * phi_{ntag} - math.pi / 2.0))")
                elif "Burst" in shape_choice:
                    lines.append(f"            mod_{ntag} = math.exp(-4.0 * phi_{ntag})")
                else:
                    lines.append(f"            mod_{ntag} = 1.0")
                lines.append(f"        else:")
                lines.append(f"            mod_{ntag} = 0.0")
                lines.append(f"        res_{ntag} = min(1.0, max(0.0, vin_{ntag} * mod_{ntag}))")
                lines.append(f"    else:")
                lines.append(f"        res_{ntag} = 0.0")
                lines.append(f"    val_map['{out_attr}'] = res_{ntag}")
                lines.append("")

        # Output Motors (Multi-Input Summing Array clamped to [0, 1])
        lines.append("    # Output XInput Vibration Motors (Multi-Input Summing Array clamped to [0,1])")
        lines.append(f"    low_srcs = {in_to_outs.get('attr_in_low', [])}")
        lines.append(f"    high_srcs = {in_to_outs.get('attr_in_high', [])}")
        lines.append("    low_val = min(1.0, max(0.0, sum(val_map.get(s, 0.0) for s in low_srcs))) if low_srcs else 0.0")
        lines.append("    high_val = min(1.0, max(0.0, sum(val_map.get(s, 0.0) for s in high_srcs))) if high_srcs else 0.0")
        lines.append("    return low_val, high_val")
        lines.append("")

        return "\n".join(lines)

    @classmethod
    def compile_graph(cls, graph_data: dict) -> Callable[[dict, float], Tuple[float, float]]:
        """
        Compiles the graph topology into an in-memory executable Python function object.
        Returns a callable function: evaluate_haptics(telemetry: dict, t: float) -> (low_val, high_val)
        """
        py_source = cls.generate_python_source(graph_data)
        code_obj = compile(py_source, filename="<simpad_graph_compiled>", mode="exec")

        namespace: Dict[str, Any] = {"math": math}
        exec(code_obj, namespace)

        func = namespace.get("evaluate_haptics")
        if not callable(func):
            raise RuntimeError("Compiled graph did not produce a callable evaluate_haptics function.")
        return func
