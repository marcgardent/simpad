"""
Tests unitaires pour RoleRegistry et RoleFactory (Race Engineer).
"""

import pytest
from simpad_qt.core.engineer.base import BaseRole, EngineerMessage, RoleStatus
from simpad_qt.core.engineer.context import EngineerContext
from simpad_qt.core.engineer.registry import RoleRegistry
from simpad_qt.core.engineer.factory import RoleFactory


class DummyRole(BaseRole):
    """Rôle de test factice pour vérifier l'enregistrement dynamique."""
    def __init__(self, role_id="dummy", name="Dummy Role", description="", priority=40, enabled=True, audio_engine=None):
        super().__init__(role_id, name, description, priority, enabled, audio_engine)
        self._busy = False

    def is_busy(self) -> bool:
        return self._busy

    def update(self, context: EngineerContext):
        return None


def test_role_registry_registration():
    """Vérifie l'enregistrement et les métadonnées dans RoleRegistry."""
    RoleRegistry.register_role_class(
        role_id="custom_dummy",
        role_cls=DummyRole,
        name="Custom Dummy",
        description="A test role",
        default_priority=65,
    )

    assert RoleRegistry.is_registered("custom_dummy")
    cls_ref = RoleRegistry.get_role_class("custom_dummy")
    assert cls_ref is DummyRole

    meta = RoleRegistry.get_metadata("custom_dummy")
    assert meta is not None
    assert meta["name"] == "Custom Dummy"
    assert meta["default_priority"] == 65


def test_role_factory_instantiation():
    """Vérifie l'instanciation de rôles via RoleFactory."""
    RoleRegistry.register_role_class(
        role_id="factory_test_role",
        role_cls=DummyRole,
        name="Factory Test",
        default_priority=80,
    )

    role = RoleFactory.create_role("factory_test_role", priority=90, enabled=True)
    assert isinstance(role, DummyRole)
    assert role.role_id == "factory_test_role"
    assert role.priority == 90
    assert role.enabled is True
    assert role.status == RoleStatus.IDLE


def test_role_factory_create_all():
    """Vérifie que create_all_roles instancie tous les rôles intégrés triés par priorité."""
    roles = RoleFactory.create_all_roles()
    assert len(roles) >= 2

    # Vérifier que le tri par priorité décroissante est respecté
    priorities = [r.priority for r in roles]
    assert priorities == sorted(priorities, reverse=True)

    # Vérifier la présence des rôles obligatoires
    role_ids = [r.role_id for r in roles]
    assert "lap_validity" in role_ids
    assert "traffic_spotter" in role_ids
