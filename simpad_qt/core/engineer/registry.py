"""
SimPad Race Engineer — Dynamic Role Registry.
Allows dynamic role registration via decorator or programmatic call.
"""

import logging
from dataclasses import dataclass
from typing import Dict, Type, Optional, List, Callable
from .base import BaseRole

logger = logging.getLogger(__name__)


@dataclass
class RoleMetadata:
    """Metadata describing a registered race engineer role."""
    role_id: str
    name: str
    description: str = ""
    default_priority: int = 50
    role_class: Optional[Type[BaseRole]] = None


class RoleRegistry:
    """
    Central registry of available race engineer role classes.
    Follows Registry design pattern (SOLID / Open-Closed Principle).
    """

    _registry: Dict[str, Type[BaseRole]] = {}
    _metadata: Dict[str, RoleMetadata] = {}

    @classmethod
    def register(
        cls,
        role_id: str,
        name: Optional[str] = None,
        description: str = "",
        default_priority: int = 50,
    ) -> Callable[[Type[BaseRole]], Type[BaseRole]]:
        """
        Decorator to register a role class in the registry.

        Usage:
            @RoleRegistry.register("traffic_spotter", name="Traffic Spotter FSM", default_priority=100)
            class TrafficSpotterRole(BaseRole):
                ...
        """
        def decorator(role_cls: Type[BaseRole]) -> Type[BaseRole]:
            role_name = name or role_cls.__name__
            cls._registry[role_id] = role_cls
            cls._metadata[role_id] = RoleMetadata(
                role_id=role_id,
                name=role_name,
                description=description or (role_cls.__doc__ or "").strip(),
                default_priority=default_priority,
                role_class=role_cls,
            )
            logger.debug(f"[RoleRegistry] Registered role '{role_id}' ({role_name})")
            return role_cls

        return decorator

    @classmethod
    def register_role_class(
        cls,
        role_id: str,
        role_cls: Type[BaseRole],
        name: Optional[str] = None,
        description: str = "",
        default_priority: int = 50,
    ) -> None:
        """Direct programmatic registration of a role class."""
        role_name = name or role_cls.__name__
        cls._registry[role_id] = role_cls
        cls._metadata[role_id] = RoleMetadata(
            role_id=role_id,
            name=role_name,
            description=description or (role_cls.__doc__ or "").strip(),
            default_priority=default_priority,
            role_class=role_cls,
        )

    @classmethod
    def get_role_class(cls, role_id: str) -> Optional[Type[BaseRole]]:
        """Returns role class matching role_id, or None."""
        return cls._registry.get(role_id)

    @classmethod
    def get_metadata(cls, role_id: str) -> Optional[RoleMetadata]:
        """Returns registered metadata for role_id."""
        return cls._metadata.get(role_id)

    @classmethod
    def list_roles(cls) -> List[RoleMetadata]:
        """Returns metadata list for all registered roles."""
        return list(cls._metadata.values())

    @classmethod
    def is_registered(cls, role_id: str) -> bool:
        """Checks if a role is registered."""
        return role_id in cls._registry

    @classmethod
    def clear(cls) -> None:
        """Clears the registry (primarily for unit tests)."""
        cls._registry.clear()
        cls._metadata.clear()
