"""
SimPad Haptic Middleware — Graph Serializer & Deserializer.
Handles graph state serialization to dictionary format and restoration/deserialization onto the canvas.
"""

import dearpygui.dearpygui as dpg
from typing import Dict, Tuple, List, Any


class GraphSerializer:
    """Handles serialization and deserialization of the node graph structure."""

    BASE_TAG_MAP = [
        "attr_out_abs", "attr_out_abs_l", "attr_out_abs_r",
        "attr_out_tc", "attr_out_tc_l", "attr_out_tc_r",
        "attr_out_over", "attr_out_over_l", "attr_out_over_r",
        "attr_out_und", "attr_out_und_l", "attr_out_und_r",
        "attr_out_over_rev", "attr_out_under_rev", "attr_out_rpm", "attr_out_gear",
        "attr_out_travel", "attr_out_travel_l", "attr_out_travel_r",
        "attr_out_travel_fl", "attr_out_travel_fr", "attr_out_travel_rl", "attr_out_travel_rr",
        "attr_out_grip", "attr_out_grip_l", "attr_out_grip_r",
        "attr_out_const", "attr_in_low", "attr_in_high"
    ]

    @staticmethod
    def export_graph_to_dict(custom_nodes: Dict[str, dict], node_links: Dict[int, Tuple[str, str]]) -> dict:
        """Serializes current node graph (nodes, properties, positions, links) to a dictionary."""
        nodes_dict = {}
        for ntag, ninfo in custom_nodes.items():
            pos = dpg.get_item_pos(ntag) if dpg.does_item_exist(ntag) else [240, 100]
            ndata = {"type": ninfo["type"], "pos": list(pos)}
            for k, v in ninfo.items():
                if (k.startswith("out_") or k.startswith("in_")) and isinstance(v, str):
                    ndata[k] = v

            ntype = ninfo["type"]
            if ntype in ["constant", "float_constant"]:
                ndata["val"] = dpg.get_value(ninfo["val_tag"]) if dpg.does_item_exist(ninfo["val_tag"]) else (0.5 if ntype == "constant" else 20.0)
            elif ntype == "normalize":
                ndata["in_attr"] = ninfo.get("in_attr")
                ndata["min"] = dpg.get_value(ninfo["min_tag"]) if dpg.does_item_exist(ninfo["min_tag"]) else 0.0
                ndata["max"] = dpg.get_value(ninfo["max_tag"]) if dpg.does_item_exist(ninfo["max_tag"]) else 100.0
                ndata["clamp"] = dpg.get_value(ninfo["clamp_tag"]) if dpg.does_item_exist(ninfo["clamp_tag"]) else True
                ndata["val_in"] = dpg.get_value(ninfo["val_in_tag"]) if "val_in_tag" in ninfo and dpg.does_item_exist(ninfo["val_in_tag"]) else 0.0
            elif ntype == "math":
                ndata["in_a"] = ninfo.get("in_a")
                ndata["in_b"] = ninfo.get("in_b")
                ndata["op"] = dpg.get_value(ninfo["op_tag"]) if "op_tag" in ninfo and dpg.does_item_exist(ninfo["op_tag"]) else "Multiply (*)"
                ndata["val_a"] = dpg.get_value(ninfo["val_a_tag"]) if "val_a_tag" in ninfo and dpg.does_item_exist(ninfo["val_a_tag"]) else 0.0
                ndata["val_b"] = dpg.get_value(ninfo["val_b_tag"]) if "val_b_tag" in ninfo and dpg.does_item_exist(ninfo["val_b_tag"]) else 0.0
            elif ntype == "multiply":
                ndata["in_a"] = ninfo.get("in_a")
                ndata["in_b"] = ninfo.get("in_b")
                ndata["val_a"] = dpg.get_value(ninfo["val_a_tag"]) if "val_a_tag" in ninfo and dpg.does_item_exist(ninfo["val_a_tag"]) else 1.0
                ndata["val_b"] = dpg.get_value(ninfo["val_b_tag"]) if "val_b_tag" in ninfo and dpg.does_item_exist(ninfo["val_b_tag"]) else 1.0
            elif ntype == "logic_bool":
                ndata["in_a"] = ninfo.get("in_a")
                ndata["in_b"] = ninfo.get("in_b")
                ndata["op"] = dpg.get_value(ninfo["op_tag"]) if "op_tag" in ninfo and dpg.does_item_exist(ninfo["op_tag"]) else "AND"
                ndata["val_a"] = dpg.get_value(ninfo["val_a_tag"]) if "val_a_tag" in ninfo and dpg.does_item_exist(ninfo["val_a_tag"]) else 0.0
                ndata["val_b"] = dpg.get_value(ninfo["val_b_tag"]) if "val_b_tag" in ninfo and dpg.does_item_exist(ninfo["val_b_tag"]) else 0.0
            elif ntype == "array_multiply":
                ndata["in_attr"] = ninfo.get("in_attr")
            elif ntype == "transform":
                ndata["in_attr"] = ninfo.get("in_attr")
                ndata["gain"] = dpg.get_value(ninfo["gain_tag"]) if dpg.does_item_exist(ninfo["gain_tag"]) else 1.0
                ndata["gamma"] = dpg.get_value(ninfo["gamma_tag"]) if dpg.does_item_exist(ninfo["gamma_tag"]) else 1.0
                ndata["thresh"] = dpg.get_value(ninfo["thresh_tag"]) if dpg.does_item_exist(ninfo["thresh_tag"]) else 0.0
                ndata["val_in"] = dpg.get_value(ninfo["val_in_tag"]) if "val_in_tag" in ninfo and dpg.does_item_exist(ninfo["val_in_tag"]) else 0.0
            elif ntype == "invert":
                ndata["in_attr"] = ninfo.get("in_attr")
                ndata["val_in"] = dpg.get_value(ninfo["val_in_tag"]) if "val_in_tag" in ninfo and dpg.does_item_exist(ninfo["val_in_tag"]) else 0.0
            elif ntype == "shape":
                ndata["in_attr"] = ninfo.get("in_attr")
                ndata["in_freq"] = ninfo.get("in_freq")
                ndata["shape"] = dpg.get_value(ninfo["shape_tag"]) if dpg.does_item_exist(ninfo["shape_tag"]) else "Square (Pulsed)"
                ndata["freq"] = dpg.get_value(ninfo["freq_tag"]) if dpg.does_item_exist(ninfo["freq_tag"]) else 20.0
                ndata["duty"] = dpg.get_value(ninfo["duty_tag"]) if dpg.does_item_exist(ninfo["duty_tag"]) else 0.40
                ndata["val_in"] = dpg.get_value(ninfo["val_in_tag"]) if "val_in_tag" in ninfo and dpg.does_item_exist(ninfo["val_in_tag"]) else 0.0

            if dpg.does_item_exist(ntag):
                lbl = dpg.get_item_label(ntag)
                if lbl:
                    ndata["label"] = lbl

            nodes_dict[ntag] = ndata

        links_list = [[o, i] for link_id, (o, i) in node_links.items()]
        return {"nodes": nodes_dict, "links": links_list}

    @staticmethod
    def import_graph_from_dict(editor_tab, graph_data: dict):
        """Clears current graph canvas and rebuilds visual nodes and links from dictionary."""
        if not dpg.does_item_exist("node_editor_canvas"):
            return

        # 1. Clear current dynamic nodes and links
        for link_id in list(editor_tab._node_links.keys()):
            if dpg.does_item_exist(link_id):
                dpg.delete_item(link_id)
        editor_tab._node_links.clear()

        for ntag in list(editor_tab._custom_nodes.keys()):
            if dpg.does_item_exist(ntag):
                dpg.delete_item(ntag)
        editor_tab._custom_nodes.clear()

        # Tag mapping table to re-wire loaded links to newly created attribute tags
        tag_remap: Dict[str, str] = {}

        # Helper mapping table for node instantiation logic
        nodes = graph_data.get("nodes", {})
        for old_ntag, ndata in nodes.items():
            ntype = ndata.get("type")
            pos = tuple(ndata.get("pos", [240, 100]))
            new_ntag = None

            if ntype == "constant":
                new_ntag = editor_tab._add_node_constant(val=ndata.get("val", 0.5), pos=pos)
            elif ntype == "float_constant":
                new_ntag = editor_tab._add_node_float_constant(val=ndata.get("val", 20.0), pos=pos)
            elif ntype == "invert":
                new_ntag = editor_tab._add_node_invert(val_in=ndata.get("val_in", 0.0), pos=pos)
            elif ntype == "multiply":
                new_ntag = editor_tab._add_node_multiply(val_a=ndata.get("val_a", 1.0), val_b=ndata.get("val_b", 1.0), pos=pos)
            elif ntype == "array_multiply":
                new_ntag = editor_tab._add_node_array_multiply(pos=pos)
            elif ntype == "normalize":
                new_ntag = editor_tab._add_node_normalize(min_val=ndata.get("min", 0.0), max_val=ndata.get("max", 100.0), clamp=ndata.get("clamp", True), val_in=ndata.get("val_in", 0.0), pos=pos)
            elif ntype == "math":
                new_ntag = editor_tab._add_node_math(op=ndata.get("op", "Multiply (*)"), val_a=ndata.get("val_a", 0.0), val_b=ndata.get("val_b", 0.0), pos=pos)
            elif ntype == "transform":
                new_ntag = editor_tab._add_node_transform(thresh=ndata.get("thresh", 0.15), gain=ndata.get("gain", 1.0), gamma=ndata.get("gamma", 1.0), val_in=ndata.get("val_in", 0.0), pos=pos)
            elif ntype == "shape":
                new_ntag = editor_tab._add_node_shape(
                    shape=ndata.get("shape", "Square (Pulsed)"),
                    freq=ndata.get("freq", 20.0),
                    duty=ndata.get("duty", 0.40),
                    val_in=ndata.get("val_in", 0.0),
                    pos=pos
                )
            elif ntype == "sensor_over_braking":
                new_ntag = editor_tab._add_node_sensor_abs(pos=pos)
            elif ntype == "sensor_over_accel":
                new_ntag = editor_tab._add_node_sensor_tc(pos=pos)
            elif ntype == "sensor_oversteer":
                new_ntag = editor_tab._add_node_sensor_over(pos=pos)
            elif ntype == "sensor_understeer":
                new_ntag = editor_tab._add_node_sensor_und(pos=pos)
            elif ntype == "sensor_engine_regime":
                new_ntag = editor_tab._add_node_sensor_engine(pos=pos)
            elif ntype == "sensor_gear":
                new_ntag = editor_tab._add_node_sensor_gear(pos=pos)
            elif ntype == "logic_bool":
                op = ndata.get("op", "AND")
                val_a = ndata.get("val_a", 0.0)
                val_b = ndata.get("val_b", 0.0)
                new_ntag = editor_tab._add_node_boolean(op=op, val_a=val_a, val_b=val_b, pos=pos)
            elif ntype == "sensor_wheel_travel":
                new_ntag = editor_tab._add_node_sensor_travel(pos=pos)
            elif ntype == "sensor_grip_fract":
                new_ntag = editor_tab._add_node_sensor_grip(pos=pos)
            elif ntype == "output_xinput":
                new_ntag = editor_tab._add_node_output_xinput(pos=pos)

            if new_ntag and new_ntag in editor_tab._custom_nodes:
                created_ninfo = editor_tab._custom_nodes[new_ntag]
                # Auto-remap matching input/output pin attributes
                for key, val in ndata.items():
                    if (key.startswith("out_") or key.startswith("in_")) and key in created_ninfo:
                        tag_remap[val] = created_ninfo[key]

                if "label" in ndata and dpg.does_item_exist(new_ntag):
                    dpg.configure_item(new_ntag, label=ndata["label"])
                    created_ninfo["label"] = ndata["label"]

        # Base static sensors & motors map to themselves
        for base_tag in GraphSerializer.BASE_TAG_MAP:
            tag_remap[base_tag] = base_tag

        # 3. Re-wire links
        links = graph_data.get("links", [])
        for src_out, tgt_in in links:
            mapped_src = tag_remap.get(src_out, src_out)
            mapped_tgt = tag_remap.get(tgt_in, tgt_in)

            if dpg.does_item_exist(mapped_src) and dpg.does_item_exist(mapped_tgt):
                editor_tab._cb_node_link("node_editor_canvas", (mapped_src, mapped_tgt))

        # 4. Auto-arrange node layout neatly into topological columns
        editor_tab.auto_arrange_nodes()
