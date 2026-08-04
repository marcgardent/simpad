"""
SimPad Nodes — Transform & Curve Node.
"""

from typing import Dict, List
from src.nodes.base import BaseNode


class TransformNode(BaseNode):
    """Applies a parametric response curve (Threshold, Gain, Gamma exponent) to an input signal."""

    @property
    def node_type(self) -> str:
        return "transform"

    @property
    def display_name(self) -> str:
        return "Transform & Curve"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        out_attr = ninfo.get("out_attr")
        in_attr = ninfo.get("in_attr")
        gain = float(ninfo.get("gain", 1.0))
        gamma = float(ninfo.get("gamma", 1.0))
        thresh = float(ninfo.get("thresh", 0.0))

        return [
            f"    # Transform & Curve Node {ntag}",
            f"    in_src_{ntag} = {in_to_outs.get(in_attr, [None])}",
            f"    vin_{ntag} = val_map.get(in_src_{ntag}[0], 0.0) if in_src_{ntag} else 0.0",
            f"    if vin_{ntag} < {thresh}:",
            f"        res_{ntag} = 0.0",
            f"    else:",
            f"        norm_x_{ntag} = (vin_{ntag} - {thresh}) / max(0.001, 1.0 - {thresh})",
            f"        res_{ntag} = min(1.0, max(0.0, math.pow(max(0.0, min(1.0, norm_x_{ntag})), {gamma}) * {gain}))",
            f"    val_map['{out_attr}'] = res_{ntag}",
            ""
        ]
