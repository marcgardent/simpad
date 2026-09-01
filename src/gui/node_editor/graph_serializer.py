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
    def _extract_constant_props(ninfo: dict, ntype: str) -> dict:
        v_tag = ninfo.get("val_tag")
        return {"val": dpg.get_value(v_tag) if dpg.does_item_exist(v_tag) else (0.5 if ntype == "constant" else 20.0)}

    @staticmethod
    def _extract_normalize_props(ninfo: dict) -> dict:
        min_t, max_t, cl_t, in_t = ninfo.get("min_tag"), ninfo.get("max_tag"), ninfo.get("clamp_tag"), ninfo.get("val_in_tag")
        return {
            "in_attr": ninfo.get("in_attr"),
            "min": dpg.get_value(min_t) if dpg.does_item_exist(min_t) else 0.0,
            "max": dpg.get_value(max_t) if dpg.does_item_exist(max_t) else 100.0,
            "clamp": dpg.get_value(cl_t) if dpg.does_item_exist(cl_t) else True,
            "val_in": dpg.get_value(in_t) if in_t and dpg.does_item_exist(in_t) else 0.0,
        }

    @staticmethod
    def _extract_math_props(ninfo: dict, is_binary: bool = True) -> dict:
        op_t = ninfo.get("op_tag")
        va_t = ninfo.get("val_a_tag")
        vb_t = ninfo.get("val_b_tag")
        def_v = 1.0 if not is_binary else 0.0
        props = {"in_a": ninfo.get("in_a"), "in_b": ninfo.get("in_b")}
        if op_t:
            props["op"] = dpg.get_value(op_t) if dpg.does_item_exist(op_t) else "Multiply (*)"
        props["val_a"] = dpg.get_value(va_t) if va_t and dpg.does_item_exist(va_t) else def_v
        props["val_b"] = dpg.get_value(vb_t) if vb_t and dpg.does_item_exist(vb_t) else def_v
        return props

    @staticmethod
    def _extract_transform_props(ninfo: dict) -> dict:
        g_t, gm_t, tr_t, in_t = ninfo.get("gain_tag"), ninfo.get("gamma_tag"), ninfo.get("thresh_tag"), ninfo.get("val_in_tag")
        return {
            "in_attr": ninfo.get("in_attr"),
            "gain": dpg.get_value(g_t) if dpg.does_item_exist(g_t) else 1.0,
            "gamma": dpg.get_value(gm_t) if dpg.does_item_exist(gm_t) else 1.0,
            "thresh": dpg.get_value(tr_t) if dpg.does_item_exist(tr_t) else 0.0,
            "val_in": dpg.get_value(in_t) if in_t and dpg.does_item_exist(in_t) else 0.0,
        }

    @staticmethod
    def _extract_shape_props(ninfo: dict) -> dict:
        sh_t, fr_t, du_t, in_t = ninfo.get("shape_tag"), ninfo.get("freq_tag"), ninfo.get("duty_tag"), ninfo.get("val_in_tag")
        return {
            "in_attr": ninfo.get("in_attr"),
            "in_freq": ninfo.get("in_freq"),
            "shape": dpg.get_value(sh_t) if dpg.does_item_exist(sh_t) else "Square (Pulsed)",
            "freq": dpg.get_value(fr_t) if dpg.does_item_exist(fr_t) else 20.0,
            "duty": dpg.get_value(du_t) if dpg.does_item_exist(du_t) else 0.40,
            "val_in": dpg.get_value(in_t) if in_t and dpg.does_item_exist(in_t) else 0.0,
        }

    @staticmethod
    def _serialize_node_properties(ninfo: dict) -> dict:
        """SLAP Helper: Extracts serialized node-specific property values from DPG item tags (CCN < 6)."""
        ntype = ninfo["type"]
        if ntype in ["constant", "float_constant"]:
            return GraphSerializer._extract_constant_props(ninfo, ntype)
        elif ntype == "normalize":
            return GraphSerializer._extract_normalize_props(ninfo)
        elif ntype == "math":
            return GraphSerializer._extract_math_props(ninfo, is_binary=True)
        elif ntype in ["multiply", "logic_bool"]:
            return GraphSerializer._extract_math_props(ninfo, is_binary=False)
        elif ntype == "transform":
            return GraphSerializer._extract_transform_props(ninfo)
        elif ntype == "shape":
            return GraphSerializer._extract_shape_props(ninfo)
        elif ntype in ["array_multiply", "invert"]:
            in_t = ninfo.get("val_in_tag")
            res = {"in_attr": ninfo.get("in_attr")}
            if in_t:
                res["val_in"] = dpg.get_value(in_t) if dpg.does_item_exist(in_t) else 0.0
            return res
        return {}

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

            ndata.update(GraphSerializer._serialize_node_properties(ninfo))

            if dpg.does_item_exist(ntag):
                lbl = dpg.get_item_label(ntag)
                if lbl:
                    ndata["label"] = lbl

            nodes_dict[ntag] = ndata

        links_list = [[o, i] for link_id, (o, i) in node_links.items()]
        return {"nodes": nodes_dict, "links": links_list}

    @staticmethod
    def _instantiate_node(editor_tab, ntype: str, ndata: dict, pos: Tuple[int, int]) -> Optional[str]:
        """SLAP Helper: Dispatches node instantiation on the editor canvas using a creation dispatch map (CCN < 4)."""
        creators = {
            "constant": lambda: editor_tab._add_node_constant(val=ndata.get("val", 0.5), pos=pos),
            "float_constant": lambda: editor_tab._add_node_float_constant(val=ndata.get("val", 20.0), pos=pos),
            "invert": lambda: editor_tab._add_node_invert(val_in=ndata.get("val_in", 0.0), pos=pos),
            "multiply": lambda: editor_tab._add_node_multiply(val_a=ndata.get("val_a", 1.0), val_b=ndata.get("val_b", 1.0), pos=pos),
            "array_multiply": lambda: editor_tab._add_node_array_multiply(pos=pos),
            "normalize": lambda: editor_tab._add_node_normalize(min_val=ndata.get("min", 0.0), max_val=ndata.get("max", 100.0), clamp=ndata.get("clamp", True), val_in=ndata.get("val_in", 0.0), pos=pos),
            "math": lambda: editor_tab._add_node_math(op=ndata.get("op", "Multiply (*)"), val_a=ndata.get("val_a", 0.0), val_b=ndata.get("val_b", 0.0), pos=pos),
            "transform": lambda: editor_tab._add_node_transform(thresh=ndata.get("thresh", 0.15), gain=ndata.get("gain", 1.0), gamma=ndata.get("gamma", 1.0), val_in=ndata.get("val_in", 0.0), pos=pos),
            "shape": lambda: editor_tab._add_node_shape(shape=ndata.get("shape", "Square (Pulsed)"), freq=ndata.get("freq", 20.0), duty=ndata.get("duty", 0.40), val_in=ndata.get("val_in", 0.0), pos=pos),
            "sensor_over_braking": lambda: editor_tab._add_node_sensor_abs(pos=pos),
            "sensor_over_accel": lambda: editor_tab._add_node_sensor_tc(pos=pos),
            "sensor_oversteer": lambda: editor_tab._add_node_sensor_over(pos=pos),
            "sensor_understeer": lambda: editor_tab._add_node_sensor_und(pos=pos),
            "sensor_engine_regime": lambda: editor_tab._add_node_sensor_engine(pos=pos),
            "sensor_gear": lambda: editor_tab._add_node_sensor_gear(pos=pos),
            "logic_bool": lambda: editor_tab._add_node_boolean(op=ndata.get("op", "AND"), val_a=ndata.get("val_a", 0.0), val_b=ndata.get("val_b", 0.0), pos=pos),
            "sensor_wheel_travel": lambda: editor_tab._add_node_sensor_travel(pos=pos),
            "sensor_grip_fract": lambda: editor_tab._add_node_sensor_grip(pos=pos),
            "sensor_ecu_abs": lambda: editor_tab._add_node_sensor_ecu_abs(pos=pos),
            "sensor_ecu_tc": lambda: editor_tab._add_node_sensor_ecu_tc(pos=pos),
            "output_xinput": lambda: editor_tab._add_node_output_xinput(pos=pos),
        }
        creator = creators.get(ntype)
        return creator() if creator else None

    @staticmethod
    def _clear_canvas(editor_tab) -> None:
        """SLAP Helper: Clears dynamic node items and link items from PyGui canvas."""
        for link_id in list(editor_tab._node_links.keys()):
            if dpg.does_item_exist(link_id):
                dpg.delete_item(link_id)
        editor_tab._node_links.clear()

        for ntag in list(editor_tab._custom_nodes.keys()):
            if dpg.does_item_exist(ntag):
                dpg.delete_item(ntag)
        editor_tab._custom_nodes.clear()

    @staticmethod
    def _rebuild_nodes(editor_tab, nodes: dict) -> Dict[str, str]:
        """SLAP Helper: Re-instantiates nodes from JSON dict and constructs tag remapping dictionary."""
        tag_remap: Dict[str, str] = {}
        for old_ntag, ndata in nodes.items():
            ntype = ndata.get("type")
            pos = tuple(ndata.get("pos", [240, 100]))
            new_ntag = GraphSerializer._instantiate_node(editor_tab, ntype, ndata, pos)

            if new_ntag and new_ntag in editor_tab._custom_nodes:
                created_ninfo = editor_tab._custom_nodes[new_ntag]
                for key, val in ndata.items():
                    if (key.startswith("out_") or key.startswith("in_")) and key in created_ninfo:
                        tag_remap[val] = created_ninfo[key]

                if "label" in ndata and dpg.does_item_exist(new_ntag):
                    dpg.configure_item(new_ntag, label=ndata["label"])
                    created_ninfo["label"] = ndata["label"]

        for base_tag in GraphSerializer.BASE_TAG_MAP:
            tag_remap[base_tag] = base_tag

        return tag_remap

    @staticmethod
    def _rebuild_links(editor_tab, links: list, tag_remap: Dict[str, str]) -> None:
        """SLAP Helper: Re-wires link connections between attribute pins."""
        for src_out, tgt_in in links:
            mapped_src = tag_remap.get(src_out, src_out)
            mapped_tgt = tag_remap.get(tgt_in, tgt_in)
            if dpg.does_item_exist(mapped_src) and dpg.does_item_exist(mapped_tgt):
                editor_tab._cb_node_link("node_editor_canvas", (mapped_src, mapped_tgt))

    @staticmethod
    def import_graph_from_dict(editor_tab, graph_data: dict):
        """Clears current graph canvas and rebuilds visual nodes and links from dictionary (CCN < 4)."""
        if not dpg.does_item_exist("node_editor_canvas"):
            return

        GraphSerializer._clear_canvas(editor_tab)
        tag_remap = GraphSerializer._rebuild_nodes(editor_tab, graph_data.get("nodes", {}))
        GraphSerializer._rebuild_links(editor_tab, graph_data.get("links", []), tag_remap)
        editor_tab.auto_arrange_nodes()
