"""
Tests unitaires pour RaceEngineer Manager (Priorités, Tri, Activation, IHM, Sauvegarde).
"""

import pytest
from simpulse.builtin_plugins.race_engineer.manager import RaceEngineer
from simpulse.builtin_plugins.race_engineer.base import BaseRole, RoleHostSlot, EngineerMessage, RoleStatus
from simpulse.builtin_plugins.race_engineer.context import EngineerContext


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
    assert engineer.is_role_enabled("role_a") is False
    assert engineer.get_slot("role_a").enabled is False

    # Le rôle désactivé ne produit aucun message
    role_a._busy = True
    msgs = engineer.update(telemetry=None, scoring=None)
    assert len(msgs) == 0

    engineer.set_role_enabled("role_a", True)
    assert engineer.is_role_enabled("role_a") is True
    assert engineer.get_slot("role_a").enabled is True
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
    assert engineer2.is_role_enabled("role_a") is False


def test_race_engineer_file_persistence(tmp_path):
    """Vérifie la sauvegarde et le chargement via fichier JSON sur disque."""
    config_file = tmp_path / "test_engineer_cfg.json"

    # Initialisation avec auto-load builtin roles et un fichier custom
    engineer = RaceEngineer(auto_load_builtin_roles=True, config_path=config_file)
    assert len(engineer.get_roles()) > 0

    # Désactiver individuellement des rôles
    engineer.set_role_enabled("lap_validity", False)
    engineer.set_role_enabled("traffic_jam", False)
    engineer.move_role_up("traffic_spotter")

    assert config_file.exists()

    # Recharger dans une nouvelle instance
    engineer2 = RaceEngineer(auto_load_builtin_roles=True, config_path=config_file)
    assert engineer2.is_role_enabled("lap_validity") is False
    assert engineer2.is_role_enabled("traffic_jam") is False
    assert engineer2.is_role_enabled("traffic_spotter") is True


def test_individual_roles_disabled_behavior():
    """Vérifie que les rôles désactivés ne déclenchent aucun son ni alerte."""
    from isimotor_rawudp_client import FullScoringSession, VehicleScoring, TelemVect3, CompactScoring
    from simpulse.builtin_plugins.race_engineer.subplugins.lap_validity import LapValidityRole
    from simpulse.builtin_plugins.race_engineer.subplugins.traffic_spotter import TrafficSpotterRole
    from simpulse.builtin_plugins.race_engineer.subplugins.traffic_jam import TrafficJamRole
    from simpulse.builtin_plugins.race_engineer.subplugins.pace_notes import PaceNotesRole

    played = []
    def mock_audio(phrase_key, interrupt=False):
        played.append(phrase_key)

    # 1. Lap Validity désactivé
    lap_slot = RoleHostSlot(role=LapValidityRole(audio_engine=mock_audio), enabled=False)
    assert lap_slot.status == RoleStatus.IDLE
    ctx_clean = EngineerContext(scoring=CompactScoring(count_lap_flag=2))
    assert lap_slot.update(ctx_clean) is None
    assert len(played) == 0

    # 2. Traffic Spotter désactivé
    spotter_slot = RoleHostSlot(role=TrafficSpotterRole(audio_engine=mock_audio), enabled=False)
    assert spotter_slot.status == RoleStatus.IDLE
    scoring_threat = FullScoringSession(
        lap_dist=5000.0,
        vehicles=[
            VehicleScoring(id=1, is_player=True, lap_dist=500.0, local_vel=TelemVect3(0.0, 0.0, 50.0)),
            VehicleScoring(id=2, is_player=False, control=1, lap_dist=460.0, local_vel=TelemVect3(0.0, 0.0, 60.0)),
        ],
    )
    assert spotter_slot.update(EngineerContext(scoring=scoring_threat)) is None
    assert spotter_slot.status == RoleStatus.IDLE
    assert len(played) == 0

    # 3. Traffic Jam désactivé
    jam_slot = RoleHostSlot(role=TrafficJamRole(audio_engine=mock_audio), enabled=False)
    assert jam_slot.status == RoleStatus.IDLE
    scoring_slow = FullScoringSession(
        lap_dist=5000.0,
        vehicles=[
            VehicleScoring(id=1, is_player=True, lap_dist=500.0, local_vel=TelemVect3(0.0, 0.0, 50.0)),
            VehicleScoring(id=2, is_player=False, control=1, lap_dist=540.0, local_vel=TelemVect3(0.0, 0.0, 5.0)),
        ],
    )
    assert jam_slot.update(EngineerContext(scoring=scoring_slow)) is None
    assert jam_slot.status == RoleStatus.IDLE
    assert len(played) == 0

    # 4. Pace Notes désactivé
    pace_slot = RoleHostSlot(role=PaceNotesRole(audio_engine=mock_audio), enabled=False)
    assert pace_slot.status == RoleStatus.IDLE
    assert pace_slot.update(EngineerContext(scoring=scoring_threat)) is None
    assert len(played) == 0

