"""
SimPad Haptic Middleware — Node Graph Layout & Auto-Arranger.
Calculates topological depth layers, dynamic column X bounds, zero-overlap Y stacking, and parent link alignment.
"""

import dearpygui.dearpygui as dpg
from typing import Dict, Tuple, List, Set, Callable, Any


class NodeGraphArranger:
    """Handles auto-arranging node canvas positions based on graph topology and node dimensions."""

    @staticmethod
    def get_node_dimensions(ntag: str, custom_nodes: Dict[str, dict]) -> Tuple[float, float]:
        """
        Retrieves or estimates the (width, height) of a node.
        First tries DearPyGui's runtime get_item_rect_size if DPG is running.
        Otherwise, falls back to structural size calculation based on node type and attributes.
        """
        if dpg.is_dearpygui_running() and dpg.does_item_exist(ntag):
            try:
                rect = dpg.get_item_rect_size(ntag)
                if rect and rect[0] > 20 and rect[1] > 20:
                    return float(rect[0]), float(rect[1])
            except Exception:
                pass

        # Specific known built-in nodes
        if ntag == "node_sensors":
            return 260.0, 480.0
        elif ntag == "node_xinput":
            return 230.0, 130.0

        # Custom nodes lookup
        if ntag in custom_nodes:
            ntype = custom_nodes[ntag].get("type")
            if ntype in ["constant", "float_constant"]:
                return 200.0, 95.0
            elif ntype in ["multiply", "array_multiply"]:
                return 220.0, 135.0
            elif ntype == "normalize":
                return 230.0, 195.0
            elif ntype == "math":
                return 230.0, 175.0
            elif ntype == "transform":
                return 240.0, 215.0
            elif ntype == "shape":
                return 240.0, 235.0

        # Dynamic fallback for any other node: count children attributes
        if dpg.is_dearpygui_running() and dpg.does_item_exist(ntag):
            try:
                children = dpg.get_item_children(ntag, slot=1) or []
                attr_count = len(children)
                est_h = 40.0 + (attr_count * 32.0)
                return 220.0, max(90.0, est_h)
            except Exception:
                pass

        return 220.0, 150.0

    @classmethod
    def auto_arrange_nodes(cls, custom_nodes: Dict[str, dict], node_links: Dict[int, Tuple[str, str]], recompile_cb: Callable[[], None]):
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

        for ntag, ninfo in custom_nodes.items():
            if dpg.does_item_exist(ntag):
                all_node_tags.append(ntag)
                for key in ["out_attr", "in_a", "in_b", "in_attr", "in_on", "in_off", "in_freq"]:
                    val = ninfo.get(key)
                    if val:
                        attr_to_node[val] = ntag

        if dpg.does_item_exist("node_xinput"):
            all_node_tags.append("node_xinput")

        # 2. Build adjacency list of incoming node connections
        incoming_nodes: Dict[str, Set[str]] = {ntag: set() for ntag in all_node_tags}
        for link_id, (src_out, tgt_in) in node_links.items():
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

        # 5. Measure dimensions & calculate dynamic column X positions
        node_dims: Dict[str, Tuple[float, float]] = {
            ntag: cls.get_node_dimensions(ntag, custom_nodes) for ntag in all_node_tags
        }

        col_x_start = 40.0
        col_gap = 70.0
        row_y_start = 40.0
        row_gap = 35.0

        col_x: Dict[int, float] = {}
        curr_x = col_x_start
        sorted_depths = sorted(columns.keys())

        for depth in sorted_depths:
            col_x[depth] = curr_x
            max_w_in_col = max((node_dims[ntag][0] for ntag in columns[depth]), default=220.0)
            curr_x += max_w_in_col + col_gap

        # 6. Position nodes vertically within each column layer
        final_positions: Dict[str, Tuple[float, float]] = {}

        for depth in sorted_depths:
            n_list = columns[depth]
            x_pos = col_x[depth]

            if depth > 0:
                # Sort nodes by average Y position of their parent nodes to minimize link crossing
                def get_parent_y(ntag: str) -> float:
                    parents = incoming_nodes.get(ntag, set())
                    known_parents_y = [final_positions[p][1] for p in parents if p in final_positions]
                    if known_parents_y:
                        return sum(known_parents_y) / len(known_parents_y)
                    return 9999.0

                n_list = sorted(n_list, key=get_parent_y)

            # Special vertical centering for single output node column (e.g. node_xinput)
            if len(n_list) == 1 and depth == sorted_depths[-1]:
                target_node = n_list[0]
                _, target_h = node_dims[target_node]
                parents = incoming_nodes.get(target_node, set())
                known_parents_y = [final_positions[p][1] + node_dims[p][1] / 2.0 for p in parents if p in final_positions]
                if known_parents_y:
                    avg_center_y = sum(known_parents_y) / len(known_parents_y)
                    y_pos = max(row_y_start, avg_center_y - (target_h / 2.0))
                else:
                    y_pos = row_y_start
                final_positions[target_node] = (x_pos, y_pos)
                dpg.set_item_pos(target_node, [float(x_pos), float(y_pos)])
                continue

            # Sequential vertical stacking with dynamic height offsets
            curr_y = row_y_start
            for ntag in n_list:
                _, n_h = node_dims[ntag]
                final_positions[ntag] = (x_pos, curr_y)
                dpg.set_item_pos(ntag, [float(x_pos), float(curr_y)])
                curr_y += n_h + row_gap

        recompile_cb()
