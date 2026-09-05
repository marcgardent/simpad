"""
SimPad Race Engineer — Role Factory.
Instantiates race engineer roles following Factory Method / Abstract Factory pattern.
"""

import logging
from typing import Optional, List, Dict
from .base import BaseRole, AudioEngineType
from .registry import RoleRegistry

from .params import ParamScalarValue

logger = logging.getLogger(__name__)


class RoleFactory:
    """
    Factory instantiating roles registered in RoleRegistry.
    Ensures dependency injection (audio engine, configuration).
    """

    @classmethod
    def create_role(
        cls,
        role_id: str,
        audio_engine: Optional[AudioEngineType] = None,
        priority: Optional[int] = None,
        enabled: bool = True,
        **kwargs: ParamScalarValue,
    ) -> BaseRole:
        """
        Instantiates a specific role by its identifier role_id.
        """
        role_cls = RoleRegistry.get_role_class(role_id)
        if role_cls is None:
            raise ValueError(f"[RoleFactory] No role registered with identifier '{role_id}'.")

        meta = RoleRegistry.get_metadata(role_id)
        role_name = meta.name if meta else role_id
        role_desc = meta.description if meta else ""
        role_prio = priority if priority is not None else (meta.default_priority if meta else 50)

        instance = role_cls(
            role_id=role_id,
            name=role_name,
            description=role_desc,
            priority=role_prio,
            enabled=enabled,
            audio_engine=audio_engine,
            **kwargs,
        )
        return instance

    @classmethod
    def create_all_roles(cls, audio_engine: Optional[AudioEngineType] = None) -> List[BaseRole]:
        """
        Instantiates all roles registered in the registry and returns them
        sorted by descending priority.
        """
        # Ensure all built-in roles are imported and registered
        cls._ensure_builtin_roles_loaded()

        roles: List[BaseRole] = []
        for meta in RoleRegistry.list_roles():
            role_id = meta.role_id
            try:
                role_instance = cls.create_role(role_id=role_id, audio_engine=audio_engine)
                roles.append(role_instance)
            except Exception as e:
                logger.error(f"[RoleFactory] Error instantiating role '{role_id}': {e}")

        # Sort by descending priority
        roles.sort(key=lambda r: r.priority, reverse=True)
        return roles

    @classmethod
    def _ensure_builtin_roles_loaded(cls) -> None:
        """Forces import of built-in sub-plugins from race_engineer plugin to trigger registration."""
        try:
            from . import subplugins
        except ImportError as e:
            logger.debug(f"[RoleFactory] Builtin subplugins import: {e}")


# Sub-plugin factory alias
SubpluginFactory = RoleFactory
