"""
SimPad Race Engineer — Coordinateur Principal de l'Ingénieur de Course (RaceEngineer).
Gère la collection ordonnée des Rôles, leur cycle de vie, la priorisation,
l'arbitrage des messages audio et l'état global IDLE/BUSY.
"""

import time
import logging
from typing import List, Dict, Optional, Any
from src.engineer.base import BaseRole, EngineerMessage, RoleStatus
from src.engineer.context import EngineerContext
from src.engineer.factory import RoleFactory
from src.telemetry.lmu_parser import TelemetryData
from src.utils.audio import AudioAnnouncer

logger = logging.getLogger(__name__)


class RaceEngineer:
    """
    Coordinateur principal de l'ingénieur de course virtuel.
    Gère l'exécution des rôles par priorité décroissante, l'arbitrage sonore et l'état global.
    """

    def __init__(
        self,
        audio_engine: Optional[Any] = None,
        auto_load_builtin_roles: bool = True,
    ):
        self.enabled: bool = True
        self.audio_engine = audio_engine if audio_engine is not None else AudioAnnouncer
        self._roles: List[BaseRole] = []
        self._last_processed_time: float = 0.0

        if auto_load_builtin_roles:
            self._roles = RoleFactory.create_all_roles(audio_engine=self.audio_engine)
            self._sort_roles()

    def _sort_roles(self) -> None:
        """Trie la liste des rôles par priorité décroissante."""
        self._roles.sort(key=lambda r: r.priority, reverse=True)

    def get_roles(self) -> List[BaseRole]:
        """Retourne la liste des rôles ordonnée par priorité."""
        return list(self._roles)

    def get_role(self, role_id: str) -> Optional[BaseRole]:
        """Recherche un rôle par son identifiant."""
        for r in self._roles:
            if r.role_id == role_id:
                return r
        return None

    def add_role(self, role: BaseRole) -> None:
        """Ajoute un rôle personnalisé et réordonne par priorité."""
        # Remplacer si déjà présent
        self._roles = [r for r in self._roles if r.role_id != role.role_id]
        role.audio_engine = self.audio_engine
        self._roles.append(role)
        self._sort_roles()

    def remove_role(self, role_id: str) -> bool:
        """Retire un rôle de l'ingénieur."""
        before = len(self._roles)
        self._roles = [r for r in self._roles if r.role_id != role_id]
        return len(self._roles) < before

    def set_role_enabled(self, role_id: str, enabled: bool) -> None:
        """Active ou désactive un rôle spécifique."""
        role = self.get_role(role_id)
        if role:
            role.enabled = enabled
            if not enabled:
                role.reset()

    def move_role_up(self, role_id: str) -> bool:
        """
        Augmente la priorité d'un rôle en l'échangeant avec le rôle au-dessus.
        """
        for i, r in enumerate(self._roles):
            if r.role_id == role_id and i > 0:
                # Échange des priorités
                prev_role = self._roles[i - 1]
                # Garantir une différence de priorité stricte
                if r.priority <= prev_role.priority:
                    new_prio = prev_role.priority + 10
                    r.priority = new_prio
                else:
                    r.priority, prev_role.priority = prev_role.priority, r.priority

                self._sort_roles()
                return True
        return False

    def move_role_down(self, role_id: str) -> bool:
        """
        Diminue la priorité d'un rôle en l'échangeant avec le rôle en-dessous.
        """
        for i, r in enumerate(self._roles):
            if r.role_id == role_id and i < len(self._roles) - 1:
                next_role = self._roles[i + 1]
                if r.priority >= next_role.priority:
                    new_prio = max(0, next_role.priority - 10)
                    r.priority = new_prio
                else:
                    r.priority, next_role.priority = next_role.priority, r.priority

                self._sort_roles()
                return True
        return False

    def reorder_roles(self, ordered_role_ids: List[str]) -> None:
        """
        Réassigne les priorités de l'ensemble des rôles selon l'ordre fourni.
        Le premier élément recevra la priorité la plus haute (ex: 100, 90, 80...).
        """
        base_priority = max(100, len(ordered_role_ids) * 10)
        for index, r_id in enumerate(ordered_role_ids):
            role = self.get_role(r_id)
            if role:
                role.priority = base_priority - (index * 10)
        self._sort_roles()

    def is_any_role_busy(self) -> bool:
        """Indique si au moins un rôle actif est actuellement en état BUSY."""
        return any(r.enabled and r.is_busy() for r in self._roles)

    def get_busy_roles(self) -> List[BaseRole]:
        """Retourne la liste des rôles actuellement occupés."""
        return [r for r in self._roles if r.enabled and r.is_busy()]

    def update(
        self,
        telemetry: Optional[TelemetryData] = None,
        scoring: Optional[Dict[str, Any]] = None,
    ) -> List[EngineerMessage]:
        """
        Cycle d'évaluation principal : transmet le contexte à chaque rôle dans l'ordre de priorité.
        """
        if not self.enabled:
            return []

        now = time.time()
        self._last_processed_time = now

        context = EngineerContext(
            telemetry=telemetry,
            scoring=scoring,
            timestamp=now,
            audio_engine=self.audio_engine,
        )

        emitted_messages: List[EngineerMessage] = []

        # Évaluation dans l'ordre strict des priorités
        for role in self._roles:
            if not role.enabled:
                continue

            try:
                msg = role.update(context)
                if msg:
                    emitted_messages.append(msg)
            except Exception as e:
                logger.error(f"[RaceEngineer] Erreur lors de l'exécution du rôle '{role.role_id}': {e}", exc_info=True)

        return emitted_messages

    def reset_all(self) -> None:
        """Réinitialise tous les rôles."""
        for role in self._roles:
            role.reset()

    def get_status_summary(self) -> Dict[str, Any]:
        """Retourne un état complet pour l'IHM."""
        busy_roles = [r.role_id for r in self._roles if r.enabled and r.is_busy()]
        return {
            "enabled": self.enabled,
            "is_busy": len(busy_roles) > 0,
            "busy_roles": busy_roles,
            "roles": [r.get_state_summary() for r in self._roles],
        }

    def save_configuration(self) -> Dict[str, Any]:
        """Exporte la configuration des rôles (activations, priorités, paramètres)."""
        return {
            "enabled": self.enabled,
            "roles": {
                r.role_id: r.get_config()
                for r in self._roles
            },
            "order": [r.role_id for r in self._roles],
        }

    def load_configuration(self, config: Dict[str, Any]) -> None:
        """Restaure une configuration exportée."""
        if "enabled" in config:
            self.enabled = bool(config["enabled"])

        roles_config = config.get("roles", {})
        for role_id, r_cfg in roles_config.items():
            role = self.get_role(role_id)
            if role and isinstance(r_cfg, dict):
                role.set_config(r_cfg)

        order = config.get("order")
        if order and isinstance(order, list):
            self.reorder_roles(order)
        else:
            self._sort_roles()
