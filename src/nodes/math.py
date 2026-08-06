"""
SimPad Nodes — Math Mix Node.
"""

from typing import Dict, List
from src.nodes.base import BaseNode


class MathNode(BaseNode):
    """Applies algebraic operations (Add, Multiply, Subtract, Divide, Min, Max) between two signals."""

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
        val_a = float(ninfo.get("val_a", 0.0))
        val_b = float(ninfo.get("val_b", 0.0))
        op = ninfo.get("op", "Multiply (*)")

        lines = [
            f"    # Math Mix Node {ntag} ({op})",
            f"    src_a_{ntag} = {in_to_outs.get(in_a, [None])}",
            f"    src_b_{ntag} = {in_to_outs.get(in_b, [None])}",
            f"    va_{ntag} = val_map.get(src_a_{ntag}[0], {val_a}) if src_a_{ntag} and src_a_{ntag}[0] else {val_a}",
            f"    vb_{ntag} = val_map.get(src_b_{ntag}[0], {val_b}) if src_b_{ntag} and src_b_{ntag}[0] else {val_b}"
        ]

        if "Add" in op:
            lines.append(f"    res_{ntag} = va_{ntag} + vb_{ntag}")
        elif "Multiply" in op:
            lines.append(f"    res_{ntag} = va_{ntag} * vb_{ntag}")
        elif "Subtract" in op:
            lines.append(f"    res_{ntag} = va_{ntag} - vb_{ntag}")
        elif "Divide" in op:
            lines.append(f"    res_{ntag} = va_{ntag} / (vb_{ntag} if abs(vb_{ntag}) > 1e-5 else 1.0)")
        elif "Min" in op:
            lines.append(f"    res_{ntag} = min(va_{ntag}, vb_{ntag})")
        elif "Max" in op:
            lines.append(f"    res_{ntag} = max(va_{ntag}, vb_{ntag})")
        else:
            lines.append(f"    res_{ntag} = va_{ntag} * vb_{ntag}")

        lines.extend([
            f"    val_map['{out_attr}'] = min(1.0, max(0.0, res_{ntag}))",
            ""
        ])
        return lines
