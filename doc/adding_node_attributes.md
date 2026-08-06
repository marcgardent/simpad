# Developer Guide: How to Add a Node Attribute in SimPad

This guide explains step-by-step how to add a new attribute (input pin, output pin, or static parameter) to a node in SimPad cleanly and correctly, preserving code quality, graph compilation, UI rendering, and serialization.

---

## Architecture Overview

Adding an attribute involves 6 main layers:
1. **Node Definition Class** (`src/nodes/`) - Backend code generator.
2. **Registry & Factory** (`src/nodes/factory.py`) - Instantiation & lookup.
3. **Graph Schema** (`src/core/schema.py`) - Schema validation rules.
4. **Graph Compiler** (`src/core/compiler.py`) - Real-time Python compilation.
5. **UI Factory** (`src/gui/node_editor/node_factory_ui.py`) - DearPyGui widget rendering & input control pairing.
6. **Editor Tab & Serialization** (`src/gui/node_editor/editor_tab.py`) - Dynamic link visibility & JSON import/export.

---

## Step-by-Step Implementation Guide

### Step 1: Update the Node Backend Class (`src/nodes/`)
1. Open the node class file (or create a new one inheriting from `BaseNode`).
2. In `generate_code(self, ntag, ninfo, in_to_outs)`:
   - Extract the attribute tag from `ninfo` (e.g. `ninfo.get("in_my_attr")` or `ninfo.get("out_my_attr")`).
   - Extract fallback default value parameter if unconnected (e.g. `val_fallback = float(ninfo.get("val_my_attr", 0.0))`).
   - Emit Python statements that read connected input values or default fallbacks:
     ```python
     src_tag = in_to_outs.get(in_attr, [None])
     val = val_map.get(src_tag[0], val_fallback) if src_tag and src_tag[0] else val_fallback
     ```

---

### Step 2: Register Attribute in Schema (`src/core/schema.py`)
1. If adding a new sensor or global output attribute, append its identifier string (e.g., `"attr_out_my_sensor"`) to `VALID_SENSOR_OUTPUTS`.
2. Ensure `GraphSchemaValidator` accepts your attribute key in link validation loop (`in_attr`, `out_attr`, etc.).

---

### Step 3: Update Graph Compiler (`src/core/compiler.py`)
1. If the attribute is a live telemetry input signal (e.g. from `VehicleSensors`), extract it in `GraphCompiler.generate_python_source()`:
   ```python
   my_sensor_val = telemetry.get('my_sensor', 0.0)
   ```
2. Include the output pin tag in `val_map`:
   ```python
   'attr_out_my_sensor': my_sensor_val,
   ```

---

### Step 4: Render Attribute in UI Factory (`src/gui/node_editor/node_factory_ui.py`)
1. Open `NodeUIFactory` and locate the node creation method (e.g., `add_node_my_type`).
2. Generate unique DPG tags for the attribute pin, widget, and text label:
   ```python
   in_attr_tag  = f"attr_in_my_attr_{nid}"
   widget_tag   = f"val_my_attr_{nid}"
   label_tag    = f"lbl_my_attr_{nid}"
   ```
3. Create the input pin using **Connector VS Input Field pairing** (never show both simultaneously):
   ```python
   with dpg.node_attribute(label="My Attribute", attribute_type=dpg.mvNode_Attr_Input, tag=in_attr_tag):
       dpg.add_drag_float(label="My Value", default_value=float(val), width=90, tag=widget_tag, callback=lambda: recompile_cb())
       dpg.add_text("My Attribute", tag=label_tag, show=False)
   ```
4. Register `input_controls` in `custom_nodes[node_tag]`:
   ```python
   custom_nodes[node_tag] = {
       "type": "my_type",
       "in_attr": in_attr_tag,
       "widget_tag": widget_tag,
       "input_controls": [
           {"attr": in_attr_tag, "widget": widget_tag, "label": label_tag}
       ]
   }
   ```

---

### Step 5: Update Serialization & Visibility in Editor Tab (`src/gui/node_editor/editor_tab.py`)
1. **Dynamic Visibility**: `_update_embedded_controls_visibility()` automatically hides `widget_tag` and displays `label_tag` whenever a link is connected to `in_attr_tag`.
2. **Exporting Graph**: In `export_graph_to_dict()`, serialize the current widget value:
   ```python
   elif ntype == "my_type":
       ndata["in_attr"] = ninfo.get("in_attr")
       ndata["my_val"] = dpg.get_value(ninfo["widget_tag"]) if "widget_tag" in ninfo and dpg.does_item_exist(ninfo["widget_tag"]) else 0.0
   ```
3. **Importing / Deserializing Graph**: In `_load_graph_dict()`, restore the attribute parameter:
   ```python
   elif ntype == "my_type":
       my_val = ndata.get("my_val", 0.0)
       new_ntag = self._add_node_my_type(val=my_val, pos=pos)
       if "in_attr" in ndata: tag_remap[ndata["in_attr"]] = self._custom_nodes[new_ntag]["in_attr"]
   ```

---

## Summary Rules & Best Practices

- **Rule 1**: An input pin MUST show either an interactive input field OR a text label, **never both simultaneously**.
- **Rule 2**: Always generate unique DPG item tags using `get_next_nid()`.
- **Rule 3**: Never hardcode colors or static pixel offsets; use `apply_pin_theme()`.
- **Rule 4**: Run `python -m unittest discover tests` after modifying attributes to guarantee no regression in graph execution.
