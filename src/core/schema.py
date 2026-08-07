"""
SimPad Haptic Middleware — Graph Schema & AI Preset Validator.

Provides schema validation, JSON serialization/deserialization, and specifications
for AI-assisted preset generation.
"""

import json
from typing import Dict, Any, Tuple, List, Optional


from src.nodes.factory import NodeFactory

VALID_NODE_TYPES = NodeFactory.get_registered_types()

VALID_SENSOR_OUTPUTS = {
    "attr_out_abs", "attr_out_abs_l", "attr_out_abs_r",
    "attr_out_tc", "attr_out_tc_l", "attr_out_tc_r",
    "attr_out_over", "attr_out_over_l", "attr_out_over_r",
    "attr_out_und", "attr_out_und_l", "attr_out_und_r",
    "attr_out_over_rev", "attr_out_under_rev", "attr_out_rpm", "attr_out_gear",
    "attr_out_travel", "attr_out_travel_l", "attr_out_travel_r",
    "attr_out_travel_fl", "attr_out_travel_fr", "attr_out_travel_rl", "attr_out_travel_rr"
}

VALID_MOTOR_INPUTS = {
    "attr_in_low",
    "attr_in_high"
}


class GraphSchemaValidator:
    """Validates node graph dictionaries generated manually or by AI models."""

    @staticmethod
    def _validate_structure(graph_data: dict) -> Tuple[bool, str]:
        """SLAP Helper: Verifies JSON object top-level structure keys."""
        if not isinstance(graph_data, dict):
            return False, "Graph data must be a JSON object (dict)."
        if "nodes" not in graph_data or not isinstance(graph_data["nodes"], dict):
            return False, "Graph data must contain a 'nodes' dict."
        if "links" not in graph_data or not isinstance(graph_data["links"], list):
            return False, "Graph data must contain a 'links' list."
        return True, "OK"

    @staticmethod
    def _validate_node_entries(nodes: dict, available_outputs: set, available_inputs: set) -> Tuple[bool, str]:
        """SLAP Helper: Validates individual node types and collects output/input attribute pins."""
        for ntag, ninfo in nodes.items():
            if not isinstance(ninfo, dict):
                return False, f"Node '{ntag}' definition must be a dict."

            ntype = ninfo.get("type")
            if ntype not in VALID_NODE_TYPES:
                return False, f"Node '{ntag}' has invalid type '{ntype}'. Allowed: {sorted(list(VALID_NODE_TYPES))}"

            for key, val in ninfo.items():
                if key.startswith("out_") and isinstance(val, str):
                    available_outputs.add(val)

            for key in ["in_attr", "in_a", "in_b", "in_on", "in_off", "in_low", "in_high", "in_freq"]:
                val = ninfo.get(key)
                if val and isinstance(val, str):
                    available_inputs.add(val)

        return True, "OK"

    @staticmethod
    def _validate_link_entries(links: list, available_outputs: set, available_inputs: set) -> Tuple[bool, str]:
        """SLAP Helper: Validates link tuple format and pin attribute registration."""
        for idx, link in enumerate(links):
            if not isinstance(link, (list, tuple)) or len(link) != 2:
                return False, f"Link #{idx} must be a 2-element list [src_output_attr, tgt_input_attr]."

            src_out, tgt_in = link[0], link[1]
            if src_out not in available_outputs:
                return False, f"Link #{idx} references unknown source output pin '{src_out}'."
            if tgt_in not in available_inputs:
                return False, f"Link #{idx} references unknown target input pin '{tgt_in}'."

        return True, "OK"

    @staticmethod
    def validate(graph_data: dict) -> Tuple[bool, str]:
        """
        Validates the structure, nodes, parameters and link connections of a graph dictionary (CCN < 5).
        Returns (is_valid, error_message).
        """
        valid_struct, err_msg = GraphSchemaValidator._validate_structure(graph_data)
        if not valid_struct:
            return False, err_msg

        nodes = graph_data["nodes"]
        links = graph_data["links"]

        available_outputs = set(VALID_SENSOR_OUTPUTS)
        available_inputs = set(VALID_MOTOR_INPUTS)

        valid_nodes, err_msg = GraphSchemaValidator._validate_node_entries(nodes, available_outputs, available_inputs)
        if not valid_nodes:
            return False, err_msg

        valid_links, err_msg = GraphSchemaValidator._validate_link_entries(links, available_outputs, available_inputs)
        if not valid_links:
            return False, err_msg

        return True, "Valid Graph Schema"


def export_graph_json(graph_data: dict, indent: int = 2) -> str:
    """Serializes a graph dictionary into a clean JSON string."""
    return json.dumps(graph_data, indent=indent)


def import_graph_json(json_str: str) -> Tuple[Optional[dict], str]:
    """Parses a JSON string, validates its schema, and returns (graph_dict, status_msg)."""
    try:
        data = json.loads(json_str)
    except Exception as e:
        return None, f"Invalid JSON Syntax: {e}"

    # Extract inner graph_data if wrapped in a profile container
    if "graph_data" in data and isinstance(data["graph_data"], dict):
        data = data["graph_data"]

    is_valid, msg = GraphSchemaValidator.validate(data)
    if not is_valid:
        return None, f"Schema Validation Error: {msg}"

    return data, "OK"
