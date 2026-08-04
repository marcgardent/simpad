"""
SimPad Nodes — Normalize Node.
"""

from typing import Dict, List
from src.nodes.base import BaseNode


class NormalizeNode(BaseNode):
    """Normalizes an unconstrained input signal between min and max bounds."""

    @property
    def node_type(self) -> str:
        return "normalize"

    @property
    def display_name(self) -> str:
        return "Normalize"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        out_attr = ninfo.get("out_attr")
        in_attr = ninfo.get("in_attr")
        min_v = float(ninfo.get("min", 0.0))
        max_v = float(ninfo.get("max", 100.0))
        do_clamp = bool(ninfo.get("clamp", True))
        span = max(0.00001, max_v - min_v)

        lines = [
            f"    # Normalize Node {ntag}",
            f"    in_src_{ntag} = {in_to_outs.get(in_attr, [None])}",
            f"    vin_{ntag} = val_map.get(in_src_{ntag}[0], 0.0) if in_src_{ntag} else 0.0",
            f"    norm_{ntag} = (vin_{ntag} - {min_v}) / {span}"
        ]
        if do_clamp:
            lines.append(f"    norm_{ntag} = min(1.0, max(0.0, norm_{ntag}))")
        lines.extend([
            f"    val_map['{out_attr}'] = norm_{ntag}",
            ""
        ])
        return lines
