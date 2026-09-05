"""
SimPulse SDK — Plugin Configuration Contract.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Type, TypeVar

T = TypeVar("T")


class IPluginConfigProvider(ABC):
    """
    Contract interface providing isolated, strongly-typed configuration storage to plugins.
    Plugins only interact with their own namespace.
    """

    @abstractmethod
    def get_plugin_config_as(self, plugin_id: str, dataclass_cls: Type[T]) -> T:
        """Instantiate a strongly-typed dataclass from plugin configuration."""
        ...

    @abstractmethod
    def set_plugin_config_from(self, plugin_id: str, dataclass_obj: object, auto_save: bool = True) -> None:
        """Store a strongly-typed dataclass into plugin configuration."""
        ...
