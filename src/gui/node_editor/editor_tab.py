"""
SimPad Haptic Middleware — Node Editor Tab.
Main orchestrator for Node Editor UI canvas, toolbars, links, preset management, and synthesis compilation.
"""

import dearpygui.dearpygui as dpg
from typing import Dict, Any, List, Optional, Tuple

from src.core.compiler import GraphCompiler
from src.profiles.manager import GraphProfileManager
from src.gui.node_editor.graph_layout import NodeGraphArranger
from src.gui.node_editor.node_factory_ui import NodeUIFactory
from src.gui.node_editor.sidebar_control import NodeSidebarControl


class NodeEditorTab:
    """Encapsulates the DearPyGui Node Editor interface and dynamic graph solver."""

    def __init__(self, synth_engine=None):
        self._custom_nodes: Dict[str, dict] = {}
        self._node_links: Dict[int, Tuple[str, str]] = {}
        self._synth_engine = synth_engine
        self._profile_manager = GraphProfileManager()
        self._factory = NodeUIFactory()
        self._sidebar = NodeSidebarControl()

    def set_synth_engine(self, synth_engine):
        self._synth_engine = synth_engine
        self.recompile_and_update_synth()

    def build_tab(self, parent_app):
        """Constructs the Node Editor tab UI layout."""
        self._parent = parent_app

        with dpg.group(horizontal=False):
            # Top Toolbar 1: Profiles & Synthesizer Controls
            with dpg.child_window(height=42, border=True):
                with dpg.group(horizontal=True):
                    dpg.add_text("Profiles:", color=[255, 200, 0, 255])
                    dpg.add_combo(
                        items=self._profile_manager.list_display_names(),
                        default_value=self._profile_manager.get_display_name(self._profile_manager._active_profile_name),
                        width=150,
                        tag="combo_profile_select",
                        callback=self._cb_load_preset
                    )
                    dpg.add_button(label="+ New Profile", tag="btn_new_profile", callback=self._open_new_profile_modal)
                    dpg.add_button(label="Save Profile", tag="btn_save_profile", callback=self._cb_save_preset)
                    dpg.add_button(label="Rename", tag="btn_rename_profile", callback=self._open_rename_profile_modal)
                    dpg.add_button(label="Clone Profile", tag="btn_clone_profile", callback=self._cb_clone_preset)
                    dpg.add_button(label="Delete Profile", tag="btn_delete_profile", callback=self._cb_delete_preset)


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

            # Keyboard Handler: Bind Delete / Suppr / F2 keys
            handler_tag = "node_editor_key_handler"
            if dpg.does_item_exist(handler_tag):
                dpg.delete_item(handler_tag)
            with dpg.handler_registry(tag=handler_tag):
                dpg.add_key_press_handler(dpg.mvKey_Delete, callback=lambda: self._delete_selected_items())
                dpg.add_key_press_handler(dpg.mvKey_Back, callback=lambda: self._delete_selected_items())
                dpg.add_key_press_handler(dpg.mvKey_F2, callback=lambda: self._open_rename_node_modal())


            with dpg.group(horizontal=True):
                # 1. Left Sidebar: Vertical Node Creation Toolbox
                with dpg.child_window(width=195, height=-1, border=True):
                    dpg.add_text("Node Toolbox", color=[0, 210, 255, 255])
                    dpg.add_text("Click to add node:", color=[140, 140, 140, 255])
                    dpg.add_separator()
                    dpg.add_spacer(height=4)

                    dpg.add_text("Telemetry Sensors", color=[255, 220, 0, 255])
                    dpg.add_button(label="+ Over-Braking Sensor", width=-1, callback=lambda: self._add_node_sensor_abs())
                    dpg.add_spacer(height=2)
                    dpg.add_button(label="+ Over-Accel Sensor", width=-1, callback=lambda: self._add_node_sensor_tc())
                    dpg.add_spacer(height=2)
                    dpg.add_button(label="+ Oversteer Sensor", width=-1, callback=lambda: self._add_node_sensor_over())
                    dpg.add_spacer(height=2)
                    dpg.add_button(label="+ Understeer Sensor", width=-1, callback=lambda: self._add_node_sensor_und())
                    dpg.add_spacer(height=2)
                    dpg.add_button(label="+ Engine Regime Sensor", width=-1, callback=lambda: self._add_node_sensor_engine())
                    dpg.add_spacer(height=2)
                    dpg.add_button(label="+ Wheel Travel Sensor", width=-1, callback=lambda: self._add_node_sensor_travel())
                    dpg.add_spacer(height=6)
                    dpg.add_separator()
                    dpg.add_spacer(height=4)

                    dpg.add_text("Haptic Motors (Outputs)", color=[255, 60, 60, 255])
                    dpg.add_button(label="+ XInput Vibration", width=-1, callback=lambda: self._add_node_output_xinput())
                    dpg.add_spacer(height=6)
                    dpg.add_separator()
                    dpg.add_spacer(height=4)

                    dpg.add_text("Processing Nodes", color=[0, 210, 255, 255])

                    dpg.add_button(label="+ Constant [0,1]", width=-1, callback=lambda: self._add_node_constant())
                    dpg.add_spacer(height=2)
                    dpg.add_button(label="+ Float Constant", width=-1, callback=lambda: self._add_node_float_constant())
                    dpg.add_spacer(height=2)
                    dpg.add_button(label="+ Multiply [0,1]", width=-1, callback=lambda: self._add_node_multiply())
                    dpg.add_spacer(height=2)
                    dpg.add_button(label="+ Array Multiplier", width=-1, callback=lambda: self._add_node_array_multiply())
                    dpg.add_spacer(height=2)
                    dpg.add_button(label="+ Normalize", width=-1, callback=lambda: self._add_node_normalize())
                    dpg.add_spacer(height=2)
                    dpg.add_button(label="+ Math Mix", width=-1, callback=lambda: self._add_node_math())
                    dpg.add_spacer(height=2)
                    dpg.add_button(label="+ Transform & Curve", width=-1, callback=lambda: self._add_node_transform())
                    dpg.add_spacer(height=2)
                    dpg.add_button(label="+ Waveform Shape", width=-1, callback=lambda: self._add_node_shape())

                # 2. Center: DearPyGui Node Editor Canvas (Expands to fill center space)
                with dpg.child_window(width=-330, height=-1, border=True):
                    with dpg.node_editor(
                        tag="node_editor_canvas",
                        callback=self._cb_node_link,
                        delink_callback=self._cb_node_delink,
                        width=-1,
                        height=-1,
                    ):
                        # 1. INPUT NODES: 4 Separate Telemetry Sensors
                        # 1a. Over-Braking Sensor Node
                        with dpg.node(label="Input: Over-Braking", tag="node_sensor_abs", pos=[30.0, 40.0]):
                            with dpg.node_attribute(label="Over-Braking Max", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_abs"):
                                dpg.add_text("Over-Braking (Max)", color=[255, 220, 0, 255])
                            with dpg.node_attribute(label="Over-Braking Left", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_abs_l"):
                                dpg.add_text("Over-Braking (Left)", color=[255, 220, 0, 255])
                            with dpg.node_attribute(label="Over-Braking Right", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_abs_r"):
                                dpg.add_text("Over-Braking (Right)", color=[255, 220, 0, 255])

                        # 1b. Over-Acceleration Sensor Node
                        with dpg.node(label="Input: Over-Acceleration", tag="node_sensor_tc", pos=[30.0, 160.0]):
                            with dpg.node_attribute(label="Over-Accel Max", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_tc"):
                                dpg.add_text("Over-Accel (Max)", color=[255, 220, 0, 255])
                            with dpg.node_attribute(label="Over-Accel Left", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_tc_l"):
                                dpg.add_text("Over-Accel (Left)", color=[255, 220, 0, 255])
                            with dpg.node_attribute(label="Over-Accel Right", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_tc_r"):
                                dpg.add_text("Over-Accel (Right)", color=[255, 220, 0, 255])

                        # 1c. Oversteer Sensor Node
                        with dpg.node(label="Input: Oversteer", tag="node_sensor_over", pos=[30.0, 280.0]):
                            with dpg.node_attribute(label="Oversteer Max", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_over"):
                                dpg.add_text("Oversteer (Max)", color=[255, 220, 0, 255])
                            with dpg.node_attribute(label="Oversteer Left", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_over_l"):
                                dpg.add_text("Oversteer (Left)", color=[255, 220, 0, 255])
                            with dpg.node_attribute(label="Oversteer Right", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_over_r"):
                                dpg.add_text("Oversteer (Right)", color=[255, 220, 0, 255])

                        # 1d. Understeer Sensor Node
                        with dpg.node(label="Input: Understeer", tag="node_sensor_und", pos=[30.0, 400.0]):
                            with dpg.node_attribute(label="Understeer Max", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_und"):
                                dpg.add_text("Understeer (Max)", color=[255, 220, 0, 255])
                            with dpg.node_attribute(label="Understeer Left", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_und_l"):
                                dpg.add_text("Understeer (Left)", color=[255, 220, 0, 255])
                            with dpg.node_attribute(label="Understeer Right", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_und_r"):
                                dpg.add_text("Understeer (Right)", color=[255, 220, 0, 255])

                        # 2. OUTPUT NODE: XInput Vibration Motors
                        with dpg.node(label="Output: XInput Vibration", tag="node_xinput", pos=[580.0, 120.0]):
                            with dpg.node_attribute(label="Low Freq (Rumble)", attribute_type=dpg.mvNode_Attr_Input, tag="attr_in_low"):
                                dpg.add_text("Low Freq Rumble (Left)", color=[255, 220, 0, 255])
                            with dpg.node_attribute(label="High Freq (Buzz)", attribute_type=dpg.mvNode_Attr_Input, tag="attr_in_high"):
                                dpg.add_text("High Freq Buzz (Right)", color=[255, 220, 0, 255])

                        # Apply pin themes
                        for sensor_pin in [
                            "attr_out_abs", "attr_out_abs_l", "attr_out_abs_r",
                            "attr_out_tc", "attr_out_tc_l", "attr_out_tc_r",
                            "attr_out_over", "attr_out_over_l", "attr_out_over_r",
                            "attr_out_und", "attr_out_und_l", "attr_out_und_r"
                        ]:
                            self._apply_pin_theme(sensor_pin, "normalized")

                        self._apply_pin_theme("attr_in_low", "sum_array")
                        self._apply_pin_theme("attr_in_high", "sum_array")

                # Right: Interactive Test Sidebar
                self._sidebar.build_sidebar(self)


        # Load active preset on startup
        active_preset = self._profile_manager.get_active()
        if active_preset:
            self.import_graph_from_dict(active_preset.graph_data)
            self._update_preset_ui_state()

    # ── Delegation Helpers ───────────────────────────────────────────────────
    def _apply_pin_theme(self, attr_tag: str, pin_type: Any = "normalized", is_normalized: Optional[bool] = None, is_square: bool = False):
        self._factory.apply_pin_theme(attr_tag, pin_type, is_normalized, is_square)

    def _get_node_dimensions(self, ntag: str) -> Tuple[float, float]:
        return NodeGraphArranger.get_node_dimensions(ntag, self._custom_nodes)

    def auto_arrange_nodes(self):
        NodeGraphArranger.auto_arrange_nodes(self._custom_nodes, self._node_links, self.recompile_and_update_synth)

    def evaluate_graph(self) -> Tuple[float, float]:
        return self._sidebar.evaluate_graph(self._synth_engine, self._profile_manager, self._update_preset_ui_state)

    def _on_test_sensor_change(self):
        self._sidebar.on_test_sensor_change(self._synth_engine)

    def _trigger_sensor_pulse(self, tag_name: str):
        self._sidebar.trigger_sensor_pulse(self._synth_engine, tag_name)

    def _reset_test_sensors(self):
        self._sidebar.reset_test_sensors(self._synth_engine)

    # ── Toolbox Callbacks ────────────────────────────────────────────────────
    def _add_node_sensor_abs(self, pos=(30.0, 40.0)):
        return self._factory.add_node_sensor_abs(self._custom_nodes, self.recompile_and_update_synth, pos)

    def _add_node_sensor_tc(self, pos=(30.0, 160.0)):
        return self._factory.add_node_sensor_tc(self._custom_nodes, self.recompile_and_update_synth, pos)

    def _add_node_sensor_over(self, pos=(30.0, 280.0)):
        return self._factory.add_node_sensor_over(self._custom_nodes, self.recompile_and_update_synth, pos)

    def _add_node_sensor_und(self, pos=(30.0, 400.0)):
        return self._factory.add_node_sensor_und(self._custom_nodes, self.recompile_and_update_synth, pos)

    def _add_node_sensor_engine(self, pos=(30.0, 520.0)):
        return self._factory.add_node_sensor_engine(self._custom_nodes, self.recompile_and_update_synth, pos)

    def _add_node_sensor_travel(self, pos=(30.0, 640.0)):
        return self._factory.add_node_sensor_travel(self._custom_nodes, self.recompile_and_update_synth, pos)

    def _add_node_output_xinput(self, pos=(580.0, 120.0)):
        return self._factory.add_node_output_xinput(self._custom_nodes, self.recompile_and_update_synth, pos)

    def _add_node_constant(self, val: float = 0.5, pos=(240.0, 280.0)):
        if not isinstance(val, (int, float)):
            val = 0.5
        return self._factory.add_node_constant(self._custom_nodes, self.recompile_and_update_synth, val, pos)

    def _add_node_float_constant(self, val: float = 20.0, pos=(240.0, 340.0)):
        if not isinstance(val, (int, float)):
            val = 20.0
        return self._factory.add_node_float_constant(self._custom_nodes, self.recompile_and_update_synth, val, pos)

    def _add_node_multiply(self, pos=(240.0, 40.0)):
        return self._factory.add_node_multiply(self._custom_nodes, self.recompile_and_update_synth, pos)

    def _add_node_array_multiply(self, pos=(240.0, 60.0)):
        return self._factory.add_node_array_multiply(self._custom_nodes, self.recompile_and_update_synth, pos)

    def _add_node_normalize(self, min_val=0.0, max_val=100.0, clamp=True, pos=(240.0, 100.0)):
        if not isinstance(min_val, (int, float)):
            min_val = 0.0
        return self._factory.add_node_normalize(self._custom_nodes, self.recompile_and_update_synth, min_val, max_val, clamp, pos)

    def _add_node_math(self, op="Multiply (*)", pos=(240.0, 40.0)):
        if not isinstance(op, str):
            op = "Multiply (*)"
        return self._factory.add_node_math(self._custom_nodes, self.recompile_and_update_synth, op, pos)

    def _add_node_transform(self, thresh=0.15, gain=1.0, gamma=1.0, pos=(240.0, 160.0)):
        if not isinstance(thresh, (int, float)):
            thresh = 0.15
        return self._factory.add_node_transform(self._custom_nodes, self.recompile_and_update_synth, thresh, gain, gamma, pos)

    def _add_node_shape(self, shape="Square (Pulsed)", freq=20.0, duty=0.40, pos=(240.0, 420.0)):
        if not isinstance(shape, str):
            shape = "Square (Pulsed)"
        return self._factory.add_node_shape(self._custom_nodes, self.recompile_and_update_synth, shape, freq, duty, pos)

    def _delete_custom_node(self, node_tag: str):
        self._factory.delete_custom_node(self._custom_nodes, self._node_links, node_tag, self.recompile_and_update_synth)

    def _delete_selected_items(self):
        """Keyboard Del / Suppr Key Handler: Deletes selected nodes and links."""
        if not dpg.does_item_exist("node_editor_canvas"):
            return

        selected_links = dpg.get_selected_links("node_editor_canvas")
        for link_id in selected_links:
            if link_id in self._node_links:
                del self._node_links[link_id]
            if dpg.does_item_exist(link_id):
                dpg.delete_item(link_id)

        selected_nodes = dpg.get_selected_nodes("node_editor_canvas")
        for node_id in selected_nodes:
            node_tag = None
            if node_id in self._custom_nodes:
                node_tag = node_id
            else:
                for ntag in list(self._custom_nodes.keys()):
                    if dpg.does_item_exist(ntag) and (dpg.get_alias_id(ntag) == node_id or ntag == node_id):
                        node_tag = ntag
                        break

            if node_tag:
                self._delete_custom_node(node_tag)
            else:
                target_tag = node_id
                if not dpg.does_item_exist(target_tag):
                    for btag in ["node_sensor_abs", "node_sensor_tc", "node_sensor_over", "node_sensor_und", "node_sensors", "node_xinput"]:
                        if dpg.does_item_exist(btag) and dpg.get_alias_id(btag) == node_id:
                            target_tag = btag
                            break

                if dpg.does_item_exist(target_tag):
                    children = dpg.get_item_children(target_tag, slot=1) or []
                    attr_ids = set(children)
                    links_to_delete = []
                    for link_id, (o, i) in list(self._node_links.items()):
                        o_id = dpg.get_alias_id(o) if dpg.does_item_exist(o) else o
                        i_id = dpg.get_alias_id(i) if dpg.does_item_exist(i) else i
                        if o in attr_ids or i in attr_ids or o_id in attr_ids or i_id in attr_ids:
                            links_to_delete.append(link_id)

                    for lid in links_to_delete:
                        if lid in self._node_links:
                            del self._node_links[lid]
                        if dpg.does_item_exist(lid):
                            dpg.delete_item(lid)

                    dpg.delete_item(target_tag)

        self.recompile_and_update_synth()


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

            if dpg.does_item_exist(ntag):
                lbl = dpg.get_item_label(ntag)
                if lbl:
                    ndata["label"] = lbl

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
            new_ntag = None

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

            elif ntype == "sensor_over_braking":
                new_ntag = self._add_node_sensor_abs(pos=pos)
                if "out_attr" in ndata: tag_remap[ndata["out_attr"]] = self._custom_nodes[new_ntag]["out_attr"]
                if "out_l" in ndata: tag_remap[ndata["out_l"]] = self._custom_nodes[new_ntag]["out_l"]
                if "out_r" in ndata: tag_remap[ndata["out_r"]] = self._custom_nodes[new_ntag]["out_r"]

            elif ntype == "sensor_over_accel":
                new_ntag = self._add_node_sensor_tc(pos=pos)
                if "out_attr" in ndata: tag_remap[ndata["out_attr"]] = self._custom_nodes[new_ntag]["out_attr"]
                if "out_l" in ndata: tag_remap[ndata["out_l"]] = self._custom_nodes[new_ntag]["out_l"]
                if "out_r" in ndata: tag_remap[ndata["out_r"]] = self._custom_nodes[new_ntag]["out_r"]

            elif ntype == "sensor_oversteer":
                new_ntag = self._add_node_sensor_over(pos=pos)
                if "out_attr" in ndata: tag_remap[ndata["out_attr"]] = self._custom_nodes[new_ntag]["out_attr"]
                if "out_l" in ndata: tag_remap[ndata["out_l"]] = self._custom_nodes[new_ntag]["out_l"]
                if "out_r" in ndata: tag_remap[ndata["out_r"]] = self._custom_nodes[new_ntag]["out_r"]

            elif ntype == "sensor_understeer":
                new_ntag = self._add_node_sensor_und(pos=pos)
                if "out_attr" in ndata: tag_remap[ndata["out_attr"]] = self._custom_nodes[new_ntag]["out_attr"]
                if "out_l" in ndata: tag_remap[ndata["out_l"]] = self._custom_nodes[new_ntag]["out_l"]
                if "out_r" in ndata: tag_remap[ndata["out_r"]] = self._custom_nodes[new_ntag]["out_r"]

            elif ntype == "sensor_engine_regime":
                new_ntag = self._add_node_sensor_engine(pos=pos)
                if "out_over_rev" in ndata: tag_remap[ndata["out_over_rev"]] = self._custom_nodes[new_ntag]["out_over_rev"]
                if "out_under_rev" in ndata: tag_remap[ndata["out_under_rev"]] = self._custom_nodes[new_ntag]["out_under_rev"]
                if "out_rpm" in ndata: tag_remap[ndata["out_rpm"]] = self._custom_nodes[new_ntag]["out_rpm"]

            elif ntype == "sensor_wheel_travel":
                new_ntag = self._add_node_sensor_travel(pos=pos)
                if "out_attr" in ndata: tag_remap[ndata["out_attr"]] = self._custom_nodes[new_ntag]["out_attr"]
                if "out_l" in ndata: tag_remap[ndata["out_l"]] = self._custom_nodes[new_ntag]["out_l"]
                if "out_r" in ndata: tag_remap[ndata["out_r"]] = self._custom_nodes[new_ntag]["out_r"]
                if "out_fl" in ndata: tag_remap[ndata["out_fl"]] = self._custom_nodes[new_ntag]["out_fl"]
                if "out_fr" in ndata: tag_remap[ndata["out_fr"]] = self._custom_nodes[new_ntag]["out_fr"]
                if "out_rl" in ndata: tag_remap[ndata["out_rl"]] = self._custom_nodes[new_ntag]["out_rl"]
                if "out_rr" in ndata: tag_remap[ndata["out_rr"]] = self._custom_nodes[new_ntag]["out_rr"]

            elif ntype == "output_xinput":
                new_ntag = self._add_node_output_xinput(pos=pos)
                if "in_low" in ndata: tag_remap[ndata["in_low"]] = self._custom_nodes[new_ntag]["in_low"]
                if "in_high" in ndata: tag_remap[ndata["in_high"]] = self._custom_nodes[new_ntag]["in_high"]

            if new_ntag and "label" in ndata and dpg.does_item_exist(new_ntag):
                dpg.configure_item(new_ntag, label=ndata["label"])
                if new_ntag in self._custom_nodes:
                    self._custom_nodes[new_ntag]["label"] = ndata["label"]

        # Base sensors & motors map to themselves
        for base_tag in [
            "attr_out_abs", "attr_out_abs_l", "attr_out_abs_r",
            "attr_out_tc", "attr_out_tc_l", "attr_out_tc_r",
            "attr_out_over", "attr_out_over_l", "attr_out_over_r",
            "attr_out_und", "attr_out_und_l", "attr_out_und_r",
            "attr_out_over_rev", "attr_out_under_rev", "attr_out_rpm",
            "attr_out_travel", "attr_out_travel_l", "attr_out_travel_r",
            "attr_out_travel_fl", "attr_out_travel_fr", "attr_out_travel_rl", "attr_out_travel_rr",
            "attr_out_const", "attr_in_low", "attr_in_high"
        ]:
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

    def recompile_and_update_synth(self):
        """Compiles current graph state and updates the high-frequency synthesizer thread."""
        graph_dict = self.export_graph_to_dict()
        try:
            compiled_fn = GraphCompiler.compile_graph(graph_dict)
            if self._synth_engine:
                self._synth_engine.set_compiled_func(compiled_fn)
        except Exception as e:
            print(f"[NodeEditor] Graph compilation error: {e}")

    # ── Profile Callbacks & Modals ────────────────────────────────────────────
    def _cb_load_preset(self):
        selected_display = dpg.get_value("combo_profile_select") if dpg.does_item_exist("combo_profile_select") else ""
        prof = self._profile_manager.get_profile(selected_display)
        if prof:
            self._profile_manager.set_active(prof.name)
            self.import_graph_from_dict(prof.graph_data)
        self._update_preset_ui_state()

    def _cb_save_preset(self):
        selected_display = dpg.get_value("combo_profile_select") if dpg.does_item_exist("combo_profile_select") else ""
        graph_dict = self.export_graph_to_dict()
        prof, msg = self._profile_manager.save_profile(selected_display, graph_dict)
        if prof:
            displays = self._profile_manager.list_display_names()
            new_disp = self._profile_manager.get_display_name(prof.name)
            dpg.configure_item("combo_profile_select", items=displays, default_value=new_disp)
            self._update_preset_ui_state()

    def _cb_clone_preset(self):
        selected_display = dpg.get_value("combo_profile_select") if dpg.does_item_exist("combo_profile_select") else ""
        cloned_prof, msg = self._profile_manager.clone_profile(selected_display)
        if cloned_prof:
            displays = self._profile_manager.list_display_names()
            new_disp = self._profile_manager.get_display_name(cloned_prof.name)
            dpg.configure_item("combo_profile_select", items=displays, default_value=new_disp)
            self.import_graph_from_dict(cloned_prof.graph_data)
            self._update_preset_ui_state()

    def _cb_delete_preset(self):
        selected_display = dpg.get_value("combo_profile_select") if dpg.does_item_exist("combo_profile_select") else ""
        success, msg = self._profile_manager.delete_profile(selected_display)
        if success:
            displays = self._profile_manager.list_display_names()
            active_disp = self._profile_manager.get_display_name(self._profile_manager._active_profile_name)
            dpg.configure_item("combo_profile_select", items=displays, default_value=active_disp)
            self._cb_load_preset()

    def _get_centered_modal_pos(self, width: int = 440, height: int = 170) -> Tuple[int, int]:
        vp_w = dpg.get_viewport_width() if dpg.is_viewport_ok() else 1240
        vp_h = dpg.get_viewport_height() if dpg.is_viewport_ok() else 780
        pos_x = max(20, (vp_w - width) // 2)
        pos_y = max(20, (vp_h - height) // 2)
        return (pos_x, pos_y)

    def _open_new_profile_modal(self):
        """Opens a DPG modal window prompting the user to name a new blank profile."""
        modal_tag = "modal_new_profile"
        if dpg.does_item_exist(modal_tag):
            dpg.delete_item(modal_tag)

        input_tag = "input_new_profile_name"
        pos = self._get_centered_modal_pos(440, 170)

        base_name = "New Profile"
        counter = 1
        default_name = base_name
        while default_name in self._profile_manager.profiles:
            counter += 1
            default_name = f"{base_name} {counter}"

        def create_new_profile():
            new_name = dpg.get_value(input_tag).strip()
            if not new_name:
                return
            blank_graph = {"nodes": {}, "links": []}
            prof, msg = self._profile_manager.save_profile(new_name, blank_graph)
            if prof:
                displays = self._profile_manager.list_display_names()
                new_disp = self._profile_manager.get_display_name(prof.name)
                dpg.configure_item("combo_profile_select", items=displays, default_value=new_disp)
                self.import_graph_from_dict(blank_graph)
                self._update_preset_ui_state()
            if dpg.does_item_exist(modal_tag):
                dpg.delete_item(modal_tag)

        with dpg.window(label="Create New Profile", tag=modal_tag, modal=True, show=True, no_resize=True, width=440, height=170, pos=pos):
            dpg.add_text("Enter name for the new profile:", color=[255, 200, 0, 255])
            dpg.add_spacer(height=6)
            dpg.add_input_text(default_value=default_name, width=-1, tag=input_tag, on_enter=True, callback=lambda: create_new_profile())
            dpg.add_spacer(height=14)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Create", width=110, callback=lambda: create_new_profile())
                dpg.add_button(label="Cancel", width=110, callback=lambda: dpg.delete_item(modal_tag) if dpg.does_item_exist(modal_tag) else None)

    def _open_rename_profile_modal(self):
        """Opens a DPG modal window allowing the user to rename the active user profile."""
        selected_display = dpg.get_value("combo_profile_select") if dpg.does_item_exist("combo_profile_select") else ""
        prof = self._profile_manager.get_profile(selected_display)
        if not prof or prof.is_preset:
            return

        modal_tag = "modal_rename_profile"
        if dpg.does_item_exist(modal_tag):
            dpg.delete_item(modal_tag)

        input_tag = "input_rename_profile_name"
        pos = self._get_centered_modal_pos(440, 170)

        def apply_profile_rename():
            new_name = dpg.get_value(input_tag).strip()
            if not new_name:
                return
            renamed_prof, msg = self._profile_manager.rename_profile(selected_display, new_name)
            if renamed_prof:
                displays = self._profile_manager.list_display_names()
                new_disp = self._profile_manager.get_display_name(renamed_prof.name)
                dpg.configure_item("combo_profile_select", items=displays, default_value=new_disp)
                self._update_preset_ui_state()
            if dpg.does_item_exist(modal_tag):
                dpg.delete_item(modal_tag)

        with dpg.window(label="Rename Profile", tag=modal_tag, modal=True, show=True, no_resize=True, width=440, height=170, pos=pos):
            dpg.add_text(f"Rename Profile '{prof.name}':", color=[255, 200, 0, 255])
            dpg.add_spacer(height=6)
            dpg.add_input_text(default_value=prof.name, width=-1, tag=input_tag, on_enter=True, callback=lambda: apply_profile_rename())
            dpg.add_spacer(height=14)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Apply", width=110, callback=lambda: apply_profile_rename())
                dpg.add_button(label="Cancel", width=110, callback=lambda: dpg.delete_item(modal_tag) if dpg.does_item_exist(modal_tag) else None)

    def _open_rename_node_modal(self):
        """Opens a DPG modal window allowing the user to rename the currently selected node (F2 key)."""
        if not dpg.does_item_exist("node_editor_canvas"):
            return

        selected_nodes = dpg.get_selected_nodes("node_editor_canvas")
        if not selected_nodes:
            return

        node_id = selected_nodes[0]
        node_tag = node_id
        if node_id not in self._custom_nodes:
            for ntag in list(self._custom_nodes.keys()):
                if dpg.does_item_exist(ntag) and (dpg.get_alias_id(ntag) == node_id or ntag == node_id):
                    node_tag = ntag
                    break

        current_label = dpg.get_item_label(node_tag) if dpg.does_item_exist(node_tag) else "Node"

        modal_tag = "modal_rename_node"
        if dpg.does_item_exist(modal_tag):
            dpg.delete_item(modal_tag)

        input_tag = "input_rename_node_label"
        pos = self._get_centered_modal_pos(440, 170)

        def apply_node_rename():
            new_label = dpg.get_value(input_tag).strip()
            if new_label and dpg.does_item_exist(node_tag):
                dpg.configure_item(node_tag, label=new_label)
                if node_tag in self._custom_nodes:
                    self._custom_nodes[node_tag]["label"] = new_label
                self.recompile_and_update_synth()
            if dpg.does_item_exist(modal_tag):
                dpg.delete_item(modal_tag)

        with dpg.window(label="Rename Node (F2)", tag=modal_tag, modal=True, show=True, no_resize=True, width=440, height=170, pos=pos):
            dpg.add_text("Enter new node display label:", color=[0, 210, 255, 255])
            dpg.add_spacer(height=6)
            dpg.add_input_text(default_value=current_label, width=-1, tag=input_tag, on_enter=True, callback=lambda: apply_node_rename())
            dpg.add_spacer(height=14)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Apply", width=110, callback=lambda: apply_node_rename())
                dpg.add_button(label="Cancel", width=110, callback=lambda: dpg.delete_item(modal_tag) if dpg.does_item_exist(modal_tag) else None)


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

    def _set_button_enabled(self, btn_tag: str, enabled: bool):
        if not dpg.does_item_exist(btn_tag):
            return
        dpg.configure_item(btn_tag, enabled=enabled)
        if enabled:
            dpg.bind_item_theme(btn_tag, 0)
        else:
            if not hasattr(self, "_disabled_btn_theme") or not dpg.does_item_exist(self._disabled_btn_theme):
                with dpg.theme() as theme:
                    with dpg.theme_component(dpg.mvButton):
                        dpg.add_theme_color(dpg.mvThemeCol_Button, [45, 45, 52, 255])
                        dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, [45, 45, 52, 255])
                        dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, [45, 45, 52, 255])
                        dpg.add_theme_color(dpg.mvThemeCol_Text, [120, 120, 130, 255])
                self._disabled_btn_theme = theme
            dpg.bind_item_theme(btn_tag, self._disabled_btn_theme)

    def _update_preset_ui_state(self):
        """Disables and grays out Save, Rename, and Delete buttons if current profile is a read-only preset."""
        selected_display = dpg.get_value("combo_profile_select") if dpg.does_item_exist("combo_profile_select") else self._profile_manager._active_profile_name
        prof = self._profile_manager.get_profile(selected_display)
        is_preset = prof.is_preset if prof else False

        self._set_button_enabled("btn_save_profile", not is_preset)
        self._set_button_enabled("btn_rename_profile", not is_preset)
        self._set_button_enabled("btn_delete_profile", not is_preset)



    def _show_python_code_modal(self):
        """Opens a DPG modal window displaying the standalone generated Python source code."""
        modal_tag = "modal_python_code_export"
        if dpg.does_item_exist(modal_tag):
            dpg.delete_item(modal_tag)

        graph_dict = self.export_graph_to_dict()
        py_source = GraphCompiler.generate_python_source(graph_dict)
        pos = self._get_centered_modal_pos(700, 500)

        with dpg.window(label="Generated Python Graph Code", tag=modal_tag, modal=True, show=True, width=700, height=500, pos=pos):
            dpg.add_text("Standalone Compiled Python Function for High-Frequency Synthesizer Engine:", color=[0, 210, 255, 255])
            dpg.add_spacer(height=6)
            dpg.add_input_text(multiline=True, readonly=True, default_value=py_source, width=-1, height=400)
            dpg.add_spacer(height=6)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Close", width=120, callback=lambda: dpg.delete_item(modal_tag))

