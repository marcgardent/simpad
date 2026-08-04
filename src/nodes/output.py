"""
SimPad Nodes — Output Nodes.
Provides dedicated node definitions for Haptic Outputs (XInput Vibration Motors).
"""

from typing import Dict, List
from src.nodes.base import BaseNode


class XInputOutputNode(BaseNode):
    """Output node for XInput Vibration Motors (Low Freq Rumble & High Freq Buzz)."""

    @property
    def node_type(self) -> str:
        return "output_xinput"

    @property
    def display_name(self) -> str:
        return "Output: XInput Vibration"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        in_low = ninfo.get("in_low", "attr_in_low")
        in_high = ninfo.get("in_high", "attr_in_high")
        low_srcs = in_to_outs.get(in_low, [])
        high_srcs = in_to_outs.get(in_high, [])
        return [
            f"    # Output XInput Node ({ntag})",
            f"    # low_srcs: {low_srcs}, high_srcs: {high_srcs}",
            ""
        ]
