"""
SimPad Nodes — Telemetry Sensor Input Nodes.
Provides dedicated node definitions for the 4 Telemetry Sensor Inputs:
- Over-Braking (Front Wheel Lockup)
- Over-Acceleration (Rear Wheel Power Spin)
- Oversteer (Rear Axle Lateral Slip)
- Understeer (Front Axle Lateral Scrub)
"""

from typing import Dict, List
from src.nodes.base import BaseNode


class OverBrakingSensorNode(BaseNode):
    """Input sensor node for Over-Braking (front wheel lockup)."""

    @property
    def node_type(self) -> str:
        return "sensor_over_braking"

    @property
    def display_name(self) -> str:
        return "Input: Over-Braking"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        return [
            f"    # Sensor Node: Over-Braking ({ntag})",
            "    val_map['attr_out_abs'] = abs_val",
            "    val_map['attr_out_abs_l'] = abs_l",
            "    val_map['attr_out_abs_r'] = abs_r",
            ""
        ]


class OverAccelSensorNode(BaseNode):
    """Input sensor node for Over-Acceleration (rear wheel power spin)."""

    @property
    def node_type(self) -> str:
        return "sensor_over_accel"

    @property
    def display_name(self) -> str:
        return "Input: Over-Acceleration"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        return [
            f"    # Sensor Node: Over-Acceleration ({ntag})",
            "    val_map['attr_out_tc'] = tc_val",
            "    val_map['attr_out_tc_l'] = tc_l",
            "    val_map['attr_out_tc_r'] = tc_r",
            ""
        ]


class OversteerSensorNode(BaseNode):
    """Input sensor node for Oversteer (rear axle lateral slip)."""

    @property
    def node_type(self) -> str:
        return "sensor_oversteer"

    @property
    def display_name(self) -> str:
        return "Input: Oversteer"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        return [
            f"    # Sensor Node: Oversteer ({ntag})",
            "    val_map['attr_out_over'] = over_val",
            "    val_map['attr_out_over_l'] = over_l",
            "    val_map['attr_out_over_r'] = over_r",
            ""
        ]


class UndersteerSensorNode(BaseNode):
    """Input sensor node for Understeer (front axle lateral scrub)."""

    @property
    def node_type(self) -> str:
        return "sensor_understeer"

    @property
    def display_name(self) -> str:
        return "Input: Understeer"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        return [
            f"    # Sensor Node: Understeer ({ntag})",
            "    val_map['attr_out_und'] = und_val",
            "    val_map['attr_out_und_l'] = und_l",
            "    val_map['attr_out_und_r'] = und_r",
            ""
        ]
