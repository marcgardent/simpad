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
from src.gui.node_editor.modal_manager import EditorModalManager
from src.gui.node_editor.selection_manager import GraphSelectionManager
from src.gui.node_editor.graph_serializer import GraphSerializer


class NodeEditorTab:
    """Encapsulates the DearPyGui Node Editor interface and dynamic graph solver."""

    # Default pins for theme application
    SENSOR_PIN_TAGS = [
        "attr_out_abs", "attr_out_abs_l", "attr_out_abs_r",
        "attr_out_tc", "attr_out_tc_l", "attr_out_tc_r",
        "attr_out_over", "attr_out_over_l", "attr_out_over_r",
        "attr_out_und", "attr_out_und_l", "attr_out_und_r"
    ]

    def __init__(self, synth_engine=None):
        self._custom_nodes: Dict[str, dict] = {}
        self._node_links: Dict[int, Tuple[str, str]] = {}
        self._synth_engine = synth_engine
        self._profile_manager = GraphProfileManager()
        self._factory = NodeUIFactory()
        self._sidebar = NodeSidebarControl()
        self._modal_manager = EditorModalManager()

    def set_synth_engine(self, synth_engine):
        self._synth_engine = synth_engine
        self.recompile_and_update_synth()

    def build_tab(self, parent_app):
        """Constructs the Node Editor tab UI layout by orchestrating sub-component builders."""
        self._parent = parent_app

        with dpg.group(horizontal=False):
            self._build_top_toolbar()
            dpg.add_spacer(height=2)
            self._build_keyboard_shortcuts()

            with dpg.group(horizontal=True):
                self._build_node_toolbox()
                self._build_canvas_and_default_nodes()
                self._sidebar.build_sidebar(self)

        # Load active preset on startup
        active_preset = self._profile_manager.get_active()
        if active_preset:
            self.import_graph_from_dict(active_preset.graph_data)
            self._update_preset_ui_state()

    # ── SLAP Layout Builders ──────────────────────────────────────────────────
    def _build_top_toolbar(self):
        """Top Toolbar 1: Profiles & Synthesizer Controls."""
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

    def _build_keyboard_shortcuts(self):
        """Keyboard Handler: Bind Delete / Suppr / F2 keys."""
        handler_tag = "node_editor_key_handler"
        if dpg.does_item_exist(handler_tag):
            dpg.delete_item(handler_tag)
        with dpg.handler_registry(tag=handler_tag):
            dpg.add_key_press_handler(dpg.mvKey_Delete, callback=lambda *args: self._delete_selected_items())
            dpg.add_key_press_handler(dpg.mvKey_Back, callback=lambda *args: self._delete_selected_items())
            dpg.add_key_press_handler(dpg.mvKey_F2, callback=lambda *args: self._open_rename_node_modal())

    def _build_node_toolbox(self):
        """Left Sidebar: Vertical Node Creation Toolbox."""
        with dpg.child_window(width=195, height=-1, border=True):
            dpg.add_text("Node Toolbox", color=[0, 210, 255, 255])
            dpg.add_text("Click to add node:", color=[140, 140, 140, 255])
            dpg.add_separator()
            dpg.add_spacer(height=4)

            dpg.add_text("Telemetry Sensors", color=[255, 220, 0, 255])
            dpg.add_button(label="+ Over-Braking Sensor", width=-1, callback=lambda *args: self._add_node_sensor_abs())
            dpg.add_spacer(height=2)
            dpg.add_button(label="+ Over-Accel Sensor", width=-1, callback=lambda *args: self._add_node_sensor_tc())
            dpg.add_spacer(height=2)
            dpg.add_button(label="+ Oversteer Sensor", width=-1, callback=lambda *args: self._add_node_sensor_over())
            dpg.add_spacer(height=2)
            dpg.add_button(label="+ Understeer Sensor", width=-1, callback=lambda *args: self._add_node_sensor_und())
            dpg.add_spacer(height=2)
            dpg.add_button(label="+ Engine Regime Sensor", width=-1, callback=lambda *args: self._add_node_sensor_engine())
            dpg.add_spacer(height=2)
            dpg.add_button(label="+ Gear Sensor", width=-1, callback=lambda *args: self._add_node_sensor_gear())
            dpg.add_spacer(height=2)
            dpg.add_button(label="+ Wheel Travel Sensor", width=-1, callback=lambda *args: self._add_node_sensor_travel())
            dpg.add_spacer(height=2)
            dpg.add_button(label="+ Grip Fraction Sensor", width=-1, callback=lambda *args: self._add_node_sensor_grip())
            dpg.add_spacer(height=6)
            dpg.add_separator()
            dpg.add_spacer(height=4)

            dpg.add_text("Haptic Motors (Outputs)", color=[255, 60, 60, 255])
            dpg.add_button(label="+ XInput Vibration", width=-1, callback=lambda *args: self._add_node_output_xinput())
            dpg.add_spacer(height=6)
            dpg.add_separator()
            dpg.add_spacer(height=4)

            dpg.add_text("Processing Nodes", color=[0, 210, 255, 255])
            dpg.add_button(label="+ Constant [0,1]", width=-1, callback=lambda *args: self._add_node_constant())
            dpg.add_spacer(height=2)
            dpg.add_button(label="+ Float Constant", width=-1, callback=lambda *args: self._add_node_float_constant())
            dpg.add_spacer(height=2)
            dpg.add_button(label="+ Invert (1 - x)", width=-1, callback=lambda *args: self._add_node_invert())
            dpg.add_spacer(height=2)
            dpg.add_button(label="+ Multiply [0,1]", width=-1, callback=lambda *args: self._add_node_multiply())
            dpg.add_spacer(height=2)
            dpg.add_button(label="+ Array Multiplier", width=-1, callback=lambda *args: self._add_node_array_multiply())
            dpg.add_spacer(height=2)
            dpg.add_button(label="+ Normalize", width=-1, callback=lambda *args: self._add_node_normalize())
            dpg.add_spacer(height=2)
            dpg.add_button(label="+ Math Mix", width=-1, callback=lambda *args: self._add_node_math())
            dpg.add_spacer(height=2)
            dpg.add_button(label="+ Transform & Curve", width=-1, callback=lambda *args: self._add_node_transform())
            dpg.add_spacer(height=2)
            dpg.add_button(label="+ Waveform Shape", width=-1, callback=lambda *args: self._add_node_shape())
            dpg.add_spacer(height=2)
            dpg.add_button(label="+ Boolean Logic", width=-1, callback=lambda *args: self._add_node_boolean())

    def _build_canvas_and_default_nodes(self):
        """Center: DearPyGui Node Editor Canvas and default nodes."""
        with dpg.child_window(width=-330, height=-1, border=True):
            with dpg.node_editor(
                tag="node_editor_canvas",
                callback=self._cb_node_link,
                delink_callback=self._cb_node_delink,
                width=-1,
                height=-1,
            ):
                # 1. INPUT NODES: 4 Separate Telemetry Sensors
                with dpg.node(label="Input: Over-Braking", tag="node_sensor_abs", pos=[30.0, 40.0]):
                    with dpg.node_attribute(label="Over-Braking Max", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_abs"):
                        dpg.add_text("Over-Braking (Max)", color=[255, 220, 0, 255])
                    with dpg.node_attribute(label="Over-Braking Left", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_abs_l"):
                        dpg.add_text("Over-Braking (Left)", color=[255, 220, 0, 255])
                    with dpg.node_attribute(label="Over-Braking Right", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_abs_r"):
                        dpg.add_text("Over-Braking (Right)", color=[255, 220, 0, 255])

                with dpg.node(label="Input: Over-Acceleration", tag="node_sensor_tc", pos=[30.0, 160.0]):
                    with dpg.node_attribute(label="Over-Accel Max", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_tc"):
                        dpg.add_text("Over-Accel (Max)", color=[255, 220, 0, 255])
                    with dpg.node_attribute(label="Over-Accel Left", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_tc_l"):
                        dpg.add_text("Over-Accel (Left)", color=[255, 220, 0, 255])
                    with dpg.node_attribute(label="Over-Accel Right", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_tc_r"):
                        dpg.add_text("Over-Accel (Right)", color=[255, 220, 0, 255])

                with dpg.node(label="Input: Oversteer", tag="node_sensor_over", pos=[30.0, 280.0]):
                    with dpg.node_attribute(label="Oversteer Max", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_over"):
                        dpg.add_text("Oversteer (Max)", color=[255, 220, 0, 255])
                    with dpg.node_attribute(label="Oversteer Left", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_over_l"):
                        dpg.add_text("Oversteer (Left)", color=[255, 220, 0, 255])
                    with dpg.node_attribute(label="Oversteer Right", attribute_type=dpg.mvNode_Attr_Output, tag="attr_out_over_r"):
                        dpg.add_text("Oversteer (Right)", color=[255, 220, 0, 255])

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

                self._setup_default_pin_themes()

    def _setup_default_pin_themes(self):
        """Applies pin color themes to initial default nodes."""
        for sensor_pin in self.SENSOR_PIN_TAGS:
            self._apply_pin_theme(sensor_pin, "normalized")
        self._apply_pin_theme("attr_in_low", "sum_array")
        self._apply_pin_theme("attr_in_high", "sum_array")

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

    def _add_node_sensor_gear(self, pos=(30.0, 760.0)):
        return self._factory.add_node_sensor_gear(self._custom_nodes, self.recompile_and_update_synth, pos)

    def _add_node_sensor_travel(self, pos=(30.0, 640.0)):
        return self._factory.add_node_sensor_travel(self._custom_nodes, self.recompile_and_update_synth, pos)

    def _add_node_sensor_grip(self, pos=(30.0, 700.0)):
        return self._factory.add_node_sensor_grip(self._custom_nodes, self.recompile_and_update_synth, pos)

    def _add_node_boolean(self, op="AND", val_a=0.0, val_b=0.0, pos=(240.0, 80.0)):
        if not isinstance(op, str):
            op = "AND"
        if isinstance(val_a, (tuple, list)):
            pos = val_a
            val_a = 0.0
        return self._factory.add_node_boolean(self._custom_nodes, self.recompile_and_update_synth, op=op, val_a=val_a, val_b=val_b, pos=pos)

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

    def _add_node_invert(self, val_in: float = 0.0, pos=(240.0, 120.0)):
        if not isinstance(val_in, (int, float)):
            val_in = 0.0
        return self._factory.add_node_invert(self._custom_nodes, self.recompile_and_update_synth, val_in=val_in, pos=pos)

    def _add_node_multiply(self, val_a=1.0, val_b=1.0, pos=(240.0, 40.0)):
        if isinstance(val_a, (tuple, list)):
            pos = val_a
            val_a = 1.0
        return self._factory.add_node_multiply(self._custom_nodes, self.recompile_and_update_synth, val_a=val_a, val_b=val_b, pos=pos)

    def _add_node_array_multiply(self, pos=(240.0, 60.0)):
        return self._factory.add_node_array_multiply(self._custom_nodes, self.recompile_and_update_synth, pos)

    def _add_node_normalize(self, min_val=0.0, max_val=100.0, clamp=True, val_in=0.0, pos=(240.0, 100.0)):
        if isinstance(min_val, (tuple, list)):
            pos = min_val
            min_val = 0.0
        elif not isinstance(min_val, (int, float)):
            min_val = 0.0
        return self._factory.add_node_normalize(self._custom_nodes, self.recompile_and_update_synth, min_val=min_val, max_val=max_val, clamp=clamp, val_in=val_in, pos=pos)

    def _add_node_math(self, op="Multiply (*)", val_a=0.0, val_b=0.0, pos=(240.0, 40.0)):
        if not isinstance(op, str):
            op = "Multiply (*)"
        if isinstance(val_a, (tuple, list)):
            pos = val_a
            val_a = 0.0
        return self._factory.add_node_math(self._custom_nodes, self.recompile_and_update_synth, op=op, val_a=val_a, val_b=val_b, pos=pos)

    def _add_node_transform(self, thresh=0.15, gain=1.0, gamma=1.0, val_in=0.0, pos=(240.0, 160.0)):
        if isinstance(thresh, (tuple, list)):
            pos = thresh
            thresh = 0.15
        elif not isinstance(thresh, (int, float)):
            thresh = 0.15
        return self._factory.add_node_transform(self._custom_nodes, self.recompile_and_update_synth, thresh=thresh, gain=gain, gamma=gamma, val_in=val_in, pos=pos)

    def _add_node_shape(self, shape="Square (Pulsed)", freq=20.0, duty=0.40, val_in=0.0, pos=(240.0, 420.0)):
        if not isinstance(shape, str):
            shape = "Square (Pulsed)"
        if isinstance(freq, (tuple, list)):
            pos = freq
            freq = 20.0
        return self._factory.add_node_shape(self._custom_nodes, self.recompile_and_update_synth, shape=shape, freq=freq, duty=duty, val_in=val_in, pos=pos)

    def _delete_custom_node(self, node_tag: str):
        self._factory.delete_custom_node(self._custom_nodes, self._node_links, node_tag, self.recompile_and_update_synth)

    def _delete_selected_items(self):
        """Keyboard Del / Suppr Key Handler: Deletes selected nodes and links."""
        GraphSelectionManager.delete_selected_items(
            self._custom_nodes, self._node_links, self._factory, self.recompile_and_update_synth
        )

    def _collect_connected_attributes(self) -> set:
        """SLAP Helper: Collects all connected input attribute pin tags and alias IDs."""
        connected_attrs = set()
        for link_id, (attr_out, attr_in) in self._node_links.items():
            connected_attrs.add(attr_in)
            if dpg.does_item_exist(attr_in):
                connected_attrs.add(dpg.get_alias_id(attr_in))
        return connected_attrs

    def _collect_node_input_controls(self, ninfo: dict) -> list:
        """SLAP Helper: Aggregates embedded input widgets and labels for a node."""
        input_controls = list(ninfo.get("input_controls", []))
        if ninfo.get("type") == "shape":
            for attr_key, widget_key, lbl_key in [("in_on", "on_ms_tag", "on_lbl_tag"), ("in_off", "off_ms_tag", "off_lbl_tag")]:
                if ninfo.get(attr_key) and ninfo.get(widget_key):
                    input_controls.append({
                        "attr": ninfo.get(attr_key),
                        "widget": ninfo.get(widget_key),
                        "label": ninfo.get(lbl_key)
                    })
        return input_controls

    def _update_embedded_controls_visibility(self):
        """Hides embedded input widgets and displays pin text labels when connected via link (CCN < 5)."""
        connected_attrs = self._collect_connected_attributes()

        for ntag, ninfo in self._custom_nodes.items():
            input_controls = self._collect_node_input_controls(ninfo)
            for ctrl in input_controls:
                attr_tag = ctrl.get("attr")
                widget_tag = ctrl.get("widget")
                lbl_tag = ctrl.get("label")

                if attr_tag and widget_tag and dpg.does_item_exist(widget_tag):
                    attr_id = dpg.get_alias_id(attr_tag) if dpg.does_item_exist(attr_tag) else None
                    is_connected = (attr_tag in connected_attrs) or (attr_id and attr_id in connected_attrs)
                    dpg.configure_item(widget_tag, show=not is_connected)
                    if lbl_tag and dpg.does_item_exist(lbl_tag):
                        dpg.configure_item(lbl_tag, show=is_connected)

    def _is_array_port(self, attr_in: str) -> bool:
        """Predicate helper to test if an input attribute pin allows multi-link connections."""
        if attr_in in ["attr_in_low", "attr_in_high"]:
            return True
        for ninfo in self._custom_nodes.values():
            if ninfo.get("type") == "array_multiply":
                in_attr = ninfo.get("in_attr")
                if in_attr == attr_in:
                    return True
                if dpg.does_item_exist(attr_in) and dpg.does_item_exist(in_attr) and dpg.get_alias_id(in_attr) == dpg.get_alias_id(attr_in):
                    return True
        return False

    def _cb_node_link(self, sender, app_data):
        attr_out, attr_in = app_data

        if not self._is_array_port(attr_in):
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
        return GraphSerializer.export_graph_to_dict(self._custom_nodes, self._node_links)

    def import_graph_from_dict(self, graph_data: dict):
        """Clears current graph canvas and rebuilds visual nodes and links from dictionary."""
        GraphSerializer.import_graph_from_dict(self, graph_data)

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
    def _refresh_profile_dropdown(self, target_profile_name: Optional[str] = None):
        """Refreshes the profile selection dropdown menu items and sets default value."""
        if not dpg.does_item_exist("combo_profile_select"):
            return
        displays = self._profile_manager.list_display_names()
        if target_profile_name:
            new_disp = self._profile_manager.get_display_name(target_profile_name)
        else:
            new_disp = self._profile_manager.get_display_name(self._profile_manager._active_profile_name)
        dpg.configure_item("combo_profile_select", items=displays, default_value=new_disp)

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
            self._refresh_profile_dropdown(prof.name)
            self._update_preset_ui_state()

    def _cb_clone_preset(self):
        selected_display = dpg.get_value("combo_profile_select") if dpg.does_item_exist("combo_profile_select") else ""
        cloned_prof, msg = self._profile_manager.clone_profile(selected_display)
        if cloned_prof:
            self._refresh_profile_dropdown(cloned_prof.name)
            self.import_graph_from_dict(cloned_prof.graph_data)
            self._update_preset_ui_state()

    def _cb_delete_preset(self):
        selected_display = dpg.get_value("combo_profile_select") if dpg.does_item_exist("combo_profile_select") else ""
        success, msg = self._profile_manager.delete_profile(selected_display)
        if success:
            self._refresh_profile_dropdown()
            self._cb_load_preset()

    def _open_new_profile_modal(self):
        def on_created(prof_name, blank_graph):
            self._refresh_profile_dropdown(prof_name)
            self.import_graph_from_dict(blank_graph)
            self._update_preset_ui_state()

        self._modal_manager.open_new_profile_modal(self._profile_manager, on_created)

    def _open_rename_profile_modal(self):
        selected_display = dpg.get_value("combo_profile_select") if dpg.does_item_exist("combo_profile_select") else ""

        def on_renamed(new_name):
            self._refresh_profile_dropdown(new_name)
            self._update_preset_ui_state()

        self._modal_manager.open_rename_profile_modal(self._profile_manager, selected_display, on_renamed)

    def _open_rename_node_modal(self):
        self._modal_manager.open_rename_node_modal(self._custom_nodes, self.recompile_and_update_synth)

    def _show_python_code_modal(self):
        graph_dict = self.export_graph_to_dict()
        self._modal_manager.show_python_code_modal(graph_dict)

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
