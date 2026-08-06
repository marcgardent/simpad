"""
SimPad Haptic Middleware — Editor Modal Manager.
Encapsulates all DearPyGui modal dialog creation and interactions for profiles, nodes, and python code preview.
"""

import dearpygui.dearpygui as dpg
from typing import Dict, Any, Tuple, Callable, Optional
from src.core.compiler import GraphCompiler


class EditorModalManager:
    """Manages creation, positioning, and lifecycle of Node Editor modal windows."""

    @staticmethod
    def get_centered_modal_pos(width: int = 440, height: int = 170) -> Tuple[int, int]:
        """Calculates centered viewport coordinates for modal positioning."""
        vp_w = dpg.get_viewport_width() if dpg.is_viewport_ok() else 1240
        vp_h = dpg.get_viewport_height() if dpg.is_viewport_ok() else 780
        pos_x = max(20, (vp_w - width) // 2)
        pos_y = max(20, (vp_h - height) // 2)
        return (pos_x, pos_y)

    def open_new_profile_modal(self, profile_manager, on_profile_created: Callable[[str, dict], None]):
        """Opens a modal prompting user for new profile name."""
        modal_tag = "modal_new_profile"
        if dpg.does_item_exist(modal_tag):
            dpg.delete_item(modal_tag)

        input_tag = "input_new_profile_name"
        pos = self.get_centered_modal_pos(440, 170)

        base_name = "New Profile"
        counter = 1
        default_name = base_name
        while default_name in profile_manager.profiles:
            counter += 1
            default_name = f"{base_name} {counter}"

        def create_new_profile():
            new_name = dpg.get_value(input_tag).strip()
            if not new_name:
                return
            blank_graph = {"nodes": {}, "links": []}
            prof, msg = profile_manager.save_profile(new_name, blank_graph)
            if prof:
                on_profile_created(prof.name, blank_graph)
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

    def open_rename_profile_modal(self, profile_manager, selected_display: str, on_profile_renamed: Callable[[str], None]):
        """Opens a modal window allowing user to rename active profile."""
        prof = profile_manager.get_profile(selected_display)
        if not prof or prof.is_preset:
            return

        modal_tag = "modal_rename_profile"
        if dpg.does_item_exist(modal_tag):
            dpg.delete_item(modal_tag)

        input_tag = "input_rename_profile_name"
        pos = self.get_centered_modal_pos(440, 170)

        def apply_profile_rename():
            new_name = dpg.get_value(input_tag).strip()
            if not new_name:
                return
            renamed_prof, msg = profile_manager.rename_profile(selected_display, new_name)
            if renamed_prof:
                on_profile_renamed(renamed_prof.name)
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

    def open_rename_node_modal(self, custom_nodes: Dict[str, dict], recompile_cb: Callable[[], None]):
        """Opens a modal window allowing user to rename selected node (F2)."""
        if not dpg.does_item_exist("node_editor_canvas"):
            return

        selected_nodes = dpg.get_selected_nodes("node_editor_canvas")
        if not selected_nodes:
            return

        node_id = selected_nodes[0]
        node_tag = node_id
        if node_id not in custom_nodes:
            for ntag in list(custom_nodes.keys()):
                if dpg.does_item_exist(ntag) and (dpg.get_alias_id(ntag) == node_id or ntag == node_id):
                    node_tag = ntag
                    break

        current_label = dpg.get_item_label(node_tag) if dpg.does_item_exist(node_tag) else "Node"

        modal_tag = "modal_rename_node"
        if dpg.does_item_exist(modal_tag):
            dpg.delete_item(modal_tag)

        input_tag = "input_rename_node_label"
        pos = self.get_centered_modal_pos(440, 170)

        def apply_node_rename():
            new_label = dpg.get_value(input_tag).strip()
            if new_label and dpg.does_item_exist(node_tag):
                dpg.configure_item(node_tag, label=new_label)
                if node_tag in custom_nodes:
                    custom_nodes[node_tag]["label"] = new_label
                recompile_cb()
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

    def show_python_code_modal(self, graph_dict: dict):
        """Opens a modal window displaying generated standalone Python code."""
        modal_tag = "modal_python_code_export"
        if dpg.does_item_exist(modal_tag):
            dpg.delete_item(modal_tag)

        py_source = GraphCompiler.generate_python_source(graph_dict)
        pos = self.get_centered_modal_pos(700, 500)

        with dpg.window(label="Generated Python Graph Code", tag=modal_tag, modal=True, show=True, width=700, height=500, pos=pos):
            dpg.add_text("Standalone Compiled Python Function for High-Frequency Synthesizer Engine:", color=[0, 210, 255, 255])
            dpg.add_spacer(height=6)
            dpg.add_input_text(multiline=True, readonly=True, default_value=py_source, width=-1, height=400)
            dpg.add_spacer(height=6)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Close", width=120, callback=lambda: dpg.delete_item(modal_tag))
