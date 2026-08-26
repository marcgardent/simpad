"""
SimPad Race Engineer — Fabrique de Rôles (Role Factory).
Instancie les rôles de l'ingénieur de course selon le patron Factory Method / Abstract Factory.
"""

import logging
from typing import Optional, List, Dict, Any
from src.engineer.base import BaseRole
from src.engineer.registry import RoleRegistry

logger = logging.getLogger(__name__)


class RoleFactory:
    """
    Fabrique instanciant les rôles enregistrés dans le RoleRegistry.
    Garantit l'injection correcte des dépendances (moteur audio, configuration).
    """

    @classmethod
    def create_role(
        cls,
        role_id: str,
        audio_engine: Optional[Any] = None,
        priority: Optional[int] = None,
        enabled: bool = True,
        **kwargs: Any,
    ) -> BaseRole:
        """
        Instancie un rôle spécifique par son identifiant role_id.
        """
        role_cls = RoleRegistry.get_role_class(role_id)
        if role_cls is None:
            raise ValueError(f"[RoleFactory] Aucun rôle enregistré avec l'identifiant '{role_id}'.")

        meta = RoleRegistry.get_metadata(role_id) or {}
        role_name = meta.get("name", role_id)
        role_desc = meta.get("description", "")
        role_prio = priority if priority is not None else meta.get("default_priority", 50)

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
    def create_all_roles(cls, audio_engine: Optional[Any] = None) -> List[BaseRole]:
        """
        Instancie tous les rôles enregistrés dans le registre et les retourne
        triés par priorité décroissante.
        """
        # S'assurer que tous les rôles intégrés sont importés et enregistrés
        cls._ensure_builtin_roles_loaded()

        roles: List[BaseRole] = []
        for meta in RoleRegistry.list_roles():
            role_id = meta["role_id"]
            try:
                role_instance = cls.create_role(role_id=role_id, audio_engine=audio_engine)
                roles.append(role_instance)
            except Exception as e:
                logger.error(f"[RoleFactory] Erreur lors de l'instanciation du rôle '{role_id}': {e}")

        # Tri par priorité décroissante
        roles.sort(key=lambda r: r.priority, reverse=True)
        return roles

    @classmethod
    def _ensure_builtin_roles_loaded(cls) -> None:
        """Force l'import des rôles prédéfinis pour déclencher leurs décorateurs @register."""
        try:
            import src.engineer.roles
        except ImportError as e:
            logger.debug(f"[RoleFactory] Import des rôles intégrés : {e}")
