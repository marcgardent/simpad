"""
SimPad Nodes — Constant & Float Constant Nodes.
"""

from typing import Dict, List
from src.nodes.base import BaseNode


class ConstantNode(BaseNode):
    """Constant node generating a fixed value clamped to [0,1]."""

    @property
    def node_type(self) -> str:
        return "constant"

    @property
    def display_name(self) -> str:
        return "Constant [0,1]"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        out_attr = ninfo.get("out_attr")
        val = float(ninfo.get("val", 0.5))
        return [
            f"    # Constant Node {ntag}",
            f"    val_map['{out_attr}'] = {val:.4f}",
            ""
        ]


class FloatConstantNode(BaseNode):
    """Float Constant node generating an unconstrained floating-point value (e.g. frequency)."""

    @property
    def node_type(self) -> str:
        return "float_constant"

    @property
    def display_name(self) -> str:
        return "Float Constant"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        out_attr = ninfo.get("out_attr")
        val = float(ninfo.get("val", 0.5))
        return [
            f"    # Float Constant Node {ntag}",
            f"    val_map['{out_attr}'] = {val:.4f}",
            ""
        ]
