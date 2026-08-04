"""
SimPad Haptic Middleware — Node Editor Module.
Handles node graph canvas layout, custom dynamic nodes, Blender-style ergonomics,
graph persistence, Python source code compilation, and real-time synthesizer synchronization.
"""

import time
import math
import json
import dearpygui.dearpygui as dpg
from typing import Dict, Any, List, Optional, Tuple

from src.core.compiler import GraphCompiler
from src.core.schema import export_graph_json, import_graph_json, GraphSchemaValidator
from src.profiles.manager import GraphProfileManager
from src.core.math_utils import apply_response_curve

# TODO: [DRY] Replaced local duplicate _apply_curve definition with central apply_response_curve from src.core.math_utils.


# TODO: [SRP] NodeEditorTab currently handles UI layout, node graph state, profile management, code compilation, and manual testing. In future refactorings, graph state model and layout rendering should be split.
# TODO: [SLAP] Keep UI construction methods at a uniform high level of abstraction, delegating raw widget configuration and event binding to helper builder methods.
class NodeEditorTab:
    """Encapsulates the DearPyGui Node Editor interface and dynamic graph solver."""

    def __init__(self, synth_engine=None):
        self._node_id_counter = 0
        self._custom_nodes: Dict[str, dict] = {}
        self._node_links: Dict[int, Tuple[str, str]] = {}
        self._active_drag_source: Optional[str] = None
        self._synth_engine = synth_engine
        self._profile_manager = GraphProfileManager()

    def set_synth_engine(self, synth_engine):
        self._synth_engine = synth_engine
        self.recompile_and_update_synth()

    def build_tab(self, parent_app):
        """Constructs the Node Editor tab UI layout."""
        self._parent = parent_app

        with dpg.group(horizontal=False):
            # Top Toolbar 1: Presets & Synthesizer Controls
            with dpg.child_window(height=42, border=True):
                with dpg.group(horizontal=True):
                    dpg.add_text("Presets:", color=[255, 200, 0, 255])
                    dpg.add_combo(
                        items=self._profile_manager.list_names(),
                        default_value=self._profile_manager._active_profile_name,
                        width=140,
                        tag="combo_preset_select",
                        callback=self._cb_load_preset
                    )
                    dpg.add_button(label="Save Preset", tag="btn_save_preset", callback=self._cb_save_preset)
                    dpg.add_button(label="Clone", tag="btn_clone_preset", callback=self._cb_clone_preset)
                    dpg.add_button(label="Delete", tag="btn_delete_preset", callback=self._cb_delete_preset)

                    dpg.add_spacer(width=15)
                    dpg.add_text("Frequency:", color=[0, 210, 255, 255])
                    dpg.add_combo(
                        items=["50 Hz (20ms)", "200 Hz (5ms)", "1000 Hz (1ms)"],
                        default_value="200 Hz (5ms)",
                        width=130,
                        tag="combo_synth_freq",
                        callback=self._cb_change_frequency
                    )

                    dpg.add_spacer(width=15)
                    dpg.add_button(label="View Python Code", callback=self._show_python_code_modal)
                    dpg.add_spacer(width=10)
                    dpg.add_button(label="Auto-Arrange Graph", callback=self.auto_arrange_nodes)

            dpg.add_spacer(height=2)

            # Top Toolbar 2: Node Creation Toolbox
            with dpg.child_window(height=42, border=True):
                with dpg.group(horizontal=True):
                    dpg.add_text("Toolbox:", color=[180, 180, 180, 255])
                    dpg.add_button(label="+ Constant [0,1]", callback=self._add_node_constant)
                    dpg.add_button(label="+ Float Constant (Blue)", callback=self._add_node_float_constant)
                    dpg.add_button(label="+ Multiply [0,1]", callback=self._add_node_multiply)
                    dpg.add_button(label="+ Array Multiplier", callback=self._add_node_array_multiply)
                    dpg.add_button(label="+ Normalize", callback=self._add_node_normalize)
                    dpg.add_button(label="+ Math Mix", callback=self._add_node_math)
                    dpg.add_button(label="+ Transform & Curve", callback=self._add_node_transform)
                    dpg.add_button(label="+ Waveform Shape", callback=self._add_node_shape)

            dpg.add_spacer(height=4)

            # Keyboard Handler: Bind Delete / Suppr key to delete selected nodes & links
            handler_tag = "node_editor_key_handler"
            if dpg.does_item_exist(handler_tag):
                dpg.delete_item(handler_tag)
            with dpg.handler_registry(tag=handler_tag):
                dpg.add_key_press_handler(dpg.mvKey_Delete, callback=lambda: self._delete_selected_items())
                dpg.add_key_press_handler(dpg.mvKey_Back, callback=lambda: self._delete_selected_items())

            with dpg.group(horizontal=True):
                # Left: DearPyGui Node Editor Canvas (Expands to 100% available height)
                with dpg.child_window(width=-340, height=-1, border=True):
                    with dpg.node_editor(
                        tag="node_editor_canvas",
                        callback=self._cb_node_link,
                        delink_callback=self._cb_node_delink,
                        width=-1,
                        height=-1,
                    ):
                        # 1. INPUT NODE: Telemetry Sensors (Combined & Left/Right Channels)
                        with dpg.node(label="Input: Telemetry Sensors", tag="node_sensors", pos=[30.0, 40.0]):
                            with dpg.node_attribute(label="Over-Braking Header", attribute_type=dpg.mvNode_Attr_Static):
                                dpg.add_text("--- Over-Braking ---", color=[140, 140, 140, 255])
                            with dpg.node_attribute(label="Over-Braking Max", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_abs"):
                                dpg.add_text("Over-Braking (Max)", color=[255, 220, 0, 255])
                            with dpg.node_attribute(label="Over-Braking Left", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_abs_l"):
                                dpg.add_text("Over-Braking (Left)", color=[255, 220, 0, 255])
                            with dpg.node_attribute(label="Over-Braking Right", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_abs_r"):
                                dpg.add_text("Over-Braking (Right)", color=[255, 220, 0, 255])

                            with dpg.node_attribute(label="Over-Acceleration Header", attribute_type=dpg.mvNode_Attr_Static):
                                dpg.add_text("--- Over-Acceleration ---", color=[140, 140, 140, 255])
                            with dpg.node_attribute(label="Over-Accel Max", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_tc"):
                                dpg.add_text("Over-Accel (Max)", color=[255, 220, 0, 255])
                            with dpg.node_attribute(label="Over-Accel Left", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_tc_l"):
                                dpg.add_text("Over-Accel (Left)", color=[255, 220, 0, 255])
                            with dpg.node_attribute(label="Over-Accel Right", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_tc_r"):
                                dpg.add_text("Over-Accel (Right)", color=[255, 220, 0, 255])

                            with dpg.node_attribute(label="Oversteer Header", attribute_type=dpg.mvNode_Attr_Static):
                                dpg.add_text("--- Oversteer ---", color=[140, 140, 140, 255])
                            with dpg.node_attribute(label="Oversteer Max", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_over"):
                                dpg.add_text("Oversteer (Max)", color=[255, 220, 0, 255])
                            with dpg.node_attribute(label="Oversteer Left", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_over_l"):
                                dpg.add_text("Oversteer (Left)", color=[255, 220, 0, 255])
                            with dpg.node_attribute(label="Oversteer Right", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_over_r"):
                                dpg.add_text("Oversteer (Right)", color=[255, 220, 0, 255])

                            with dpg.node_attribute(label="Understeer Header", attribute_type=dpg.mvNode_Attr_Static):
                                dpg.add_text("--- Understeer ---", color=[140, 140, 140, 255])
                            with dpg.node_attribute(label="Understeer Max", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_und"):
                                dpg.add_text("Understeer (Max)", color=[255, 220, 0, 255])
                            with dpg.node_attribute(label="Understeer Left", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_und_l"):
                                dpg.add_text("Understeer (Left)", color=[255, 220, 0, 255])
                            with dpg.node_attribute(label="Understeer Right", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_und_r"):
                                dpg.add_text("Understeer (Right)", color=[255, 220, 0, 255])

                        # 2. OUTPUT NODE: XInput Vibration Motors (Multi-Input Summing Ports)
                        with dpg.node(label="Output: XInput Vibration", tag="node_xinput", pos=[580.0, 120.0]):
                            with dpg.node_attribute(label="Low Freq (Rumble)", attribute_type=dpg.mvNode_Attr_Input, tag="attr_in_low"):
                                dpg.add_text("Low Freq Rumble (Left)", color=[255, 220, 0, 255])
                            with dpg.node_attribute(label="High Freq (Buzz)", attribute_type=dpg.mvNode_Attr_Input, tag="attr_in_high"):
                                dpg.add_text("High Freq Buzz (Right)", color=[255, 220, 0, 255])

                        # Apply pin themes for all sensor channels
                        for sensor_pin in [
                            "attr_out_abs", "attr_out_abs_l", "attr_out_abs_r",
                            "attr_out_tc", "attr_out_tc_l", "attr_out_tc_r",
                            "attr_out_over", "attr_out_over_l", "attr_out_over_r",
                            "attr_out_und", "attr_out_und_l", "attr_out_und_r"
                        ]:
                            self._apply_pin_theme(sensor_pin, "normalized")

                        self._apply_pin_theme("attr_in_low", "sum_array")
                        self._apply_pin_theme("attr_in_high", "sum_array")

                # Right: Interactive Test Sidebar for Sensors Control
                with dpg.child_window(width=320, height=-1, border=True):
                    dpg.add_text("Real-Time Synthesizer Control", color=[0, 210, 255, 255])
                    dpg.add_text("Manual telemetry input to test haptic synthesis loop.", color=[140, 140, 140, 255])
                    dpg.add_separator()
                    dpg.add_spacer(height=4)

                    dpg.add_text("Sensors Live Control (Left / Right)", color=[243, 156, 18, 255])

                    dpg.add_text("Over-Braking", color=[255, 220, 0, 255])
                    with dpg.group(horizontal=True):
                        dpg.add_slider_float(label="L", tag="test_sensor_abs_l", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=self._on_test_sensor_change)
                        dpg.add_slider_float(label="R", tag="test_sensor_abs_r", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=self._on_test_sensor_change)

                    dpg.add_spacer(height=2)
                    dpg.add_text("Over-Acceleration", color=[255, 220, 0, 255])
                    with dpg.group(horizontal=True):
                        dpg.add_slider_float(label="L", tag="test_sensor_tc_l", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=self._on_test_sensor_change)
                        dpg.add_slider_float(label="R", tag="test_sensor_tc_r", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=self._on_test_sensor_change)

                    dpg.add_spacer(height=2)
                    dpg.add_text("Oversteer", color=[255, 220, 0, 255])
                    with dpg.group(horizontal=True):
                        dpg.add_slider_float(label="L", tag="test_sensor_over_l", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=self._on_test_sensor_change)
                        dpg.add_slider_float(label="R", tag="test_sensor_over_r", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=self._on_test_sensor_change)

                    dpg.add_spacer(height=2)
                    dpg.add_text("Understeer", color=[255, 220, 0, 255])
                    with dpg.group(horizontal=True):
                        dpg.add_slider_float(label="L", tag="test_sensor_und_l", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=self._on_test_sensor_change)
                        dpg.add_slider_float(label="R", tag="test_sensor_und_r", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=self._on_test_sensor_change)

                    dpg.add_spacer(height=10)
                    dpg.add_separator()
                    dpg.add_spacer(height=4)
                    dpg.add_text("Quick Action Pulse", color=[180, 180, 180, 255])
                    with dpg.group(horizontal=True):
                        dpg.add_button(label="Braking L", width=65, callback=lambda: self._trigger_sensor_pulse("test_sensor_abs_l"))
                        dpg.add_button(label="Braking R", width=65, callback=lambda: self._trigger_sensor_pulse("test_sensor_abs_r"))
                        dpg.add_button(label="Accel L", width=65, callback=lambda: self._trigger_sensor_pulse("test_sensor_tc_l"))
                        dpg.add_button(label="Accel R", width=65, callback=lambda: self._trigger_sensor_pulse("test_sensor_tc_r"))
                    with dpg.group(horizontal=True):
                        dpg.add_button(label="Oversteer L", width=65, callback=lambda: self._trigger_sensor_pulse("test_sensor_over_l"))
                        dpg.add_button(label="Oversteer R", width=65, callback=lambda: self._trigger_sensor_pulse("test_sensor_over_r"))
                        dpg.add_button(label="Under L", width=65, callback=lambda: self._trigger_sensor_pulse("test_sensor_und_l"))
                        dpg.add_button(label="Under R", width=65, callback=lambda: self._trigger_sensor_pulse("test_sensor_und_r"))

                    dpg.add_spacer(height=10)
                    dpg.add_separator()
                    dpg.add_spacer(height=4)
                    dpg.add_text("Output Readout (Vibration)", color=[46, 204, 113, 255])
                    dpg.add_text("Low Freq Rumble (Left): 0%", tag="lbl_node_out_low", color=[255, 51, 102, 255])
                    dpg.add_progress_bar(tag="bar_node_out_low", default_value=0.0, width=280)
                    dpg.add_spacer(height=4)
                    dpg.add_text("High Freq Buzz (Right): 0%", tag="lbl_node_out_high", color=[0, 255, 136, 255])
                    dpg.add_progress_bar(tag="bar_node_out_high", default_value=0.0, width=280)

                    dpg.add_spacer(height=12)
                    dpg.add_button(label="Reset All Sensors to 0", width=280, callback=self._reset_test_sensors)

        # Load active preset on startup
        active_preset = self._profile_manager.get_active()
        if active_preset:
            self.import_graph_from_dict(active_preset.graph_data)
            self._update_preset_ui_state()

    def _apply_pin_theme(self, attr_tag: str, pin_type: Any = "normalized", is_normalized: Optional[bool] = None, is_square: bool = False):
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
            pin_col = [255, 140, 0, 255]  # Orange for Array Multiplier
            hover_col = [255, 180, 50, 255]
        elif pin_type in ["sum_array", "red"]:
            pin_col = [255, 60, 60, 255]  # Red for Motor Summing Array Ports
            hover_col = [255, 120, 120, 255]
        else:
            pin_col = [180, 180, 180, 255]
            hover_col = [220, 220, 220, 255]

        with dpg.theme(tag=theme_tag):
            with dpg.theme_component(dpg.mvNodeAttribute):
                dpg.add_theme_color(dpg.mvNodeCol_Pin, pin_col, category=dpg.mvThemeCat_Nodes)
                dpg.add_theme_color(dpg.mvNodeCol_PinHovered, hover_col, category=dpg.mvThemeCat_Nodes)
        dpg.bind_item_theme(attr_tag, theme_tag)

    def _get_next_nid(self) -> int:
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

    def _get_next_spawn_pos(self, requested_pos: Any = None) -> List[float]:
        """Calculates a non-overlapping spawn position for new nodes added from Toolbox."""
        if requested_pos is not None:
            x, y = float(requested_pos[0]), float(requested_pos[1])
        else:
            x, y = 280.0, 60.0

        existing_positions = []
        for ntag in self._custom_nodes.keys():
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

    # ── Toolbox Node Creation Callbacks ───────────────────────────────────────
    def _add_node_constant(self, val: float = 0.5, pos=(240.0, 280.0)):
        pos_f = self._get_next_spawn_pos(pos)
        nid = self._get_next_nid()
        node_tag = f"dynamic_node_const_{nid}"
        out_tag = f"attr_out_dyn_const_{nid}"
        val_tag = f"val_dyn_const_{nid}"

        for tag in [node_tag, out_tag, val_tag]:
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)

        with dpg.node(label=f"Constant [0,1] #{nid}", tag=node_tag, parent="node_editor_canvas", pos=pos_f):
            with dpg.node_attribute(label="Value Out", attribute_type=dpg.mvNode_Attr_Output, tag=out_tag):
                dpg.add_slider_float(default_value=val, min_value=0.0, max_value=1.0, format="%.2f", width=120, tag=val_tag, callback=lambda: self.recompile_and_update_synth())

        self._apply_pin_theme(out_tag, "normalized")
        self._custom_nodes[node_tag] = {"type": "constant", "out_attr": out_tag, "val_tag": val_tag}
        self.recompile_and_update_synth()
        return node_tag

    def _add_node_float_constant(self, val: float = 20.0, pos=(240.0, 340.0)):
        pos_f = self._get_next_spawn_pos(pos)
        nid = self._get_next_nid()
        node_tag = f"dynamic_node_float_const_{nid}"
        out_tag = f"attr_out_dyn_float_const_{nid}"
        val_tag = f"val_dyn_float_const_{nid}"

        for tag in [node_tag, out_tag, val_tag]:
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)

        with dpg.node(label=f"Float Constant #{nid}", tag=node_tag, parent="node_editor_canvas", pos=pos_f):
            with dpg.node_attribute(label="Float Out", attribute_type=dpg.mvNode_Attr_Output, tag=out_tag):
                dpg.add_input_float(default_value=val, step=5.0, step_fast=10.0, format="%.1f", width=120, tag=val_tag, callback=lambda: self.recompile_and_update_synth())

        self._apply_pin_theme(out_tag, "float")
        self._custom_nodes[node_tag] = {"type": "float_constant", "out_attr": out_tag, "val_tag": val_tag}
        self.recompile_and_update_synth()
        return node_tag

    def _add_node_multiply(self, pos=(240.0, 40.0)):
        pos_f = self._get_next_spawn_pos(pos)
        nid = self._get_next_nid()
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

        self._apply_pin_theme(in_a_tag, "normalized")
        self._apply_pin_theme(in_b_tag, "normalized")
        self._apply_pin_theme(out_tag, "normalized")

        self._custom_nodes[node_tag] = {
            "type": "multiply",
            "in_a": in_a_tag,
            "in_b": in_b_tag,
            "out_attr": out_tag,
        }
        self.recompile_and_update_synth()
        return node_tag

    def _add_node_array_multiply(self, pos=(240.0, 60.0)):
        pos_f = self._get_next_spawn_pos(pos)
        nid = self._get_next_nid()
        node_tag = f"dynamic_node_array_mult_{nid}"
        in_attr_tag = f"attr_in_array_mult_{nid}"
        out_tag     = f"attr_out_array_mult_{nid}"

        with dpg.node(label=f"Array Multiplier #{nid}", tag=node_tag, parent="node_editor_canvas", pos=pos_f):
            with dpg.node_attribute(label="Multi-Input Signals", attribute_type=dpg.mvNode_Attr_Input, tag=in_attr_tag):
                dpg.add_text("Multi-Input Signals (Array)")

            with dpg.node_attribute(label="Product Out", attribute_type=dpg.mvNode_Attr_Output, tag=out_tag):
                dpg.add_text("Product Out")

        self._apply_pin_theme(in_attr_tag, "array")
        self._apply_pin_theme(out_tag, "normalized")

        self._custom_nodes[node_tag] = {
            "type": "array_multiply",
            "in_attr": in_attr_tag,
            "out_attr": out_tag,
        }
        self.recompile_and_update_synth()
        return node_tag

    def _add_node_normalize(self, min_val=0.0, max_val=100.0, clamp=True, pos=(240.0, 100.0)):
        pos_f = self._get_next_spawn_pos(pos)
        nid = self._get_next_nid()
        node_tag = f"dynamic_node_norm_{nid}"
        in_tag = f"attr_in_norm_{nid}"
        out_tag = f"attr_out_norm_{nid}"
        min_tag = f"min_norm_{nid}"
        max_tag = f"max_norm_{nid}"
        clamp_tag = f"clamp_norm_{nid}"

        with dpg.node(label=f"Normalize #{nid}", tag=node_tag, parent="node_editor_canvas", pos=pos_f):
            with dpg.node_attribute(label="Range", attribute_type=dpg.mvNode_Attr_Static):
                dpg.add_drag_float(label="Min In", default_value=min_val, format="%.2f", width=120, tag=min_tag, callback=lambda: self.recompile_and_update_synth())
                dpg.add_drag_float(label="Max In", default_value=max_val, format="%.2f", width=120, tag=max_tag, callback=lambda: self.recompile_and_update_synth())
                dpg.add_checkbox(label="Clamp [0, 1]", default_value=clamp, tag=clamp_tag, callback=lambda: self.recompile_and_update_synth())

            with dpg.node_attribute(label="Float In", attribute_type=dpg.mvNode_Attr_Input, tag=in_tag):
                dpg.add_text("Float In")
            with dpg.node_attribute(label="Signal Out", attribute_type=dpg.mvNode_Attr_Output, tag=out_tag):
                dpg.add_text("Signal Out")

        self._apply_pin_theme(in_tag, "compatible")
        self._apply_pin_theme(out_tag, "normalized")

        self._custom_nodes[node_tag] = {
            "type": "normalize",
            "in_attr": in_tag,
            "out_attr": out_tag,
            "min_tag": min_tag,
            "max_tag": max_tag,
            "clamp_tag": clamp_tag,
        }
        self.recompile_and_update_synth()
        return node_tag

    def _add_node_math(self, op="Multiply (*)", pos=(240.0, 40.0)):
        pos_f = self._get_next_spawn_pos(pos)
        nid = self._get_next_nid()
        node_tag = f"dynamic_node_math_{nid}"
        in_a_tag = f"attr_in_math_a_{nid}"
        in_b_tag = f"attr_in_math_b_{nid}"
        out_tag  = f"attr_out_math_{nid}"
        op_tag   = f"op_math_{nid}"

        with dpg.node(label=f"Math Mix #{nid}", tag=node_tag, parent="node_editor_canvas", pos=pos_f):
            with dpg.node_attribute(label="Op", attribute_type=dpg.mvNode_Attr_Static):
                dpg.add_combo(items=["Add (+)", "Multiply (*)", "Subtract (-)", "Divide (/)"], default_value=op, width=120, tag=op_tag, callback=lambda: self.recompile_and_update_synth())
            with dpg.node_attribute(label="Input A", attribute_type=dpg.mvNode_Attr_Input, tag=in_a_tag):
                dpg.add_text("Input A")
            with dpg.node_attribute(label="Input B", attribute_type=dpg.mvNode_Attr_Input, tag=in_b_tag):
                dpg.add_text("Input B")
            with dpg.node_attribute(label="Result Out", attribute_type=dpg.mvNode_Attr_Output, tag=out_tag):
                dpg.add_text("Output")

        self._apply_pin_theme(in_a_tag, "compatible")
        self._apply_pin_theme(in_b_tag, "compatible")
        self._apply_pin_theme(out_tag, "compatible")

        self._custom_nodes[node_tag] = {
            "type": "math",
            "in_a": in_a_tag,
            "in_b": in_b_tag,
            "out_attr": out_tag,
            "op_tag": op_tag
        }
        self.recompile_and_update_synth()
        return node_tag

    def _add_node_transform(self, thresh=0.15, gain=1.0, gamma=1.0, pos=(240.0, 160.0)):
        pos_f = self._get_next_spawn_pos(pos)
        nid = self._get_next_nid()
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
                dpg.add_slider_float(label="Threshold", default_value=thresh, min_value=0.0, max_value=0.5, format="%.2f", width=120, tag=thresh_tag, callback=lambda: (self._update_node_plot(nid), self.recompile_and_update_synth()))
                dpg.add_slider_float(label="Gain", default_value=gain, min_value=0.0, max_value=2.0, format="%.2f", width=120, tag=gain_tag, callback=lambda: (self._update_node_plot(nid), self.recompile_and_update_synth()))
                dpg.add_slider_float(label="Gamma", default_value=gamma, min_value=0.2, max_value=3.0, format="%.2f", width=120, tag=gamma_tag, callback=lambda: (self._update_node_plot(nid), self.recompile_and_update_synth()))

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

        self._apply_pin_theme(in_tag, "normalized")
        self._apply_pin_theme(out_tag, "normalized")

        self._custom_nodes[node_tag] = {
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
        self.recompile_and_update_synth()
        return node_tag

    def _update_node_plot(self, nid: int):
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

    def _update_shape_plot(self, nid: int):
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

    def _add_node_shape(self, shape="Square (Pulsed)", freq=20.0, duty=0.40, pos=(240.0, 420.0)):
        pos_f = self._get_next_spawn_pos(pos)
        nid = self._get_next_nid()
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
                dpg.add_combo(items=["Square (Pulsed)", "Sawtooth (Scrub)", "Sine (Smooth)", "Burst (Impact)"], default_value=shape, width=170, tag=shape_tag, callback=lambda: (self._update_shape_plot(nid), self.recompile_and_update_synth()))
                dpg.add_spacer(height=4)
                dpg.add_input_float(label="Freq (Hz)", default_value=freq, step=1.0, step_fast=5.0, format="%.1f", width=100, tag=freq_tag, callback=lambda: (self._update_shape_plot(nid), self.recompile_and_update_synth()))
                dpg.add_input_float(label="Duty % [0,1]", default_value=duty, step=0.05, step_fast=0.1, format="%.2f", width=100, tag=duty_tag, callback=lambda: (self._update_shape_plot(nid), self.recompile_and_update_synth()))
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

        self._apply_pin_theme(in_tag, "normalized")
        self._apply_pin_theme(in_freq_tag, "float")
        self._apply_pin_theme(out_tag, "normalized")

        self._custom_nodes[node_tag] = {
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

        self._update_shape_plot(nid)
        self.recompile_and_update_synth()
        return node_tag

    def _delete_custom_node(self, node_tag: str):
        """Cleanly deletes a dynamic node and purges all connected links and tags."""
        if node_tag not in self._custom_nodes:
            if dpg.does_item_exist(node_tag):
                dpg.delete_item(node_tag)
            return

        ninfo = self._custom_nodes[node_tag]
        node_attrs = set()
        for key, val in ninfo.items():
            if "attr" in key or key in ["in_a", "in_b", "in_attr", "out_attr", "in_on", "in_off"]:
                node_attrs.add(val)
                if dpg.does_item_exist(val):
                    node_attrs.add(dpg.get_alias_id(val))

        links_to_delete = []
        for link_id, (o, i) in list(self._node_links.items()):
            o_id = dpg.get_alias_id(o) if dpg.does_item_exist(o) else o
            i_id = dpg.get_alias_id(i) if dpg.does_item_exist(i) else i
            if o in node_attrs or i in node_attrs or o_id in node_attrs or i_id in node_attrs:
                links_to_delete.append(link_id)

        for link_id in links_to_delete:
            if link_id in self._node_links:
                del self._node_links[link_id]
            if dpg.does_item_exist(link_id):
                dpg.delete_item(link_id)

        del self._custom_nodes[node_tag]
        if dpg.does_item_exist(node_tag):
            dpg.delete_item(node_tag)

        self.recompile_and_update_synth()

    def _delete_selected_items(self):
        """Keyboard Del / Suppr Key Handler: Deletes selected dynamic nodes and links."""
        if not dpg.does_item_exist("node_editor_canvas"):
            return

        selected_links = dpg.get_selected_links("node_editor_canvas")
        for link_id in selected_links:
            if link_id in self._node_links:
                del self._node_links[link_id]
            if dpg.does_item_exist(link_id):
                dpg.delete_item(link_id)

        selected_nodes = dpg.get_selected_nodes("node_editor_canvas")
        protected_nodes = {"node_sensors", "node_xinput"}
        for node_id in selected_nodes:
            node_tag = None
            if node_id in self._custom_nodes:
                node_tag = node_id
            else:
                for ntag in list(self._custom_nodes.keys()):
                    if dpg.does_item_exist(ntag) and (dpg.get_alias_id(ntag) == node_id or ntag == node_id):
                        node_tag = ntag
                        break

            if node_tag and node_tag not in protected_nodes:
                self._delete_custom_node(node_tag)

        self.recompile_and_update_synth()

    def _update_embedded_controls_visibility(self):
        """Hides embedded input widgets and displays pin text labels when connected via link."""
        connected_attrs = set()
        for link_id, (attr_out, attr_in) in self._node_links.items():
            connected_attrs.add(attr_in)
            if dpg.does_item_exist(attr_in):
                connected_attrs.add(dpg.get_alias_id(attr_in))

        for ntag, ninfo in self._custom_nodes.items():
            if ninfo.get("type") == "shape":
                for attr_key, widget_key, lbl_key in [("in_on", "on_ms_tag", "on_lbl_tag"), ("in_off", "off_ms_tag", "off_lbl_tag")]:
                    attr_tag = ninfo.get(attr_key)
                    widget_tag = ninfo.get(widget_key)
                    lbl_tag = ninfo.get(lbl_key)

                    if attr_tag and widget_tag and dpg.does_item_exist(widget_tag):
                        attr_id = dpg.get_alias_id(attr_tag) if dpg.does_item_exist(attr_tag) else None
                        is_connected = (attr_tag in connected_attrs) or (attr_id and attr_id in connected_attrs)
                        dpg.configure_item(widget_tag, show=not is_connected)
                        if lbl_tag and dpg.does_item_exist(lbl_tag):
                            dpg.configure_item(lbl_tag, show=is_connected)

    def _cb_node_link(self, sender, app_data):
        attr_out, attr_in = app_data

        # Multi-input array ports: Output motors (Red) and Array Multiplier (Orange)
        is_array_port = False
        if attr_in in ["attr_in_low", "attr_in_high"]:
            is_array_port = True
        else:
            for ninfo in self._custom_nodes.values():
                if ninfo.get("type") == "array_multiply" and ninfo.get("in_attr") == attr_in:
                    is_array_port = True
                    break
                elif ninfo.get("type") == "array_multiply" and dpg.does_item_exist(attr_in) and dpg.does_item_exist(ninfo.get("in_attr")) and dpg.get_alias_id(ninfo.get("in_attr")) == dpg.get_alias_id(attr_in):
                    is_array_port = True
                    break

        if not is_array_port:
            existing_links_to_remove = []
            for existing_id, (o, i) in list(self._node_links.items()):
                if i == attr_in or (dpg.does_item_exist(i) and dpg.does_item_exist(attr_in) and dpg.get_alias_id(i) == dpg.get_alias_id(attr_in)):
                    existing_links_to_remove.append(existing_id)

            for old_id in existing_links_to_remove:
                if old_id in self._node_links:
                    del self._node_links[old_id]
                if dpg.does_item_exist(old_id):
                    dpg.delete_item(old_id)

        link_id = dpg.add_node_link(attr_out, attr_in, parent=sender)
        self._node_links[link_id] = (attr_out, attr_in)
        self._update_embedded_controls_visibility()
        self.recompile_and_update_synth()

    def _cb_node_delink(self, sender, app_data):
        link_id = app_data
        if link_id in self._node_links:
            del self._node_links[link_id]
        if dpg.does_item_exist(link_id):
            dpg.delete_item(link_id)
        self._update_embedded_controls_visibility()
        self.recompile_and_update_synth()

    def _trigger_sensor_pulse(self, tag_name: str):
        dpg.set_value(tag_name, 1.0)
        self._on_test_sensor_change()

    def _reset_test_sensors(self):
        for tag in [
            "test_sensor_abs_l", "test_sensor_abs_r",
            "test_sensor_tc_l", "test_sensor_tc_r",
            "test_sensor_over_l", "test_sensor_over_r",
            "test_sensor_und_l", "test_sensor_und_r"
        ]:
            if dpg.does_item_exist(tag):
                dpg.set_value(tag, 0.0)
        self._on_test_sensor_change()

    def _on_test_sensor_change(self):
        if self._synth_engine:
            abs_l = dpg.get_value("test_sensor_abs_l") if dpg.does_item_exist("test_sensor_abs_l") else 0.0
            abs_r = dpg.get_value("test_sensor_abs_r") if dpg.does_item_exist("test_sensor_abs_r") else 0.0
            abs_val = max(abs_l, abs_r)

            tc_l = dpg.get_value("test_sensor_tc_l") if dpg.does_item_exist("test_sensor_tc_l") else 0.0
            tc_r = dpg.get_value("test_sensor_tc_r") if dpg.does_item_exist("test_sensor_tc_r") else 0.0
            tc_val = max(tc_l, tc_r)

            over_l = dpg.get_value("test_sensor_over_l") if dpg.does_item_exist("test_sensor_over_l") else 0.0
            over_r = dpg.get_value("test_sensor_over_r") if dpg.does_item_exist("test_sensor_over_r") else 0.0
            over_val = max(over_l, over_r)

            und_l = dpg.get_value("test_sensor_und_l") if dpg.does_item_exist("test_sensor_und_l") else 0.0
            und_r = dpg.get_value("test_sensor_und_r") if dpg.does_item_exist("test_sensor_und_r") else 0.0
            und_val = max(und_l, und_r)

            self._synth_engine.update_telemetry(
                abs_val=abs_val, abs_l=abs_l, abs_r=abs_r,
                tc_val=tc_val, tc_l=tc_l, tc_r=tc_r,
                over_val=over_val, over_l=over_l, over_r=over_r,
                und_val=und_val, und_l=und_l, und_r=und_r
            )

    def _update_preset_ui_state(self):
        """Disables Save and Delete buttons if current profile is a read-only preset."""
        selected_name = dpg.get_value("combo_preset_select") if dpg.does_item_exist("combo_preset_select") else self._profile_manager._active_profile_name
        prof = self._profile_manager.get_profile(selected_name)
        is_preset = prof.is_preset if prof else False

        if dpg.does_item_exist("btn_save_preset"):
            dpg.configure_item("btn_save_preset", enabled=not is_preset)
        if dpg.does_item_exist("btn_delete_preset"):
            dpg.configure_item("btn_delete_preset", enabled=not is_preset)

    def evaluate_graph(self) -> Tuple[float, float]:
        """Reads current output values from high-frequency synthesizer engine and polls profile directory changes."""
        if self._profile_manager.check_for_changes():
            names = self._profile_manager.list_names()
            active_name = self._profile_manager._active_profile_name
            if dpg.does_item_exist("combo_preset_select"):
                dpg.configure_item("combo_preset_select", items=names, default_value=active_name)
            self._update_preset_ui_state()

        if self._synth_engine:
            low_val, high_val = self._synth_engine.get_current_outputs()
        else:
            low_val, high_val = 0.0, 0.0

        if dpg.does_item_exist("lbl_node_out_low"):
            dpg.set_value("lbl_node_out_low", f"Low Freq Rumble (Left): {int(low_val * 100)}%")
            dpg.set_value("bar_node_out_low", low_val)
            dpg.set_value("lbl_node_out_high", f"High Freq Buzz (Right): {int(high_val * 100)}%")
            dpg.set_value("bar_node_out_high", high_val)

        return low_val, high_val

    # ── Graph Serialization & Persistence ────────────────────────────────────
    def export_graph_to_dict(self) -> dict:
        """Serializes current node graph (nodes, properties, positions, links) to a dictionary."""
        nodes_dict = {}
        for ntag, ninfo in self._custom_nodes.items():
            pos = dpg.get_item_pos(ntag) if dpg.does_item_exist(ntag) else [240, 100]
            ndata = {"type": ninfo["type"], "out_attr": ninfo.get("out_attr"), "pos": list(pos)}

            ntype = ninfo["type"]
            if ntype in ["constant", "float_constant"]:
                ndata["val"] = dpg.get_value(ninfo["val_tag"]) if dpg.does_item_exist(ninfo["val_tag"]) else (0.5 if ntype == "constant" else 20.0)
            elif ntype == "normalize":
                ndata["in_attr"] = ninfo.get("in_attr")
                ndata["min"] = dpg.get_value(ninfo["min_tag"]) if dpg.does_item_exist(ninfo["min_tag"]) else 0.0
                ndata["max"] = dpg.get_value(ninfo["max_tag"]) if dpg.does_item_exist(ninfo["max_tag"]) else 100.0
                ndata["clamp"] = dpg.get_value(ninfo["clamp_tag"]) if dpg.does_item_exist(ninfo["clamp_tag"]) else True
            elif ntype == "math":
                ndata["in_a"] = ninfo.get("in_a")
                ndata["in_b"] = ninfo.get("in_b")
                ndata["op"] = dpg.get_value(ninfo["op_tag"]) if dpg.does_item_exist(ninfo["op_tag"]) else "Multiply (*)"
            elif ntype == "multiply":
                ndata["in_a"] = ninfo.get("in_a")
                ndata["in_b"] = ninfo.get("in_b")
            elif ntype == "array_multiply":
                ndata["in_attr"] = ninfo.get("in_attr")
            elif ntype == "transform":
                ndata["in_attr"] = ninfo.get("in_attr")
                ndata["gain"] = dpg.get_value(ninfo["gain_tag"]) if dpg.does_item_exist(ninfo["gain_tag"]) else 1.0
                ndata["gamma"] = dpg.get_value(ninfo["gamma_tag"]) if dpg.does_item_exist(ninfo["gamma_tag"]) else 1.0
                ndata["thresh"] = dpg.get_value(ninfo["thresh_tag"]) if dpg.does_item_exist(ninfo["thresh_tag"]) else 0.0
            elif ntype == "shape":
                ndata["in_attr"] = ninfo.get("in_attr")
                ndata["in_freq"] = ninfo.get("in_freq")
                ndata["shape"] = dpg.get_value(ninfo["shape_tag"]) if dpg.does_item_exist(ninfo["shape_tag"]) else "Square (Pulsed)"
                ndata["freq"] = dpg.get_value(ninfo["freq_tag"]) if dpg.does_item_exist(ninfo["freq_tag"]) else 20.0
                ndata["duty"] = dpg.get_value(ninfo["duty_tag"]) if dpg.does_item_exist(ninfo["duty_tag"]) else 0.40

            nodes_dict[ntag] = ndata

        links_list = []
        for link_id, (o, i) in self._node_links.items():
            links_list.append([o, i])

        return {"nodes": nodes_dict, "links": links_list}

    def import_graph_from_dict(self, graph_data: dict):
        """Clears current graph canvas and rebuilds visual nodes and links from dictionary."""
        if not dpg.does_item_exist("node_editor_canvas"):
            return

        # 1. Clear current dynamic nodes and links
        for link_id in list(self._node_links.keys()):
            if dpg.does_item_exist(link_id):
                dpg.delete_item(link_id)
        self._node_links.clear()

        for ntag in list(self._custom_nodes.keys()):
            if dpg.does_item_exist(ntag):
                dpg.delete_item(ntag)
        self._custom_nodes.clear()

        # Tag mapping table to re-wire loaded links to newly created attribute tags
        tag_remap: Dict[str, str] = {}

        # 2. Re-create nodes
        nodes = graph_data.get("nodes", {})
        for old_ntag, ndata in nodes.items():
            ntype = ndata.get("type")
            pos = tuple(ndata.get("pos", [240, 100]))

            if ntype == "constant":
                new_ntag = self._add_node_constant(val=ndata.get("val", 0.5), pos=pos)
                tag_remap[ndata["out_attr"]] = self._custom_nodes[new_ntag]["out_attr"]

            elif ntype == "float_constant":
                new_ntag = self._add_node_float_constant(val=ndata.get("val", 20.0), pos=pos)
                tag_remap[ndata["out_attr"]] = self._custom_nodes[new_ntag]["out_attr"]

            elif ntype == "multiply":
                new_ntag = self._add_node_multiply(pos=pos)
                tag_remap[ndata["in_a"]] = self._custom_nodes[new_ntag]["in_a"]
                tag_remap[ndata["in_b"]] = self._custom_nodes[new_ntag]["in_b"]
                tag_remap[ndata["out_attr"]] = self._custom_nodes[new_ntag]["out_attr"]

            elif ntype == "array_multiply":
                new_ntag = self._add_node_array_multiply(pos=pos)
                tag_remap[ndata["in_attr"]] = self._custom_nodes[new_ntag]["in_attr"]
                tag_remap[ndata["out_attr"]] = self._custom_nodes[new_ntag]["out_attr"]

            elif ntype == "normalize":
                new_ntag = self._add_node_normalize(min_val=ndata.get("min", 0.0), max_val=ndata.get("max", 100.0), clamp=ndata.get("clamp", True), pos=pos)
                tag_remap[ndata["in_attr"]] = self._custom_nodes[new_ntag]["in_attr"]
                tag_remap[ndata["out_attr"]] = self._custom_nodes[new_ntag]["out_attr"]

            elif ntype == "math":
                new_ntag = self._add_node_math(op=ndata.get("op", "Multiply (*)"), pos=pos)
                tag_remap[ndata["in_a"]] = self._custom_nodes[new_ntag]["in_a"]
                tag_remap[ndata["in_b"]] = self._custom_nodes[new_ntag]["in_b"]
                tag_remap[ndata["out_attr"]] = self._custom_nodes[new_ntag]["out_attr"]

            elif ntype == "transform":
                new_ntag = self._add_node_transform(thresh=ndata.get("thresh", 0.15), gain=ndata.get("gain", 1.0), gamma=ndata.get("gamma", 1.0), pos=pos)
                tag_remap[ndata["in_attr"]] = self._custom_nodes[new_ntag]["in_attr"]
                tag_remap[ndata["out_attr"]] = self._custom_nodes[new_ntag]["out_attr"]

            elif ntype == "shape":
                new_ntag = self._add_node_shape(
                    shape=ndata.get("shape", "Square (Pulsed)"),
                    freq=ndata.get("freq", 20.0),
                    duty=ndata.get("duty", 0.40),
                    pos=pos
                )
                tag_remap[ndata["in_attr"]] = self._custom_nodes[new_ntag]["in_attr"]
                if "in_freq" in ndata: tag_remap[ndata["in_freq"]] = self._custom_nodes[new_ntag]["in_freq"]
                tag_remap[ndata["out_attr"]] = self._custom_nodes[new_ntag]["out_attr"]

        # Base sensors & motors map to themselves
        for base_tag in ["attr_out_abs", "attr_out_tc", "attr_out_over", "attr_out_und", "attr_out_const", "attr_in_low", "attr_in_high"]:
            tag_remap[base_tag] = base_tag

        # 3. Re-wire links
        links = graph_data.get("links", [])
        for src_out, tgt_in in links:
            mapped_src = tag_remap.get(src_out, src_out)
            mapped_tgt = tag_remap.get(tgt_in, tgt_in)

            if dpg.does_item_exist(mapped_src) and dpg.does_item_exist(mapped_tgt):
                self._cb_node_link("node_editor_canvas", (mapped_src, mapped_tgt))

        # 4. Auto-arrange node layout neatly into topological columns
        self.auto_arrange_nodes()

    def auto_arrange_nodes(self):
        """Topologically calculates depth layer columns for all graph nodes and auto-arranges their positions."""
        if not dpg.does_item_exist("node_editor_canvas"):
            return

        # 1. Map attribute tags to node tags
        attr_to_node: Dict[str, str] = {}

        # Sensor output pins
        for s_pin in [
            "attr_out_abs", "attr_out_abs_l", "attr_out_abs_r",
            "attr_out_tc", "attr_out_tc_l", "attr_out_tc_r",
            "attr_out_over", "attr_out_over_l", "attr_out_over_r",
            "attr_out_und", "attr_out_und_l", "attr_out_und_r"
        ]:
            attr_to_node[s_pin] = "node_sensors"

        # Motor input pins
        for m_pin in ["attr_in_low", "attr_in_high"]:
            attr_to_node[m_pin] = "node_xinput"

        # Custom nodes pins
        all_node_tags = []
        if dpg.does_item_exist("node_sensors"):
            all_node_tags.append("node_sensors")

        for ntag, ninfo in self._custom_nodes.items():
            if dpg.does_item_exist(ntag):
                all_node_tags.append(ntag)
                for key in ["out_attr", "in_a", "in_b", "in_attr", "in_on", "in_off"]:
                    val = ninfo.get(key)
                    if val:
                        attr_to_node[val] = ntag

        if dpg.does_item_exist("node_xinput"):
            all_node_tags.append("node_xinput")

        # 2. Build adjacency list of incoming node connections
        incoming_nodes: Dict[str, set] = {ntag: set() for ntag in all_node_tags}
        for link_id, (src_out, tgt_in) in self._node_links.items():
            src_node = attr_to_node.get(src_out)
            tgt_node = attr_to_node.get(tgt_in)
            if src_node and tgt_node and src_node != tgt_node:
                incoming_nodes[tgt_node].add(src_node)

        # 3. Calculate topological depth for each node
        node_depths: Dict[str, int] = {ntag: 0 for ntag in all_node_tags}
        node_depths["node_sensors"] = 0

        changed = True
        iterations = 0
        while changed and iterations < 50:
            changed = False
            iterations += 1
            for ntag in all_node_tags:
                if ntag == "node_sensors":
                    continue
                parents = incoming_nodes[ntag]
                if parents:
                    new_depth = max(node_depths[p] for p in parents) + 1
                else:
                    new_depth = 1  # Independent node (e.g. constant)

                if new_depth != node_depths[ntag]:
                    node_depths[ntag] = new_depth
                    changed = True

        max_inter_depth = max([d for n, d in node_depths.items() if n != "node_xinput"], default=1)
        node_depths["node_xinput"] = max_inter_depth + 1

        # 4. Group nodes by column layer
        columns: Dict[int, List[str]] = {}
        for ntag, depth in node_depths.items():
            columns.setdefault(depth, []).append(ntag)

        # 5. Position nodes in organized columns
        col_x_start = 30.0
        col_x_spacing = 260.0
        row_y_start = 40.0
        row_y_spacing = 180.0

        for depth in sorted(columns.keys()):
            n_list = columns[depth]
            x_pos = col_x_start + (depth * col_x_spacing)

            for idx, ntag in enumerate(n_list):
                if ntag == "node_sensors":
                    y_pos = 40.0
                elif ntag == "node_xinput":
                    y_pos = 120.0
                else:
                    y_pos = row_y_start + (idx * row_y_spacing)

                dpg.set_item_pos(ntag, [float(x_pos), float(y_pos)])

        self.recompile_and_update_synth()

    def recompile_and_update_synth(self):
        """Compiles current graph state and updates the high-frequency synthesizer thread."""
        graph_dict = self.export_graph_to_dict()
        try:
            compiled_fn = GraphCompiler.compile_graph(graph_dict)
            if self._synth_engine:
                self._synth_engine.set_compiled_func(compiled_fn)
        except Exception as e:
            print(f"[NodeEditor] Graph compilation error: {e}")

    # ── Preset Callbacks ──────────────────────────────────────────────────────
    # ── Preset Callbacks ──────────────────────────────────────────────────────
    def _cb_load_preset(self):
        preset_name = dpg.get_value("combo_preset_select")
        prof = self._profile_manager.get_profile(preset_name)
        if prof:
            self._profile_manager.set_active(preset_name)
            self.import_graph_from_dict(prof.graph_data)
        self._update_preset_ui_state()

    def _cb_save_preset(self):
        preset_name = dpg.get_value("combo_preset_select")
        graph_dict = self.export_graph_to_dict()
        prof, msg = self._profile_manager.save_profile(preset_name, graph_dict)
        if prof:
            names = self._profile_manager.list_names()
            dpg.configure_item("combo_preset_select", items=names, default_value=prof.name)
            self._update_preset_ui_state()

    def _cb_clone_preset(self):
        preset_name = dpg.get_value("combo_preset_select")
        cloned_prof, msg = self._profile_manager.clone_profile(preset_name)
        if cloned_prof:
            names = self._profile_manager.list_names()
            dpg.configure_item("combo_preset_select", items=names, default_value=cloned_prof.name)
            self.import_graph_from_dict(cloned_prof.graph_data)
            self._update_preset_ui_state()

    def _cb_delete_preset(self):
        preset_name = dpg.get_value("combo_preset_select")
        success, msg = self._profile_manager.delete_profile(preset_name)
        if success:
            active_name = self._profile_manager._active_profile_name
            dpg.configure_item("combo_preset_select", items=self._profile_manager.list_names(), default_value=active_name)
            self._cb_load_preset()

    def _cb_change_frequency(self, sender, app_data):
        freq_str = app_data
        if "50 Hz" in freq_str:
            freq = 50
        elif "1000 Hz" in freq_str:
            freq = 1000
        else:
            freq = 200

        if self._synth_engine:
            self._synth_engine.set_frequency(freq)

    def _show_python_code_modal(self):
        """Opens a DPG modal window displaying the standalone generated Python source code."""
        modal_tag = "modal_python_code_export"
        if dpg.does_item_exist(modal_tag):
            dpg.delete_item(modal_tag)

        graph_dict = self.export_graph_to_dict()
        py_source = GraphCompiler.generate_python_source(graph_dict)

        with dpg.window(label="Generated Python Graph Code", tag=modal_tag, modal=True, show=True, width=700, height=500, pos=(250, 100)):
            dpg.add_text("Standalone Compiled Python Function for High-Frequency Synthesizer Engine:", color=[0, 210, 255, 255])
            dpg.add_spacer(height=6)
            dpg.add_input_text(multiline=True, readonly=True, default_value=py_source, width=-1, height=400)
            dpg.add_spacer(height=6)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Close", width=120, callback=lambda: dpg.delete_item(modal_tag))
