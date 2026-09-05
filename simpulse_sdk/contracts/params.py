"""
SimPulse SDK — Declarative Configurable Parameters for Plugins and Components.
Provides interface abstractions and base contracts for parameters.
SOLID architecture (SRP, OCP, LSP).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Generic, TypeVar, Union, Protocol, runtime_checkable

T = TypeVar("T")

ParamScalarValue = Union[bool, int, float, str]


@runtime_checkable
class IParamDescriptor(Protocol[T]):
    """
    Abstract interface descriptor of a configurable parameter (PEP 544).
    Provides type validation and metadata contract without UI dependencies.
    """
    name: str
    label: str
    description: str
    default: Optional[T]

    def cast_and_validate(self, value: ParamScalarValue) -> T:
        """Converts and clamps value according to descriptor constraints."""
        ...


@dataclass
class ConfigParam(ABC, Generic[T]):
    """
    Abstract base descriptor of a configurable parameter for plugins and components.
    Each parameter has a unique identifier (name), a display label (label),
    a description (description), and a default value.
    Pure domain abstraction, free of any UI framework dependencies.
    """
    name: str
    label: str
    description: str = ""
    default: Optional[T] = None

    @abstractmethod
    def cast_and_validate(self, value: ParamScalarValue) -> T:
        """Converts and clamps value according to descriptor constraints."""
        pass


# Generic & backward-compatible aliases
PluginParam = ConfigParam
RoleParam = ConfigParam
SubpluginParam = ConfigParam
ParamDescriptor = ConfigParam

__all__ = [
    "IParamDescriptor",
    "ConfigParam",
    "PluginParam",
    "RoleParam",
    "SubpluginParam",
    "ParamDescriptor",
    "ParamScalarValue",
]

