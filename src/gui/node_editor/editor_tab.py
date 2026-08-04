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

            # Keyboard Handler: Bind Delete / Suppr key to delete selected nodes & links
            handler_tag = "node_editor_key_handler"
            if dpg.does_item_exist(handler_tag):
                dpg.delete_item(handler_tag)
            with dpg.handler_registry(tag=handler_tag):
                dpg.add_key_press_handler(dpg.mvKey_Delete, callback=lambda: self._delete_selected_items())
                dpg.add_key_press_handler(dpg.mvKey_Back, callback=lambda: self._delete_selected_items())

            with dpg.group(horizontal=True):
                # 1. Left Sidebar: Vertical Node Creation Toolbox
                with dpg.child_window(width=190, height=-1, border=True):
                    dpg.add_text("Node Toolbox", color=[0, 210, 255, 255])
                    dpg.add_text("Click to add node:", color=[140, 140, 140, 255])
                    dpg.add_separator()
                    dpg.add_spacer(height=4)

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
                        # 1. INPUT NODE: Telemetry Sensors
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

    def _update_preset_ui_state(self):
        """Disables Save and Delete buttons if current profile is a read-only preset."""
        selected_name = dpg.get_value("combo_preset_select") if dpg.does_item_exist("combo_preset_select") else self._profile_manager._active_profile_name
        prof = self._profile_manager.get_profile(selected_name)
        is_preset = prof.is_preset if prof else False

        if dpg.does_item_exist("btn_save_preset"):
            dpg.configure_item("btn_save_preset", enabled=not is_preset)
        if dpg.does_item_exist("btn_delete_preset"):
            dpg.configure_item("btn_delete_preset", enabled=not is_preset)

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
