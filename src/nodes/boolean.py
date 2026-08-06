"""
SimPad Nodes — Boolean Logic Node.
Applies boolean logic operations (AND, OR, XOR, NOT, NAND, NOR) on two inputs or default values.
Outputs 1.0 (True) or 0.0 (False).
"""

from typing import Dict, List
from src.nodes.base import BaseNode


class BooleanNode(BaseNode):
    """Evaluates boolean logic operations between two signal inputs or constant fallback values."""

    @property
    def node_type(self) -> str:
        return "logic_bool"

    @property
    def display_name(self) -> str:
        return "Boolean Logic"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        out_attr = ninfo.get("out_attr")
        in_a = ninfo.get("in_a")
        in_b = ninfo.get("in_b")
        val_a = float(ninfo.get("val_a", 0.0))
        val_b = float(ninfo.get("val_b", 0.0))
        op = str(ninfo.get("op", "AND")).upper()

        lines = [
            f"    # Boolean Logic Node {ntag} ({op})",
            f"    src_a_{ntag} = {in_to_outs.get(in_a, [None])}",
            f"    src_b_{ntag} = {in_to_outs.get(in_b, [None])}",
            f"    va_{ntag} = val_map.get(src_a_{ntag}[0], {val_a}) if src_a_{ntag} and src_a_{ntag}[0] else {val_a}",
            f"    vb_{ntag} = val_map.get(src_b_{ntag}[0], {val_b}) if src_b_{ntag} and src_b_{ntag}[0] else {val_b}",
            f"    bool_a_{ntag} = (va_{ntag} > 0.0)",
            f"    bool_b_{ntag} = (vb_{ntag} > 0.0)",
        ]

        if "AND" in op and "NAND" not in op:
            lines.append(f"    res_{ntag} = bool_a_{ntag} and bool_b_{ntag}")
        elif "OR" in op and "NOR" not in op and "XOR" not in op:
            lines.append(f"    res_{ntag} = bool_a_{ntag} or bool_b_{ntag}")
        elif "XOR" in op:
            lines.append(f"    res_{ntag} = bool(bool_a_{ntag}) != bool(bool_b_{ntag})")
        elif "NOT" in op and "NAND" not in op and "NOR" not in op:
            lines.append(f"    res_{ntag} = not bool_a_{ntag}")
        elif "NAND" in op:
            lines.append(f"    res_{ntag} = not (bool_a_{ntag} and bool_b_{ntag})")
        elif "NOR" in op:
            lines.append(f"    res_{ntag} = not (bool_a_{ntag} or bool_b_{ntag})")
        else:
            lines.append(f"    res_{ntag} = bool_a_{ntag} and bool_b_{ntag}")

        lines.extend([
            f"    val_map['{out_attr}'] = 1.0 if res_{ntag} else 0.0",
            ""
        ])
        return lines
