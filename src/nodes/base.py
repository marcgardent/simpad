"""
SimPad Nodes — Base Abstract Node Definition.
Defines the uniform interface for code-generation and validation across dedicated haptic nodes.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Tuple


class BaseNode(ABC):
    """Abstract base class for all standalone haptic processing nodes."""

    @property
    @abstractmethod
    def node_type(self) -> str:
        """Returns the unique identifier for this node type matching schema specifications."""
        pass

    @property
    def display_name(self) -> str:
        """Human-readable name of the node for UI menus and descriptions."""
        return self.node_type.capitalize()

    @abstractmethod
    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        """
        Generates Python code statements evaluating this node within the haptic execution function.
        
        :param ntag: Unique string tag of the node (e.g. 'node_3')
        :param ninfo: Parameters dictionary stored in the graph JSON topology
        :param in_to_outs: Mapping from target input pins to list of connected source output pins
        :return: List of indented Python source code lines
        """
        pass

    def validate(self, ninfo: dict) -> Tuple[bool, str]:
        """Validates node parameters. Returns (is_valid, error_message)."""
        if not isinstance(ninfo, dict):
            return False, f"Node '{self.node_type}' definition must be a dictionary."
        return True, "OK"
