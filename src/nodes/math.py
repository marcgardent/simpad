"""
SimPad Nodes — Math Mix Node.
"""

from typing import Dict, List
from src.nodes.base import BaseNode


class MathNode(BaseNode):
    """Applies algebraic operations (Add, Multiply, Subtract, Divide) between two signals."""

    @property
    def node_type(self) -> str:
        return "math"

    @property
    def display_name(self) -> str:
        return "Math Mix"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        out_attr = ninfo.get("out_attr")
        in_a = ninfo.get("in_a")
        in_b = ninfo.get("in_b")
        op = ninfo.get("op", "Multiply (*)")

        lines = [
            f"    # Math Mix Node {ntag} ({op})",
            f"    src_a_{ntag} = {in_to_outs.get(in_a, [None])}",
            f"    src_b_{ntag} = {in_to_outs.get(in_b, [None])}",
            f"    va_{ntag} = val_map.get(src_a_{ntag}[0], 0.0) if src_a_{ntag} else 0.0",
            f"    vb_{ntag} = val_map.get(src_b_{ntag}[0], 0.0) if src_b_{ntag} else 0.0"
        ]

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

        lines.extend([
            f"    val_map['{out_attr}'] = min(1.0, max(0.0, res_{ntag}))",
            ""
        ])
        return lines
