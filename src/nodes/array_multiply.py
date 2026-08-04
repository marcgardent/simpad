"""
SimPad Nodes — Array Multiply Node.
"""

from typing import Dict, List
from src.nodes.base import BaseNode


class ArrayMultiplyNode(BaseNode):
    """Multiplies N dynamic input signals connected to a single array pin."""

    @property
    def node_type(self) -> str:
        return "array_multiply"

    @property
    def display_name(self) -> str:
        return "Array Multiplier"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        out_attr = ninfo.get("out_attr")
        in_attr = ninfo.get("in_attr")
        sources = in_to_outs.get(in_attr, [])

        lines = [
            f"    # Array Multiplier Node {ntag}",
            f"    array_srcs_{ntag} = {sources}",
            f"    if array_srcs_{ntag}:",
            f"        arr_prod_{ntag} = 1.0",
            f"        for s in array_srcs_{ntag}:",
            f"            arr_prod_{ntag} *= val_map.get(s, 0.0)",
            f"        arr_prod_{ntag} = min(1.0, max(0.0, arr_prod_{ntag}))",
            f"    else:",
            f"        arr_prod_{ntag} = 0.0",
            f"    val_map['{out_attr}'] = arr_prod_{ntag}",
            ""
        ]
        return lines
