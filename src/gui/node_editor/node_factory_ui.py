"""
SimPad Haptic Middleware — Node UI Factory.
Handles DearPyGui node widget creation, pin themes, unique node IDs, and plot visualizer updates.
"""

import math
import dearpygui.dearpygui as dpg
from typing import Dict, Any, List, Optional, Tuple, Callable
from src.core.math_utils import apply_response_curve


class NodeUIFactory:
    """Factory responsible for creating node GUI widgets and applying pin themes."""

    def __init__(self):
        self._node_id_counter = 0

    def apply_pin_theme(self, attr_tag: str, pin_type: Any = "normalized", is_normalized: Optional[bool] = None, is_square: bool = False):
        """Applies color themes to node attribute pins based on data type."""
        if is_normalized is not None:
            pin_type = "normalized" if is_normalized else "float"
        if not dpg.does_item_exist(attr_tag):
            return
        theme_tag = f"theme_pin_{attr_tag}"
        if dpg.does_item_exist(theme_tag):
            dpg.delete_item(theme_tag)

        if pin_type == "normalized":
            pin_col = [255, 220, 0, 255]
            hover_col = [255, 240, 100, 255]
        elif pin_type == "float":
            pin_col = [0, 162, 255, 255]
            hover_col = [80, 200, 255, 255]
        elif pin_type == "array":
            pin_col = [255, 140, 0, 255]
            hover_col = [255, 180, 50, 255]
        elif pin_type in ["sum_array", "red"]:
            pin_col = [255, 60, 60, 255]
            hover_col = [255, 120, 120, 255]
        else:
            pin_col = [180, 180, 180, 255]
            hover_col = [220, 220, 220, 255]

        with dpg.theme(tag=theme_tag):
            with dpg.theme_component(dpg.mvNodeAttribute):
                dpg.add_theme_color(dpg.mvNodeCol_Pin, pin_col, category=dpg.mvThemeCat_Nodes)
                dpg.add_theme_color(dpg.mvNodeCol_PinHovered, hover_col, category=dpg.mvThemeCat_Nodes)
        dpg.bind_item_theme(attr_tag, theme_tag)

    def get_next_nid(self, custom_nodes: Dict[str, dict]) -> int:
        """Returns a guaranteed unique node ID counter value free of any DPG item conflicts."""
        self._node_id_counter += 1
        while True:
            nid = self._node_id_counter
            check_tags = [
                f"dynamic_node_const_{nid}", f"val_dyn_const_{nid}",
                f"dynamic_node_float_const_{nid}", f"val_dyn_float_const_{nid}",
                f"dynamic_node_mult_{nid}",
                f"dynamic_node_array_mult_{nid}",
                f"dynamic_node_norm_{nid}",
                f"dynamic_node_math_{nid}",
                f"dynamic_node_tf_{nid}",
                f"dynamic_node_shape_{nid}", f"pulse_on_ms_{nid}", f"pulse_off_ms_{nid}"
            ]
            if any(dpg.does_item_exist(t) for t in check_tags):
                self._node_id_counter += 1
            else:
                break
        return self._node_id_counter

    def get_next_spawn_pos(self, custom_nodes: Dict[str, dict], requested_pos: Any = None) -> List[float]:
        """Calculates a non-overlapping spawn position for new nodes added from Toolbox."""
        if isinstance(requested_pos, (tuple, list)) and len(requested_pos) >= 2:
            x, y = float(requested_pos[0]), float(requested_pos[1])
        else:
            x, y = 280.0, 60.0

        existing_positions = []
        for ntag in custom_nodes.keys():
            if dpg.does_item_exist(ntag):
                pos = dpg.get_item_pos(ntag)
                existing_positions.append((pos[0], pos[1]))

        step = 0
        while any(abs(ex - x) < 30 and abs(ey - y) < 30 for ex, ey in existing_positions):
            step += 1
            x += 35.0
            y += 35.0
            if y > 450.0:
                y = 60.0
                x += 50.0

        return [float(x), float(y)]

    # ── Toolbox Node Creation Builders ───────────────────────────────────────
    def add_node_sensor_abs(self, custom_nodes: Dict[str, dict], recompile_cb: Callable[[], None], pos=(30.0, 40.0)) -> str:
        pos_f = self.get_next_spawn_pos(custom_nodes, pos)
        nid = self.get_next_nid(custom_nodes)
        node_tag = f"dynamic_node_sensor_abs_{nid}"
        out_max_tag = f"attr_out_dyn_abs_{nid}"
        out_l_tag = f"attr_out_dyn_abs_l_{nid}"
        out_r_tag = f"attr_out_dyn_abs_r_{nid}"

        with dpg.node(label=f"Input: Over-Braking #{nid}", tag=node_tag, parent="node_editor_canvas", pos=pos_f):
            with dpg.node_attribute(label="Over-Braking Max", attribute_type=dpg.mvNode_Attr_Output, tag=out_max_tag):
                dpg.add_text("Over-Braking (Max)", color=[255, 220, 0, 255])
            with dpg.node_attribute(label="Over-Braking Left", attribute_type=dpg.mvNode_Attr_Output, tag=out_l_tag):
                dpg.add_text("Over-Braking (Left)", color=[255, 220, 0, 255])
            with dpg.node_attribute(label="Over-Braking Right", attribute_type=dpg.mvNode_Attr_Output, tag=out_r_tag):
                dpg.add_text("Over-Braking (Right)", color=[255, 220, 0, 255])

        for pin in [out_max_tag, out_l_tag, out_r_tag]:
            self.apply_pin_theme(pin, "normalized")

        custom_nodes[node_tag] = {
            "type": "sensor_over_braking",
            "out_attr": out_max_tag,
            "out_l": out_l_tag,
            "out_r": out_r_tag,
        }
        recompile_cb()
        return node_tag

    def add_node_sensor_tc(self, custom_nodes: Dict[str, dict], recompile_cb: Callable[[], None], pos=(30.0, 160.0)) -> str:
        pos_f = self.get_next_spawn_pos(custom_nodes, pos)
        nid = self.get_next_nid(custom_nodes)
        node_tag = f"dynamic_node_sensor_tc_{nid}"
        out_max_tag = f"attr_out_dyn_tc_{nid}"
        out_l_tag = f"attr_out_dyn_tc_l_{nid}"
        out_r_tag = f"attr_out_dyn_tc_r_{nid}"

        with dpg.node(label=f"Input: Over-Acceleration #{nid}", tag=node_tag, parent="node_editor_canvas", pos=pos_f):
            with dpg.node_attribute(label="Over-Accel Max", attribute_type=dpg.mvNode_Attr_Output, tag=out_max_tag):
                dpg.add_text("Over-Accel (Max)", color=[255, 220, 0, 255])
            with dpg.node_attribute(label="Over-Accel Left", attribute_type=dpg.mvNode_Attr_Output, tag=out_l_tag):
                dpg.add_text("Over-Accel (Left)", color=[255, 220, 0, 255])
            with dpg.node_attribute(label="Over-Accel Right", attribute_type=dpg.mvNode_Attr_Output, tag=out_r_tag):
                dpg.add_text("Over-Accel (Right)", color=[255, 220, 0, 255])

        for pin in [out_max_tag, out_l_tag, out_r_tag]:
            self.apply_pin_theme(pin, "normalized")

        custom_nodes[node_tag] = {
            "type": "sensor_over_accel",
            "out_attr": out_max_tag,
            "out_l": out_l_tag,
            "out_r": out_r_tag,
        }
        recompile_cb()
        return node_tag

    def add_node_sensor_over(self, custom_nodes: Dict[str, dict], recompile_cb: Callable[[], None], pos=(30.0, 280.0)) -> str:
        pos_f = self.get_next_spawn_pos(custom_nodes, pos)
        nid = self.get_next_nid(custom_nodes)
        node_tag = f"dynamic_node_sensor_over_{nid}"
        out_max_tag = f"attr_out_dyn_over_{nid}"
        out_l_tag = f"attr_out_dyn_over_l_{nid}"
        out_r_tag = f"attr_out_dyn_over_r_{nid}"

        with dpg.node(label=f"Input: Oversteer #{nid}", tag=node_tag, parent="node_editor_canvas", pos=pos_f):
            with dpg.node_attribute(label="Oversteer Max", attribute_type=dpg.mvNode_Attr_Output, tag=out_max_tag):
                dpg.add_text("Oversteer (Max)", color=[255, 220, 0, 255])
            with dpg.node_attribute(label="Oversteer Left", attribute_type=dpg.mvNode_Attr_Output, tag=out_l_tag):
                dpg.add_text("Oversteer (Left)", color=[255, 220, 0, 255])
            with dpg.node_attribute(label="Oversteer Right", attribute_type=dpg.mvNode_Attr_Output, tag=out_r_tag):
                dpg.add_text("Oversteer (Right)", color=[255, 220, 0, 255])

        for pin in [out_max_tag, out_l_tag, out_r_tag]:
            self.apply_pin_theme(pin, "normalized")

        custom_nodes[node_tag] = {
            "type": "sensor_oversteer",
            "out_attr": out_max_tag,
            "out_l": out_l_tag,
            "out_r": out_r_tag,
        }
        recompile_cb()
        return node_tag

    def add_node_sensor_und(self, custom_nodes: Dict[str, dict], recompile_cb: Callable[[], None], pos=(30.0, 400.0)) -> str:
        pos_f = self.get_next_spawn_pos(custom_nodes, pos)
        nid = self.get_next_nid(custom_nodes)
        node_tag = f"dynamic_node_sensor_und_{nid}"
        out_max_tag = f"attr_out_dyn_und_{nid}"
        out_l_tag = f"attr_out_dyn_und_l_{nid}"
        out_r_tag = f"attr_out_dyn_und_r_{nid}"

        with dpg.node(label=f"Input: Understeer #{nid}", tag=node_tag, parent="node_editor_canvas", pos=pos_f):
            with dpg.node_attribute(label="Understeer Max", attribute_type=dpg.mvNode_Attr_Output, tag=out_max_tag):
                dpg.add_text("Understeer (Max)", color=[255, 220, 0, 255])
            with dpg.node_attribute(label="Understeer Left", attribute_type=dpg.mvNode_Attr_Output, tag=out_l_tag):
                dpg.add_text("Understeer (Left)", color=[255, 220, 0, 255])
            with dpg.node_attribute(label="Understeer Right", attribute_type=dpg.mvNode_Attr_Output, tag=out_r_tag):
                dpg.add_text("Understeer (Right)", color=[255, 220, 0, 255])

        for pin in [out_max_tag, out_l_tag, out_r_tag]:
            self.apply_pin_theme(pin, "normalized")

        custom_nodes[node_tag] = {
            "type": "sensor_understeer",
            "out_attr": out_max_tag,
            "out_l": out_l_tag,
            "out_r": out_r_tag,
        }
        recompile_cb()
        return node_tag

    def add_node_output_xinput(self, custom_nodes: Dict[str, dict], recompile_cb: Callable[[], None], pos=(580.0, 120.0)) -> str:
        pos_f = self.get_next_spawn_pos(custom_nodes, pos)
        nid = self.get_next_nid(custom_nodes)
        node_tag = f"dynamic_node_xinput_{nid}"
        in_low_tag = f"attr_in_dyn_low_{nid}"
        in_high_tag = f"attr_in_dyn_high_{nid}"

        with dpg.node(label=f"Output: XInput Vibration #{nid}", tag=node_tag, parent="node_editor_canvas", pos=pos_f):
            with dpg.node_attribute(label="Low Freq (Rumble)", attribute_type=dpg.mvNode_Attr_Input, tag=in_low_tag):
                dpg.add_text("Low Freq Rumble (Left)", color=[255, 220, 0, 255])
            with dpg.node_attribute(label="High Freq (Buzz)", attribute_type=dpg.mvNode_Attr_Input, tag=in_high_tag):
                dpg.add_text("High Freq Buzz (Right)", color=[255, 220, 0, 255])

        self.apply_pin_theme(in_low_tag, "sum_array")
        self.apply_pin_theme(in_high_tag, "sum_array")

        custom_nodes[node_tag] = {
            "type": "output_xinput",
            "in_low": in_low_tag,
            "in_high": in_high_tag,
        }
        recompile_cb()
        return node_tag


    def add_node_constant(self, custom_nodes: Dict[str, dict], recompile_cb: Callable[[], None], val: float = 0.5, pos=(240.0, 280.0)) -> str:
        if not isinstance(val, (int, float)):
            val = 0.5
        pos_f = self.get_next_spawn_pos(custom_nodes, pos)
        nid = self.get_next_nid(custom_nodes)
        node_tag = f"dynamic_node_const_{nid}"
        out_tag = f"attr_out_dyn_const_{nid}"
        val_tag = f"val_dyn_const_{nid}"

        for tag in [node_tag, out_tag, val_tag]:
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)

        with dpg.node(label=f"Constant [0,1] #{nid}", tag=node_tag, parent="node_editor_canvas", pos=pos_f):
            with dpg.node_attribute(label="Value Out", attribute_type=dpg.mvNode_Attr_Output, tag=out_tag):
                dpg.add_slider_float(default_value=float(val), min_value=0.0, max_value=1.0, format="%.2f", width=120, tag=val_tag, callback=lambda: recompile_cb())

        self.apply_pin_theme(out_tag, "normalized")
        custom_nodes[node_tag] = {"type": "constant", "out_attr": out_tag, "val_tag": val_tag}
        recompile_cb()
        return node_tag

    def add_node_float_constant(self, custom_nodes: Dict[str, dict], recompile_cb: Callable[[], None], val: float = 20.0, pos=(240.0, 340.0)) -> str:
        if not isinstance(val, (int, float)):
            val = 20.0
        pos_f = self.get_next_spawn_pos(custom_nodes, pos)
        nid = self.get_next_nid(custom_nodes)
        node_tag = f"dynamic_node_float_const_{nid}"
        out_tag = f"attr_out_dyn_float_const_{nid}"
        val_tag = f"val_dyn_float_const_{nid}"

        for tag in [node_tag, out_tag, val_tag]:
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)

        with dpg.node(label=f"Float Constant #{nid}", tag=node_tag, parent="node_editor_canvas", pos=pos_f):
            with dpg.node_attribute(label="Float Out", attribute_type=dpg.mvNode_Attr_Output, tag=out_tag):
                dpg.add_input_float(default_value=float(val), step=5.0, step_fast=10.0, format="%.1f", width=120, tag=val_tag, callback=lambda: recompile_cb())

        self.apply_pin_theme(out_tag, "float")
        custom_nodes[node_tag] = {"type": "float_constant", "out_attr": out_tag, "val_tag": val_tag}
        recompile_cb()
        return node_tag

    def add_node_multiply(self, custom_nodes: Dict[str, dict], recompile_cb: Callable[[], None], pos=(240.0, 40.0)) -> str:
        pos_f = self.get_next_spawn_pos(custom_nodes, pos)
        nid = self.get_next_nid(custom_nodes)
        node_tag = f"dynamic_node_mult_{nid}"
        in_a_tag = f"attr_in_mult_a_{nid}"
        in_b_tag = f"attr_in_mult_b_{nid}"
        out_tag  = f"attr_out_mult_{nid}"

        with dpg.node(label=f"Multiply [0,1] #{nid}", tag=node_tag, parent="node_editor_canvas", pos=pos_f):
            with dpg.node_attribute(label="Input A", attribute_type=dpg.mvNode_Attr_Input, tag=in_a_tag):
                dpg.add_text("Input A")
            with dpg.node_attribute(label="Input B", attribute_type=dpg.mvNode_Attr_Input, tag=in_b_tag):
                dpg.add_text("Input B")
            with dpg.node_attribute(label="Product Out", attribute_type=dpg.mvNode_Attr_Output, tag=out_tag):
                dpg.add_text("Product Out")

        self.apply_pin_theme(in_a_tag, "normalized")
        self.apply_pin_theme(in_b_tag, "normalized")
        self.apply_pin_theme(out_tag, "normalized")

        custom_nodes[node_tag] = {
            "type": "multiply",
            "in_a": in_a_tag,
            "in_b": in_b_tag,
            "out_attr": out_tag,
        }
        recompile_cb()
        return node_tag

    def add_node_array_multiply(self, custom_nodes: Dict[str, dict], recompile_cb: Callable[[], None], pos=(240.0, 60.0)) -> str:
        pos_f = self.get_next_spawn_pos(custom_nodes, pos)
        nid = self.get_next_nid(custom_nodes)
        node_tag = f"dynamic_node_array_mult_{nid}"
        in_attr_tag = f"attr_in_array_mult_{nid}"
        out_tag     = f"attr_out_array_mult_{nid}"

        with dpg.node(label=f"Array Multiplier #{nid}", tag=node_tag, parent="node_editor_canvas", pos=pos_f):
            with dpg.node_attribute(label="Multi-Input Signals", attribute_type=dpg.mvNode_Attr_Input, tag=in_attr_tag):
                dpg.add_text("Multi-Input Signals (Array)")

            with dpg.node_attribute(label="Product Out", attribute_type=dpg.mvNode_Attr_Output, tag=out_tag):
                dpg.add_text("Product Out")

        self.apply_pin_theme(in_attr_tag, "array")
        self.apply_pin_theme(out_tag, "normalized")

        custom_nodes[node_tag] = {
            "type": "array_multiply",
            "in_attr": in_attr_tag,
            "out_attr": out_tag,
        }
        recompile_cb()
        return node_tag

    def add_node_normalize(self, custom_nodes: Dict[str, dict], recompile_cb: Callable[[], None], min_val=0.0, max_val=100.0, clamp=True, pos=(240.0, 100.0)) -> str:
        if not isinstance(min_val, (int, float)):
            min_val = 0.0
        if not isinstance(max_val, (int, float)):
            max_val = 100.0
        if not isinstance(clamp, bool):
            clamp = True
        pos_f = self.get_next_spawn_pos(custom_nodes, pos)
        nid = self.get_next_nid(custom_nodes)
        node_tag = f"dynamic_node_norm_{nid}"
        in_tag = f"attr_in_norm_{nid}"
        out_tag = f"attr_out_norm_{nid}"
        min_tag = f"min_norm_{nid}"
        max_tag = f"max_norm_{nid}"
        clamp_tag = f"clamp_norm_{nid}"

        with dpg.node(label=f"Normalize #{nid}", tag=node_tag, parent="node_editor_canvas", pos=pos_f):
            with dpg.node_attribute(label="Range", attribute_type=dpg.mvNode_Attr_Static):
                dpg.add_drag_float(label="Min In", default_value=float(min_val), format="%.2f", width=120, tag=min_tag, callback=lambda: recompile_cb())
                dpg.add_drag_float(label="Max In", default_value=float(max_val), format="%.2f", width=120, tag=max_tag, callback=lambda: recompile_cb())
                dpg.add_checkbox(label="Clamp [0, 1]", default_value=bool(clamp), tag=clamp_tag, callback=lambda: recompile_cb())

            with dpg.node_attribute(label="Float In", attribute_type=dpg.mvNode_Attr_Input, tag=in_tag):
                dpg.add_text("Float In")
            with dpg.node_attribute(label="Signal Out", attribute_type=dpg.mvNode_Attr_Output, tag=out_tag):
                dpg.add_text("Signal Out")

        self.apply_pin_theme(in_tag, "compatible")
        self.apply_pin_theme(out_tag, "normalized")

        custom_nodes[node_tag] = {
            "type": "normalize",
            "in_attr": in_tag,
            "out_attr": out_tag,
            "min_tag": min_tag,
            "max_tag": max_tag,
            "clamp_tag": clamp_tag,
        }
        recompile_cb()
        return node_tag

    def add_node_math(self, custom_nodes: Dict[str, dict], recompile_cb: Callable[[], None], op="Multiply (*)", pos=(240.0, 40.0)) -> str:
        if not isinstance(op, str):
            op = "Multiply (*)"
        pos_f = self.get_next_spawn_pos(custom_nodes, pos)
        nid = self.get_next_nid(custom_nodes)
        node_tag = f"dynamic_node_math_{nid}"
        in_a_tag = f"attr_in_math_a_{nid}"
        in_b_tag = f"attr_in_math_b_{nid}"
        out_tag  = f"attr_out_math_{nid}"
        op_tag   = f"op_math_{nid}"

        with dpg.node(label=f"Math Mix #{nid}", tag=node_tag, parent="node_editor_canvas", pos=pos_f):
            with dpg.node_attribute(label="Op", attribute_type=dpg.mvNode_Attr_Static):
                dpg.add_combo(items=["Add (+)", "Multiply (*)", "Subtract (-)", "Divide (/)"], default_value=op, width=120, tag=op_tag, callback=lambda: recompile_cb())
            with dpg.node_attribute(label="Input A", attribute_type=dpg.mvNode_Attr_Input, tag=in_a_tag):
                dpg.add_text("Input A")
            with dpg.node_attribute(label="Input B", attribute_type=dpg.mvNode_Attr_Input, tag=in_b_tag):
                dpg.add_text("Input B")
            with dpg.node_attribute(label="Result Out", attribute_type=dpg.mvNode_Attr_Output, tag=out_tag):
                dpg.add_text("Output")

        self.apply_pin_theme(in_a_tag, "compatible")
        self.apply_pin_theme(in_b_tag, "compatible")
        self.apply_pin_theme(out_tag, "compatible")

        custom_nodes[node_tag] = {
            "type": "math",
            "in_a": in_a_tag,
            "in_b": in_b_tag,
            "out_attr": out_tag,
            "op_tag": op_tag
        }
        recompile_cb()
        return node_tag

    def add_node_transform(self, custom_nodes: Dict[str, dict], recompile_cb: Callable[[], None], thresh=0.15, gain=1.0, gamma=1.0, pos=(240.0, 160.0)) -> str:
        if not isinstance(thresh, (int, float)):
            thresh = 0.15
        if not isinstance(gain, (int, float)):
            gain = 1.0
        if not isinstance(gamma, (int, float)):
            gamma = 1.0
        pos_f = self.get_next_spawn_pos(custom_nodes, pos)
        nid = self.get_next_nid(custom_nodes)
        node_tag = f"dynamic_node_tf_{nid}"
        in_tag    = f"attr_in_tf_{nid}"
        out_tag   = f"attr_out_tf_{nid}"
        gain_tag  = f"gain_tf_{nid}"
        gamma_tag = f"gamma_tf_{nid}"
        thresh_tag = f"thresh_tf_{nid}"

        plot_tag   = f"plot_tf_{nid}"
        xaxis_tag  = f"xaxis_tf_{nid}"
        yaxis_tag  = f"yaxis_tf_{nid}"
        series_tag = f"series_tf_{nid}"
        cursor_tag = f"cursor_tf_{nid}"

        xs = [x / 100.0 for x in range(101)]

        with dpg.node(label=f"Transform & Curve #{nid}", tag=node_tag, parent="node_editor_canvas", pos=pos_f):
            with dpg.node_attribute(label="Parameters", attribute_type=dpg.mvNode_Attr_Static):
                dpg.add_slider_float(label="Threshold", default_value=thresh, min_value=0.0, max_value=0.5, format="%.2f", width=120, tag=thresh_tag, callback=lambda: (self.update_node_plot(nid), recompile_cb()))
                dpg.add_slider_float(label="Gain", default_value=gain, min_value=0.0, max_value=2.0, format="%.2f", width=120, tag=gain_tag, callback=lambda: (self.update_node_plot(nid), recompile_cb()))
                dpg.add_slider_float(label="Gamma", default_value=gamma, min_value=0.2, max_value=3.0, format="%.2f", width=120, tag=gamma_tag, callback=lambda: (self.update_node_plot(nid), recompile_cb()))

                with dpg.plot(no_title=True, height=120, width=180, tag=plot_tag):
                    dpg.add_plot_axis(dpg.mvXAxis, no_tick_labels=True, tag=xaxis_tag)
                    dpg.set_axis_limits(xaxis_tag, 0, 1)
                    with dpg.plot_axis(dpg.mvYAxis, no_tick_labels=True, tag=yaxis_tag):
                        dpg.set_axis_limits(yaxis_tag, 0, 1.05)
                        ys = [apply_response_curve(x, gamma, gain, thresh) for x in xs]
                        dpg.add_line_series(xs, ys, tag=series_tag)
                        dpg.add_line_series([-1, -1], [0, 1], tag=cursor_tag)

            with dpg.node_attribute(label="Input Signal", attribute_type=dpg.mvNode_Attr_Input, tag=in_tag):
                dpg.add_text("Signal In")
            with dpg.node_attribute(label="Transformed Out", attribute_type=dpg.mvNode_Attr_Output, tag=out_tag):
                dpg.add_text("Signal Out")

        self.apply_pin_theme(in_tag, "normalized")
        self.apply_pin_theme(out_tag, "normalized")

        custom_nodes[node_tag] = {
            "type": "transform",
            "in_attr": in_tag,
            "out_attr": out_tag,
            "gain_tag": gain_tag,
            "gamma_tag": gamma_tag,
            "thresh_tag": thresh_tag,
            "cursor_tag": cursor_tag,
            "series_tag": series_tag,
            "nid": nid
        }
        recompile_cb()
        return node_tag

    def update_node_plot(self, nid: int):
        gain_tag = f"gain_tf_{nid}"
        gamma_tag = f"gamma_tf_{nid}"
        thresh_tag = f"thresh_tf_{nid}"
        series_tag = f"series_tf_{nid}"
        if dpg.does_item_exist(gain_tag):
            g = dpg.get_value(gain_tag)
            gm = dpg.get_value(gamma_tag)
            th = dpg.get_value(thresh_tag)
            xs = [x / 100.0 for x in range(101)]
            ys = [apply_response_curve(x, gm, g, th) for x in xs]
            dpg.set_value(series_tag, [xs, ys])

    def update_shape_plot(self, nid: int):
        freq_tag   = f"freq_shape_{nid}"
        duty_tag   = f"duty_shape_{nid}"
        shape_tag  = f"shape_type_{nid}"
        series_tag = f"series_shape_{nid}"
        ms_lbl_tag = f"lbl_shape_ms_{nid}"

        if dpg.does_item_exist(freq_tag) and dpg.does_item_exist(duty_tag) and dpg.does_item_exist(shape_tag):
            freq = max(0.1, dpg.get_value(freq_tag))
            duty = max(0.01, min(1.0, dpg.get_value(duty_tag)))
            shape_choice = dpg.get_value(shape_tag)

            period_ms = 1000.0 / freq
            on_ms = period_ms * duty
            off_ms = period_ms * (1.0 - duty)

            if dpg.does_item_exist(ms_lbl_tag):
                dpg.set_value(ms_lbl_tag, f"ON: {on_ms:.1f}ms | OFF: {off_ms:.1f}ms")

            xs = [i / 100.0 for i in range(101)]
            ys = []
            for x in xs:
                if x <= duty:
                    phi = x / max(0.001, duty)
                    if "Square" in shape_choice:
                        y = 1.0
                    elif "Sawtooth" in shape_choice:
                        y = phi
                    elif "Sine" in shape_choice:
                        y = 0.5 * (1.0 + math.sin(2.0 * math.pi * phi - math.pi / 2.0))
                    elif "Burst" in shape_choice:
                        y = math.exp(-4.0 * phi)
                    else:
                        y = 1.0
                else:
                    y = 0.0
                ys.append(y)

            if dpg.does_item_exist(series_tag):
                dpg.set_value(series_tag, [xs, ys])

    def add_node_shape(self, custom_nodes: Dict[str, dict], recompile_cb: Callable[[], None], shape="Square (Pulsed)", freq=20.0, duty=0.40, pos=(240.0, 420.0)) -> str:
        pos_f = self.get_next_spawn_pos(custom_nodes, pos)
        nid = self.get_next_nid(custom_nodes)
        node_tag    = f"dynamic_node_shape_{nid}"
        in_tag      = f"attr_in_shape_{nid}"
        in_freq_tag = f"attr_in_shape_freq_{nid}"
        out_tag     = f"attr_out_shape_{nid}"
        shape_tag   = f"shape_type_{nid}"
        freq_tag    = f"freq_shape_{nid}"
        duty_tag    = f"duty_shape_{nid}"
        ms_lbl_tag  = f"lbl_shape_ms_{nid}"

        plot_tag    = f"plot_shape_{nid}"
        xaxis_tag   = f"xaxis_shape_{nid}"
        yaxis_tag   = f"yaxis_shape_{nid}"
        series_tag  = f"series_shape_{nid}"

        with dpg.node(label=f"Waveform Shape #{nid}", tag=node_tag, parent="node_editor_canvas", pos=pos_f):
            with dpg.node_attribute(label="Parameters", attribute_type=dpg.mvNode_Attr_Static):
                dpg.add_combo(items=["Square (Pulsed)", "Sawtooth (Scrub)", "Sine (Smooth)", "Burst (Impact)"], default_value=shape, width=170, tag=shape_tag, callback=lambda: (self.update_shape_plot(nid), recompile_cb()))
                dpg.add_spacer(height=4)
                dpg.add_input_float(label="Freq (Hz)", default_value=freq, step=1.0, step_fast=5.0, format="%.1f", width=100, tag=freq_tag, callback=lambda: (self.update_shape_plot(nid), recompile_cb()))
                dpg.add_input_float(label="Duty", default_value=duty, step=0.05, step_fast=0.1, format="%.2f", width=100, tag=duty_tag, callback=lambda: (self.update_shape_plot(nid), recompile_cb()))
                dpg.add_spacer(height=2)
                dpg.add_text("ON: 20.0ms | OFF: 30.0ms", tag=ms_lbl_tag, color=[0, 210, 255, 255])
                dpg.add_spacer(height=4)

                with dpg.plot(no_title=True, height=100, width=170, tag=plot_tag):
                    dpg.add_plot_axis(dpg.mvXAxis, no_tick_labels=True, tag=xaxis_tag)
                    dpg.set_axis_limits(xaxis_tag, 0, 1)
                    with dpg.plot_axis(dpg.mvYAxis, no_tick_labels=True, tag=yaxis_tag):
                        dpg.set_axis_limits(yaxis_tag, -0.05, 1.05)
                        dpg.add_line_series([], [], tag=series_tag)

            with dpg.node_attribute(label="Signal In", attribute_type=dpg.mvNode_Attr_Input, tag=in_tag):
                dpg.add_text("Signal In")
            with dpg.node_attribute(label="Freq In (Hz)", attribute_type=dpg.mvNode_Attr_Input, tag=in_freq_tag):
                dpg.add_text("Freq In (Hz)")
            with dpg.node_attribute(label="Shaped Out", attribute_type=dpg.mvNode_Attr_Output, tag=out_tag):
                dpg.add_text("Shaped Out")

        self.apply_pin_theme(in_tag, "normalized")
        self.apply_pin_theme(in_freq_tag, "float")
        self.apply_pin_theme(out_tag, "normalized")

        custom_nodes[node_tag] = {
            "type": "shape",
            "in_attr": in_tag,
            "in_freq": in_freq_tag,
            "out_attr": out_tag,
            "shape_tag": shape_tag,
            "freq_tag": freq_tag,
            "duty_tag": duty_tag,
            "series_tag": series_tag,
            "nid": nid
        }

        self.update_shape_plot(nid)
        recompile_cb()
        return node_tag

    def delete_custom_node(self, custom_nodes: Dict[str, dict], node_links: Dict[int, Tuple[str, str]], node_tag: str, recompile_cb: Callable[[], None]):
        """Cleanly deletes a dynamic node and purges all connected links and tags."""
        if node_tag not in custom_nodes:
            if dpg.does_item_exist(node_tag):
                dpg.delete_item(node_tag)
            return

        ninfo = custom_nodes[node_tag]
        node_attrs = set()
        for key, val in ninfo.items():
            if "attr" in key or key in ["in_a", "in_b", "in_attr", "out_attr", "in_on", "in_off"]:
                node_attrs.add(val)
                if dpg.does_item_exist(val):
                    node_attrs.add(dpg.get_alias_id(val))

        links_to_delete = []
        for link_id, (o, i) in list(node_links.items()):
            o_id = dpg.get_alias_id(o) if dpg.does_item_exist(o) else o
            i_id = dpg.get_alias_id(i) if dpg.does_item_exist(i) else i
            if o in node_attrs or i in node_attrs or o_id in node_attrs or i_id in node_attrs:
                links_to_delete.append(link_id)

        for link_id in links_to_delete:
            if link_id in node_links:
                del node_links[link_id]
            if dpg.does_item_exist(link_id):
                dpg.delete_item(link_id)

        del custom_nodes[node_tag]
        if dpg.does_item_exist(node_tag):
            dpg.delete_item(node_tag)

        recompile_cb()
