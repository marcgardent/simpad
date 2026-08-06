"""
SimPad Haptic Middleware — Graph Selection Manager.
Handles graph selection lookup, alias resolution, node deletion, and link pruning.
"""

import dearpygui.dearpygui as dpg
from typing import Dict, Tuple, Callable


class GraphSelectionManager:
    """Manages node and link selection and deletion operations on the canvas."""

    DEFAULT_SENSOR_TAGS = [
        "node_sensor_abs", "node_sensor_tc", "node_sensor_over",
        "node_sensor_und", "node_sensors", "node_xinput"
    ]

    @staticmethod
    def delete_selected_items(
        custom_nodes: Dict[str, dict],
        node_links: Dict[int, Tuple[str, str]],
        factory,
        recompile_cb: Callable[[], None]
    ):
        """Keyboard Del / Suppr Key Handler: Deletes selected nodes and links."""
        if not dpg.does_item_exist("node_editor_canvas"):
            return

        selected_links = dpg.get_selected_links("node_editor_canvas")
        for link_id in selected_links:
            if link_id in node_links:
                del node_links[link_id]
            if dpg.does_item_exist(link_id):
                dpg.delete_item(link_id)

        selected_nodes = dpg.get_selected_nodes("node_editor_canvas")
        for node_id in selected_nodes:
            node_tag = None
            if node_id in custom_nodes:
                node_tag = node_id
            else:
                for ntag in list(custom_nodes.keys()):
                    if dpg.does_item_exist(ntag) and (dpg.get_alias_id(ntag) == node_id or ntag == node_id):
                        node_tag = ntag
                        break

            if node_tag:
                factory.delete_custom_node(custom_nodes, node_links, node_tag, recompile_cb)
            else:
                target_tag = node_id
                if not dpg.does_item_exist(target_tag):
                    for btag in GraphSelectionManager.DEFAULT_SENSOR_TAGS:
                        if dpg.does_item_exist(btag) and dpg.get_alias_id(btag) == node_id:
                            target_tag = btag
                            break

                if dpg.does_item_exist(target_tag):
                    children = dpg.get_item_children(target_tag, slot=1) or []
                    attr_ids = set(children)
                    links_to_delete = []
                    for link_id, (o, i) in list(node_links.items()):
                        o_id = dpg.get_alias_id(o) if dpg.does_item_exist(o) else o
                        i_id = dpg.get_alias_id(i) if dpg.does_item_exist(i) else i
                        if o in attr_ids or i in attr_ids or o_id in attr_ids or i_id in attr_ids:
                            links_to_delete.append(link_id)

                    for lid in links_to_delete:
                        if lid in node_links:
                            del node_links[lid]
                        if dpg.does_item_exist(lid):
                            dpg.delete_item(lid)

                    dpg.delete_item(target_tag)

        recompile_cb()
