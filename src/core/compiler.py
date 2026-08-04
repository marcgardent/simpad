"""
SimPad Haptic Middleware — Graph Compiler Module.
Translates visual Node Editor graph topologies into clean, standalone Python source code
and compiles them into executable bytecode for high-frequency real-time haptic synthesis.
"""

import math
import time
from typing import Dict, Any, List, Tuple, Callable
from src.nodes.factory import NodeFactory


# TODO: [SRP] GraphCompiler delegates individual node code statements generation to NodeFactory.
# TODO: [SLAP] generate_python_source orchestrates high-level code section generation (header, sensors map, node loop, motors output).
class GraphCompiler:
    """Compiles a node graph topology dictionary into executable Python functions."""

    @classmethod
    def generate_python_source(cls, graph_data: dict) -> str:
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
            "    # Input Telemetry Sensors (Combined & Per-Channel)",
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
            "    over_rev  = telemetry.get('over_rev', 0.0)",
            "    under_rev = telemetry.get('under_rev', 0.0)",
            "    rpm_val   = telemetry.get('rpm', 0.0)",
            "    trv_val  = telemetry.get('travel', 0.0)",
            "    trv_l    = telemetry.get('travel_l', trv_val)",
            "    trv_r    = telemetry.get('travel_r', trv_val)",
            "    trv_fl   = telemetry.get('travel_fl', trv_l)",
            "    trv_fr   = telemetry.get('travel_fr', trv_r)",
            "    trv_rl   = telemetry.get('travel_rl', trv_l)",
            "    trv_rr   = telemetry.get('travel_rr', trv_r)",
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
            "        'attr_out_over_rev': over_rev,",
            "        'attr_out_under_rev': under_rev,",
            "        'attr_out_rpm': rpm_val,",
            "        'attr_out_travel': trv_val,",
            "        'attr_out_travel_l': trv_l,",
            "        'attr_out_travel_r': trv_r,",
            "        'attr_out_travel_fl': trv_fl,",
            "        'attr_out_travel_fr': trv_fr,",
            "        'attr_out_travel_rl': trv_rl,",
            "        'attr_out_travel_rr': trv_rr,",
            "    }",
            ""
        ]

        # Process Nodes via NodeFactory delegate
        for ntag, ninfo in nodes.items():
            ntype = ninfo.get("type", "")
            node_lines = NodeFactory.generate_code(ntype, ntag, ninfo, in_to_outs)
            lines.extend(node_lines)

        # Output Motors (Multi-Input Summing Array clamped to [0, 1])
        low_srcs = list(in_to_outs.get('attr_in_low', []))
        high_srcs = list(in_to_outs.get('attr_in_high', []))
        for ntag, ninfo in nodes.items():
            if ninfo.get("type") == "output_xinput":
                in_low = ninfo.get("in_low")
                in_high = ninfo.get("in_high")
                if in_low and in_low in in_to_outs:
                    for s in in_to_outs[in_low]:
                        if s not in low_srcs:
                            low_srcs.append(s)
                if in_high and in_high in in_to_outs:
                    for s in in_to_outs[in_high]:
                        if s not in high_srcs:
                            high_srcs.append(s)

        lines.append("    # Output XInput Vibration Motors (Multi-Input Summing Array clamped to [0,1])")
        lines.append(f"    low_srcs = {low_srcs}")
        lines.append(f"    high_srcs = {high_srcs}")
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
