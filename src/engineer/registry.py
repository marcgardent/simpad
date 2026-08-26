"""
SimPad Race Engineer — Enregistreur dynamique de Rôles (Role Registry).
Permet l'enregistrement dynamique de rôles via décorateur ou appel programmatique.
"""

import logging
from typing import Dict, Type, Optional, List, Any, Callable
from src.engineer.base import BaseRole

logger = logging.getLogger(__name__)


class RoleRegistry:
    """
    Registre centralisé des classes de rôles disponibles pour l'ingénieur de course.
    Suit le patron de conception Registry (SOLID / Open-Closed Principle).
    """

    _registry: Dict[str, Type[BaseRole]] = {}
    _metadata: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def register(
        cls,
        role_id: str,
        name: Optional[str] = None,
        description: str = "",
        default_priority: int = 50,
    ) -> Callable[[Type[BaseRole]], Type[BaseRole]]:
        """
        Décorateur pour enregistrer une classe de rôle dans le registre.

        Usage:
            @RoleRegistry.register("traffic_spotter", name="Traffic Spotter FSM", default_priority=100)
            class TrafficSpotterRole(BaseRole):
                ...
        """
        def decorator(role_cls: Type[BaseRole]) -> Type[BaseRole]:
            role_name = name or role_cls.__name__
            cls._registry[role_id] = role_cls
            cls._metadata[role_id] = {
                "role_id": role_id,
                "name": role_name,
                "description": description or (role_cls.__doc__ or "").strip(),
                "default_priority": default_priority,
                "class": role_cls,
            }
            logger.debug(f"[RoleRegistry] Enregistrement du rôle '{role_id}' ({role_name})")
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
        """Enregistrement programmatique direct d'une classe de rôle."""
        role_name = name or role_cls.__name__
        cls._registry[role_id] = role_cls
        cls._metadata[role_id] = {
            "role_id": role_id,
            "name": role_name,
            "description": description or (role_cls.__doc__ or "").strip(),
            "default_priority": default_priority,
            "class": role_cls,
        }

    @classmethod
    def get_role_class(cls, role_id: str) -> Optional[Type[BaseRole]]:
        """Retourne la classe du rôle correspondant à role_id, ou None."""
        return cls._registry.get(role_id)

    @classmethod
    def get_metadata(cls, role_id: str) -> Optional[Dict[str, Any]]:
        """Retourne les métadonnées enregistrées pour un role_id."""
        return cls._metadata.get(role_id)

    @classmethod
    def list_roles(cls) -> List[Dict[str, Any]]:
        """Retourne la liste des métadonnées de tous les rôles enregistrés."""
        return [
            {
                "role_id": k,
                "name": v["name"],
                "description": v["description"],
                "default_priority": v["default_priority"],
            }
            for k, v in cls._metadata.items()
        ]

    @classmethod
    def is_registered(cls, role_id: str) -> bool:
        """Vérifie si un rôle est présent dans le registre."""
        return role_id in cls._registry

    @classmethod
    def clear(cls) -> None:
        """Vide le registre (principalement pour les tests unitaires)."""
        cls._registry.clear()
        cls._metadata.clear()
