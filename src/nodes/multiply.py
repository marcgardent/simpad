"""
SimPad Nodes — Multiply Node [0,1].
"""

from typing import Dict, List
from src.nodes.base import BaseNode


class MultiplyNode(BaseNode):
    """Multiplies two input signals and clamps the product to [0,1]."""

    @property
    def node_type(self) -> str:
        return "multiply"

    @property
    def display_name(self) -> str:
        return "Multiply [0,1]"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        out_attr = ninfo.get("out_attr")
        in_a = ninfo.get("in_a")
        in_b = ninfo.get("in_b")

        return [
            f"    # Multiply [0,1] Node {ntag}",
            f"    src_a_{ntag} = {in_to_outs.get(in_a, [None])}",
            f"    src_b_{ntag} = {in_to_outs.get(in_b, [None])}",
            f"    va_{ntag} = val_map.get(src_a_{ntag}[0], 0.0) if src_a_{ntag} else 0.0",
            f"    vb_{ntag} = val_map.get(src_b_{ntag}[0], 0.0) if src_b_{ntag} else 0.0",
            f"    val_map['{out_attr}'] = min(1.0, max(0.0, va_{ntag} * vb_{ntag}))",
            ""
        ]
