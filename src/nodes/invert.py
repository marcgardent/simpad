"""
SimPad Nodes — Invert Signal Node.
Inverts a normalized signal [0.0 - 1.0] into [1.0 - 0.0] (1.0 - input).
"""

from typing import Dict, List
from src.nodes.base import BaseNode


class InvertNode(BaseNode):
    """Inverts a normalized signal x [0.0 to 1.0] to (1.0 - x)."""

    @property
    def node_type(self) -> str:
        return "invert"

    @property
    def display_name(self) -> str:
        return "Invert (1 - x)"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        out_attr = ninfo.get("out_attr")
        in_attr = ninfo.get("in_attr")
        val_in = float(ninfo.get("val_in", 0.0))

        return [
            f"    # Invert Node {ntag} (1.0 - x)",
            f"    in_src_{ntag} = {in_to_outs.get(in_attr, [None])}",
            f"    vin_{ntag} = val_map.get(in_src_{ntag}[0], {val_in}) if in_src_{ntag} and in_src_{ntag}[0] else {val_in}",
            f"    val_map['{out_attr}'] = 1.0 - vin_{ntag}",
            ""
        ]
