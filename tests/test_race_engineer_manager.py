"""
Tests unitaires pour RaceEngineer Manager (Priorités, Tri, Activation, IHM, Sauvegarde).
"""

import pytest
from src.engineer.manager import RaceEngineer
from src.engineer.base import BaseRole, EngineerMessage, RoleStatus
from src.engineer.context import EngineerContext


class MockRoleA(BaseRole):
    def __init__(self, **kwargs):
        super().__init__(role_id="role_a", name="Role A", priority=100, **kwargs)
        self._busy = False

    def is_busy(self) -> bool:
        return self._busy

    def update(self, context: EngineerContext):
        if self._busy:
            return EngineerMessage(phrase_key="one", priority=self.priority, role_id=self.role_id)
        return None


class MockRoleB(BaseRole):
    def __init__(self, **kwargs):
        super().__init__(role_id="role_b", name="Role B", priority=50, **kwargs)
        self._busy = False

    def is_busy(self) -> bool:
        return self._busy

    def update(self, context: EngineerContext):
        return None


def test_race_engineer_sorting_and_priorities():
    """Vérifie le tri initial et le réordonnancement des rôles."""
    engineer = RaceEngineer(auto_load_builtin_roles=False)
    role_b = MockRoleB()
    role_a = MockRoleA()

    engineer.add_role(role_b)
    engineer.add_role(role_a)

    roles = engineer.get_roles()
    assert roles[0].role_id == "role_a"
    assert roles[1].role_id == "role_b"


def test_race_engineer_move_up_down():
    """Vérifie la montée et descente de priorité unitaire."""
    engineer = RaceEngineer(auto_load_builtin_roles=False)
    role_a = MockRoleA()
    role_b = MockRoleB()
    engineer.add_role(role_a)
    engineer.add_role(role_b)

    # Monter role_b au-dessus de role_a
    assert engineer.move_role_up("role_b") is True
    roles = engineer.get_roles()
    assert roles[0].role_id == "role_b"
    assert roles[1].role_id == "role_a"

    # Descendre role_b
    assert engineer.move_role_down("role_b") is True
    roles = engineer.get_roles()
    assert roles[0].role_id == "role_a"
    assert roles[1].role_id == "role_b"


def test_race_engineer_reorder_full_list():
    """Vérifie la réorganisation globale des priorités."""
    engineer = RaceEngineer(auto_load_builtin_roles=False)
    role_a = MockRoleA()
    role_b = MockRoleB()
    engineer.add_role(role_a)
    engineer.add_role(role_b)

    engineer.reorder_roles(["role_b", "role_a"])
    roles = engineer.get_roles()
    assert roles[0].role_id == "role_b"
    assert roles[1].role_id == "role_a"
    assert roles[0].priority > roles[1].priority


def test_race_engineer_enable_disable():
    """Vérifie l'activation et la désactivation d'un rôle."""
    engineer = RaceEngineer(auto_load_builtin_roles=False)
    role_a = MockRoleA()
    engineer.add_role(role_a)

    engineer.set_role_enabled("role_a", False)
    assert role_a.enabled is False

    # Le rôle désactivé ne produit aucun message
    role_a._busy = True
    msgs = engineer.update(telemetry=None, scoring=None)
    assert len(msgs) == 0

    engineer.set_role_enabled("role_a", True)
    assert role_a.enabled is True
    msgs2 = engineer.update(telemetry=None, scoring=None)
    assert len(msgs2) == 1


def test_race_engineer_busy_reporting():
    """Vérifie la détection globale de l'état BUSY."""
    engineer = RaceEngineer(auto_load_builtin_roles=False)
    role_a = MockRoleA()
    role_b = MockRoleB()
    engineer.add_role(role_a)
    engineer.add_role(role_b)

    assert not engineer.is_any_role_busy()
    assert len(engineer.get_busy_roles()) == 0

    role_a._busy = True
    assert engineer.is_any_role_busy()
    busy_list = engineer.get_busy_roles()
    assert len(busy_list) == 1
    assert busy_list[0].role_id == "role_a"


def test_race_engineer_save_and_load_config():
    """Vérifie la sérialisation et restauration de configuration."""
    engineer = RaceEngineer(auto_load_builtin_roles=False)
    role_a = MockRoleA()
    role_b = MockRoleB()
    engineer.add_role(role_a)
    engineer.add_role(role_b)

    engineer.set_role_enabled("role_a", False)
    engineer.move_role_up("role_b")

    saved_cfg = engineer.save_configuration()
    assert saved_cfg["roles"]["role_a"]["enabled"] is False
    assert saved_cfg["order"] == ["role_b", "role_a"]

    # Nouvel ingénieur
    engineer2 = RaceEngineer(auto_load_builtin_roles=False)
    engineer2.add_role(MockRoleA())
    engineer2.add_role(MockRoleB())
    engineer2.load_configuration(saved_cfg)

    roles2 = engineer2.get_roles()
    assert roles2[0].role_id == "role_b"
    assert engineer2.get_role("role_a").enabled is False
