"""
SimPad Haptic Middleware — Node Graph Layout & Auto-Arranger.
Calculates topological depth layers, dynamic column X bounds, zero-overlap Y stacking, and parent link alignment.
"""

import dearpygui.dearpygui as dpg
from typing import Dict, Tuple, List, Set, Callable, Any


class NodeGraphArranger:
    """Handles auto-arranging node canvas positions based on graph topology and node dimensions."""

    BUILTIN_NODE_DIMENSIONS = {
        "node_sensor_abs": (260.0, 135.0),
        "node_sensor_tc": (260.0, 135.0),
        "node_sensor_over": (260.0, 135.0),
        "node_sensor_und": (260.0, 135.0),
        "node_sensor_engine": (260.0, 135.0),
        "node_sensor_travel": (260.0, 260.0),
        "node_sensors": (260.0, 480.0),
        "node_xinput": (230.0, 130.0),
    }

    TYPE_DIMENSIONS = {
        "sensor_over_braking": (260.0, 135.0),
        "sensor_over_accel": (260.0, 135.0),
        "sensor_oversteer": (260.0, 135.0),
        "sensor_understeer": (260.0, 135.0),
        "sensor_engine_regime": (260.0, 135.0),
        "sensor_wheel_travel": (260.0, 260.0),
        "constant": (200.0, 95.0),
        "float_constant": (200.0, 95.0),
        "multiply": (220.0, 135.0),
        "array_multiply": (220.0, 135.0),
        "normalize": (230.0, 195.0),
        "math": (230.0, 175.0),
        "transform": (240.0, 215.0),
        "shape": (240.0, 235.0),
    }

    @staticmethod
    def get_node_dimensions(ntag: str, custom_nodes: Dict[str, dict]) -> Tuple[float, float]:
        """
        Retrieves or estimates the (width, height) of a node (CCN < 5).
        First tries DearPyGui's runtime get_item_rect_size, then dictionary lookup, and finally dynamic fallback.
        """
        if dpg.is_dearpygui_running() and dpg.does_item_exist(ntag):
            try:
                rect = dpg.get_item_rect_size(ntag)
                if rect and rect[0] > 20 and rect[1] > 20:
                    return float(rect[0]), float(rect[1])
            except Exception:
                pass

        if ntag in NodeGraphArranger.BUILTIN_NODE_DIMENSIONS:
            return NodeGraphArranger.BUILTIN_NODE_DIMENSIONS[ntag]

        if ntag in custom_nodes:
            ntype = custom_nodes[ntag].get("type", "")
            if ntype in NodeGraphArranger.TYPE_DIMENSIONS:
                return NodeGraphArranger.TYPE_DIMENSIONS[ntype]

        if dpg.is_dearpygui_running() and dpg.does_item_exist(ntag):
            try:
                children = dpg.get_item_children(ntag, slot=1) or []
                return 220.0, max(90.0, 40.0 + (len(children) * 32.0))
            except Exception:
                pass

        return 220.0, 150.0

    @classmethod
    def _build_attribute_map(cls, custom_nodes: Dict[str, dict]) -> Tuple[Dict[str, str], List[str], Set[str], Set[str]]:
        """SLAP Helper: Builds mapping of pin attribute tags to node tags and categorizes node types."""
        attr_to_node: Dict[str, str] = {}
        for s_pin in ["attr_out_abs", "attr_out_abs_l", "attr_out_abs_r"]:
            attr_to_node[s_pin] = "node_sensor_abs"
        for s_pin in ["attr_out_tc", "attr_out_tc_l", "attr_out_tc_r"]:
            attr_to_node[s_pin] = "node_sensor_tc"
        for s_pin in ["attr_out_over", "attr_out_over_l", "attr_out_over_r"]:
            attr_to_node[s_pin] = "node_sensor_over"
        for s_pin in ["attr_out_und", "attr_out_und_l", "attr_out_und_r"]:
            attr_to_node[s_pin] = "node_sensor_und"
        for m_pin in ["attr_in_low", "attr_in_high"]:
            attr_to_node[m_pin] = "node_xinput"

        all_node_tags = []
        sensor_node_tags = {"node_sensor_abs", "node_sensor_tc", "node_sensor_over", "node_sensor_und", "node_sensors"}
        output_node_tags = {"node_xinput"}

        for s_tag in ["node_sensor_abs", "node_sensor_tc", "node_sensor_over", "node_sensor_und", "node_sensors"]:
            if dpg.does_item_exist(s_tag):
                all_node_tags.append(s_tag)

        for ntag, ninfo in custom_nodes.items():
            if dpg.does_item_exist(ntag):
                all_node_tags.append(ntag)
                ntype = ninfo.get("type", "")
                if "sensor" in ntype:
                    sensor_node_tags.add(ntag)
                elif "output" in ntype or ntype == "output_xinput":
                    output_node_tags.add(ntag)
                for key in ["out_attr", "in_a", "in_b", "in_attr", "in_on", "in_off", "in_freq", "in_low", "in_high"]:
                    val = ninfo.get(key)
                    if val:
                        attr_to_node[val] = ntag

        if dpg.does_item_exist("node_xinput"):
            all_node_tags.append("node_xinput")

        return attr_to_node, all_node_tags, sensor_node_tags, output_node_tags

    @classmethod
    def _compute_topological_depths(cls, all_node_tags: List[str], sensor_node_tags: Set[str], output_node_tags: Set[str], incoming_nodes: Dict[str, Set[str]]) -> Dict[str, int]:
        """SLAP Helper: Iteratively calculates depth layers for graph nodes."""
        node_depths: Dict[str, int] = {ntag: 0 for ntag in all_node_tags}
        for stag in sensor_node_tags:
            if stag in node_depths:
                node_depths[stag] = 0

        changed = True
        iterations = 0
        while changed and iterations < 50:
            changed = False
            iterations += 1
            for ntag in all_node_tags:
                if ntag in sensor_node_tags:
                    continue
                parents = incoming_nodes[ntag]
                new_depth = (max(node_depths[p] for p in parents) + 1) if parents else 1

                if new_depth != node_depths[ntag]:
                    node_depths[ntag] = new_depth
                    changed = True

        max_inter_depth = max([d for n, d in node_depths.items() if n not in output_node_tags], default=1)
        for otag in output_node_tags:
            if otag in node_depths:
                node_depths[otag] = max_inter_depth + 1

        return node_depths

    @classmethod
    def _calculate_column_x_positions(cls, columns: Dict[int, List[str]], node_dims: Dict[str, Tuple[float, float]], col_x_start: float = 40.0, col_gap: float = 70.0) -> Tuple[Dict[int, float], List[int]]:
        """SLAP Helper: Computes dynamic X position of each topological depth column based on node widths."""
        col_x: Dict[int, float] = {}
        curr_x = col_x_start
        sorted_depths = sorted(columns.keys())

        for depth in sorted_depths:
            col_x[depth] = curr_x
            max_w_in_col = max((node_dims[ntag][0] for ntag in columns[depth]), default=220.0)
            curr_x += max_w_in_col + col_gap

        return col_x, sorted_depths

    @classmethod
    def _position_column_nodes(cls, sorted_depths: List[int], columns: Dict[int, List[str]], col_x: Dict[int, float], node_dims: Dict[str, Tuple[float, float]], incoming_nodes: Dict[str, Set[str]], row_y_start: float = 40.0, row_gap: float = 35.0) -> None:
        """SLAP Helper: Sets node Y canvas coordinates per column layer."""
        final_positions: Dict[str, Tuple[float, float]] = {}

        for depth in sorted_depths:
            n_list = columns[depth]
            x_pos = col_x[depth]

            if depth > 0:
                def get_parent_y(ntag: str) -> float:
                    parents = incoming_nodes.get(ntag, set())
                    known_parents_y = [final_positions[p][1] for p in parents if p in final_positions]
                    return (sum(known_parents_y) / len(known_parents_y)) if known_parents_y else 9999.0

                n_list = sorted(n_list, key=get_parent_y)

            if len(n_list) == 1 and depth == sorted_depths[-1]:
                target_node = n_list[0]
                _, target_h = node_dims[target_node]
                parents = incoming_nodes.get(target_node, set())
                known_parents_y = [final_positions[p][1] + node_dims[p][1] / 2.0 for p in parents if p in final_positions]
                y_pos = max(row_y_start, (sum(known_parents_y) / len(known_parents_y)) - (target_h / 2.0)) if known_parents_y else row_y_start
                final_positions[target_node] = (x_pos, y_pos)
                dpg.set_item_pos(target_node, [float(x_pos), float(y_pos)])
                continue

            curr_y = row_y_start
            for ntag in n_list:
                _, n_h = node_dims[ntag]
                final_positions[ntag] = (x_pos, curr_y)
                dpg.set_item_pos(ntag, [float(x_pos), float(curr_y)])
                curr_y += n_h + row_gap

    @classmethod
    def auto_arrange_nodes(cls, custom_nodes: Dict[str, dict], node_links: Dict[int, Tuple[str, str]], recompile_cb: Callable[[], None]):
        """Topologically calculates depth layer columns for all graph nodes and auto-arranges their positions (CCN < 5)."""
        if not dpg.does_item_exist("node_editor_canvas"):
            return

        attr_to_node, all_node_tags, sensor_node_tags, output_node_tags = cls._build_attribute_map(custom_nodes)

        incoming_nodes: Dict[str, Set[str]] = {ntag: set() for ntag in all_node_tags}
        for link_id, (src_out, tgt_in) in node_links.items():
            src_node = attr_to_node.get(src_out)
            tgt_node = attr_to_node.get(tgt_in)
            if src_node and tgt_node and src_node != tgt_node:
                incoming_nodes[tgt_node].add(src_node)

        node_depths = cls._compute_topological_depths(all_node_tags, sensor_node_tags, output_node_tags, incoming_nodes)

        columns: Dict[int, List[str]] = {}
        for ntag, depth in node_depths.items():
            columns.setdefault(depth, []).append(ntag)

        node_dims: Dict[str, Tuple[float, float]] = {
            ntag: cls.get_node_dimensions(ntag, custom_nodes) for ntag in all_node_tags
        }

        col_x, sorted_depths = cls._calculate_column_x_positions(columns, node_dims)
        cls._position_column_nodes(sorted_depths, columns, col_x, node_dims, incoming_nodes)

        recompile_cb()
