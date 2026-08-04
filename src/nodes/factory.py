"""
SimPad Nodes — Central Node Factory & Registry.
Manages dynamic registration and code generation for all dedicated haptic node classes.
"""

from typing import Dict, List, Set, Optional, Type, Union
from src.nodes.base import BaseNode
from src.nodes.constant import ConstantNode, FloatConstantNode
from src.nodes.multiply import MultiplyNode
from src.nodes.array_multiply import ArrayMultiplyNode
from src.nodes.normalize import NormalizeNode
from src.nodes.math import MathNode
from src.nodes.transform import TransformNode
from src.nodes.shape import ShapeNode
from src.nodes.sensor import (
    OverBrakingSensorNode,
    OverAccelSensorNode,
    OversteerSensorNode,
    UndersteerSensorNode,
)
from src.nodes.output import XInputOutputNode


class NodeFactory:
    """Factory and registry pattern for managing haptic graph nodes."""

    _registry: Dict[str, BaseNode] = {}

    @classmethod
    def register(cls, node_instance_or_cls: Union[BaseNode, Type[BaseNode]]):
        """Registers a node instance or class into the factory registry."""
        node = node_instance_or_cls() if isinstance(node_instance_or_cls, type) else node_instance_or_cls
        cls._registry[node.node_type] = node

    @classmethod
    def get_node(cls, node_type: str) -> Optional[BaseNode]:
        """Retrieves the node instance registered for the specified node_type string."""
        return cls._registry.get(node_type)

    @classmethod
    def generate_code(cls, node_type: str, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        """Delineates code generation to the dedicated node handler in the factory."""
        node = cls.get_node(node_type)
        if not node:
            return [f"    # Unknown node type '{node_type}' for {ntag}"]
        return node.generate_code(ntag, ninfo, in_to_outs)

    @classmethod
    def get_registered_types(cls) -> Set[str]:
        """Returns the set of all valid, registered node_type identifiers."""
        return set(cls._registry.keys())


# Automatically register built-in node types
def _initialize_factory():
    NodeFactory.register(ConstantNode)
    NodeFactory.register(FloatConstantNode)
    NodeFactory.register(MultiplyNode)
    NodeFactory.register(ArrayMultiplyNode)
    NodeFactory.register(NormalizeNode)
    NodeFactory.register(MathNode)
    NodeFactory.register(TransformNode)
    NodeFactory.register(ShapeNode)
    NodeFactory.register(OverBrakingSensorNode)
    NodeFactory.register(OverAccelSensorNode)
    NodeFactory.register(OversteerSensorNode)
    NodeFactory.register(UndersteerSensorNode)
    NodeFactory.register(XInputOutputNode)



_initialize_factory()

