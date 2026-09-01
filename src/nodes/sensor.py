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
        out_max = ninfo.get("out_attr", "attr_out_abs")
        out_l = ninfo.get("out_l", "attr_out_abs_l")
        out_r = ninfo.get("out_r", "attr_out_abs_r")
        lines = [
            f"    # Sensor Node: Over-Braking ({ntag})",
            "    val_map['attr_out_abs'] = abs_val",
            "    val_map['attr_out_abs_l'] = abs_l",
            "    val_map['attr_out_abs_r'] = abs_r",
        ]
        if out_max != "attr_out_abs": lines.append(f"    val_map['{out_max}'] = abs_val")
        if out_l != "attr_out_abs_l": lines.append(f"    val_map['{out_l}'] = abs_l")
        if out_r != "attr_out_abs_r": lines.append(f"    val_map['{out_r}'] = abs_r")
        lines.append("")
        return lines


class OverAccelSensorNode(BaseNode):
    """Input sensor node for Over-Acceleration (rear wheel power spin)."""

    @property
    def node_type(self) -> str:
        return "sensor_over_accel"

    @property
    def display_name(self) -> str:
        return "Input: Over-Acceleration"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        out_max = ninfo.get("out_attr", "attr_out_tc")
        out_l = ninfo.get("out_l", "attr_out_tc_l")
        out_r = ninfo.get("out_r", "attr_out_tc_r")
        lines = [
            f"    # Sensor Node: Over-Acceleration ({ntag})",
            "    val_map['attr_out_tc'] = tc_val",
            "    val_map['attr_out_tc_l'] = tc_l",
            "    val_map['attr_out_tc_r'] = tc_r",
        ]
        if out_max != "attr_out_tc": lines.append(f"    val_map['{out_max}'] = tc_val")
        if out_l != "attr_out_tc_l": lines.append(f"    val_map['{out_l}'] = tc_l")
        if out_r != "attr_out_tc_r": lines.append(f"    val_map['{out_r}'] = tc_r")
        lines.append("")
        return lines


class OversteerSensorNode(BaseNode):
    """Input sensor node for Oversteer (rear axle lateral slip)."""

    @property
    def node_type(self) -> str:
        return "sensor_oversteer"

    @property
    def display_name(self) -> str:
        return "Input: Oversteer"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        out_max = ninfo.get("out_attr", "attr_out_over")
        out_l = ninfo.get("out_l", "attr_out_over_l")
        out_r = ninfo.get("out_r", "attr_out_over_r")
        lines = [
            f"    # Sensor Node: Oversteer ({ntag})",
            "    val_map['attr_out_over'] = over_val",
            "    val_map['attr_out_over_l'] = over_l",
            "    val_map['attr_out_over_r'] = over_r",
        ]
        if out_max != "attr_out_over": lines.append(f"    val_map['{out_max}'] = over_val")
        if out_l != "attr_out_over_l": lines.append(f"    val_map['{out_l}'] = over_l")
        if out_r != "attr_out_over_r": lines.append(f"    val_map['{out_r}'] = over_r")
        lines.append("")
        return lines


class UndersteerSensorNode(BaseNode):
    """Input sensor node for Understeer (front axle lateral scrub)."""

    @property
    def node_type(self) -> str:
        return "sensor_understeer"

    @property
    def display_name(self) -> str:
        return "Input: Understeer"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        out_max = ninfo.get("out_attr", "attr_out_und")
        out_l = ninfo.get("out_l", "attr_out_und_l")
        out_r = ninfo.get("out_r", "attr_out_und_r")
        lines = [
            f"    # Sensor Node: Understeer ({ntag})",
            "    val_map['attr_out_und'] = und_val",
            "    val_map['attr_out_und_l'] = und_l",
            "    val_map['attr_out_und_r'] = und_r",
        ]
        if out_max != "attr_out_und": lines.append(f"    val_map['{out_max}'] = und_val")
        if out_l != "attr_out_und_l": lines.append(f"    val_map['{out_l}'] = und_l")
        if out_r != "attr_out_und_r": lines.append(f"    val_map['{out_r}'] = und_r")
        lines.append("")
        return lines


class EngineRegimeSensorNode(BaseNode):
    """Input sensor node for Engine Regime (Over-rev / Under-rev / RPM / Gear)."""

    @property
    def node_type(self) -> str:
        return "sensor_engine_regime"

    @property
    def display_name(self) -> str:
        return "Input: Engine Regime"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        out_over = ninfo.get("out_over_rev", "attr_out_over_rev")
        out_under = ninfo.get("out_under_rev", "attr_out_under_rev")
        out_rpm = ninfo.get("out_rpm", "attr_out_rpm")
        out_gear = ninfo.get("out_gear", "attr_out_gear")
        lines = [
            f"    # Sensor Node: Engine Regime ({ntag})",
            "    val_map['attr_out_over_rev'] = over_rev",
            "    val_map['attr_out_under_rev'] = under_rev",
            "    val_map['attr_out_rpm'] = rpm_val",
            "    val_map['attr_out_gear'] = gear_val",
        ]
        if out_over != "attr_out_over_rev": lines.append(f"    val_map['{out_over}'] = over_rev")
        if out_under != "attr_out_under_rev": lines.append(f"    val_map['{out_under}'] = under_rev")
        if out_rpm != "attr_out_rpm": lines.append(f"    val_map['{out_rpm}'] = rpm_val")
        if out_gear != "attr_out_gear": lines.append(f"    val_map['{out_gear}'] = gear_val")
        lines.append("")
        return lines


class GearSensorNode(BaseNode):
    """Input sensor node for Vehicle Gear / Speed."""

    @property
    def node_type(self) -> str:
        return "sensor_gear"

    @property
    def display_name(self) -> str:
        return "Input: Gear"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        out_gear = ninfo.get("out_gear", "attr_out_gear")
        lines = [
            f"    # Sensor Node: Gear ({ntag})",
            "    val_map['attr_out_gear'] = gear_val",
        ]
        if out_gear != "attr_out_gear": lines.append(f"    val_map['{out_gear}'] = gear_val")
        lines.append("")
        return lines


class WheelTravelSensorNode(BaseNode):
    """Input sensor node for Wheel Suspension Travel (4 wheels & Max Left/Right for curbs)."""

    @property
    def node_type(self) -> str:
        return "sensor_wheel_travel"

    @property
    def display_name(self) -> str:
        return "Input: Wheel Travel"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        out_max = ninfo.get("out_attr", "attr_out_travel")
        out_l = ninfo.get("out_l", "attr_out_travel_l")
        out_r = ninfo.get("out_r", "attr_out_travel_r")
        out_fl = ninfo.get("out_fl", "attr_out_travel_fl")
        out_fr = ninfo.get("out_fr", "attr_out_travel_fr")
        out_rl = ninfo.get("out_rl", "attr_out_travel_rl")
        out_rr = ninfo.get("out_rr", "attr_out_travel_rr")
        lines = [
            f"    # Sensor Node: Wheel Travel ({ntag})",
            "    val_map['attr_out_travel'] = trv_val",
            "    val_map['attr_out_travel_l'] = trv_l",
            "    val_map['attr_out_travel_r'] = trv_r",
            "    val_map['attr_out_travel_fl'] = trv_fl",
            "    val_map['attr_out_travel_fr'] = trv_fr",
            "    val_map['attr_out_travel_rl'] = trv_rl",
            "    val_map['attr_out_travel_rr'] = trv_rr",
        ]
        if out_max != "attr_out_travel": lines.append(f"    val_map['{out_max}'] = trv_val")
        if out_l != "attr_out_travel_l": lines.append(f"    val_map['{out_l}'] = trv_l")
        if out_r != "attr_out_travel_r": lines.append(f"    val_map['{out_r}'] = trv_r")
        if out_fl != "attr_out_travel_fl": lines.append(f"    val_map['{out_fl}'] = trv_fl")
        if out_fr != "attr_out_travel_fr": lines.append(f"    val_map['{out_fr}'] = trv_fr")
        if out_rl != "attr_out_travel_rl": lines.append(f"    val_map['{out_rl}'] = trv_rl")
        if out_rr != "attr_out_travel_rr": lines.append(f"    val_map['{out_rr}'] = trv_rr")
        lines.append("")
        return lines


class GripFractSensorNode(BaseNode):
    """Input sensor node for Tire Grip Fraction (unified 4 wheels, left, right clamped 0.0-1.0)."""

    @property
    def node_type(self) -> str:
        return "sensor_grip_fract"

    @property
    def display_name(self) -> str:
        return "Input: Grip Fraction"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        out_max = ninfo.get("out_attr", "attr_out_grip")
        out_l = ninfo.get("out_l", "attr_out_grip_l")
        out_r = ninfo.get("out_r", "attr_out_grip_r")
        lines = [
            f"    # Sensor Node: Grip Fraction ({ntag})",
            "    val_map['attr_out_grip'] = grip_val",
            "    val_map['attr_out_grip_l'] = grip_l",
            "    val_map['attr_out_grip_r'] = grip_r",
        ]
        if out_max != "attr_out_grip": lines.append(f"    val_map['{out_max}'] = grip_val")
        if out_l != "attr_out_grip_l": lines.append(f"    val_map['{out_l}'] = grip_l")
        if out_r != "attr_out_grip_r": lines.append(f"    val_map['{out_r}'] = grip_r")
        lines.append("")
        return lines


class EcuAbsSensorNode(BaseNode):
    """Input sensor node for Official Car ECU ABS (Anti-lock Braking System Active)."""

    @property
    def node_type(self) -> str:
        return "sensor_ecu_abs"

    @property
    def display_name(self) -> str:
        return "Input: Car ECU ABS Active"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        out_attr = ninfo.get("out_attr", "attr_out_ecu_abs")
        lines = [
            f"    # Sensor Node: Car ECU ABS Active ({ntag})",
            "    val_map['attr_out_ecu_abs'] = ecu_abs_val",
        ]
        if out_attr != "attr_out_ecu_abs":
            lines.append(f"    val_map['{out_attr}'] = ecu_abs_val")
        lines.append("")
        return lines


class EcuTcSensorNode(BaseNode):
    """Input sensor node for Official Car ECU TC (Traction Control Active)."""

    @property
    def node_type(self) -> str:
        return "sensor_ecu_tc"

    @property
    def display_name(self) -> str:
        return "Input: Car ECU TC Active"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        out_attr = ninfo.get("out_attr", "attr_out_ecu_tc")
        lines = [
            f"    # Sensor Node: Car ECU TC Active ({ntag})",
            "    val_map['attr_out_ecu_tc'] = ecu_tc_val",
        ]
        if out_attr != "attr_out_ecu_tc":
            lines.append(f"    val_map['{out_attr}'] = ecu_tc_val")
        lines.append("")
        return lines


