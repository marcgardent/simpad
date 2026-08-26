"""
SimPad Race Engineer — Coordinateur Principal de l'Ingénieur de Course (RaceEngineer).
Gère la collection ordonnée des Rôles, leur cycle de vie, la priorisation,
l'arbitrage des messages audio et l'état global IDLE/BUSY.
"""

import time
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any
from src.engineer.base import BaseRole, EngineerMessage, RoleStatus
from src.engineer.context import EngineerContext
from src.engineer.factory import RoleFactory
from src.telemetry.lmu_parser import TelemetryData
from src.utils.audio import AudioAnnouncer

logger = logging.getLogger(__name__)

DEFAULT_ENGINEER_CONFIG_PATH = Path("engineer_config.json")


class RaceEngineer:
    """
    Coordinateur principal de l'ingénieur de course virtuel.
    Gère l'exécution des rôles par priorité décroissante, l'arbitrage sonore et l'état global.
    """

    def __init__(
        self,
        audio_engine: Optional[Any] = None,
        auto_load_builtin_roles: bool = True,
        config_path: Optional[Path] = None,
        auto_load_config: bool = True,
    ):
        self.enabled: bool = True
        self.audio_engine = audio_engine if audio_engine is not None else AudioAnnouncer
        if config_path is None:
            self.config_path = DEFAULT_ENGINEER_CONFIG_PATH if auto_load_builtin_roles else None
        else:
            self.config_path = Path(config_path)
        self._roles: List[BaseRole] = []
        self._last_processed_time: float = 0.0

        if auto_load_builtin_roles:
            self._roles = RoleFactory.create_all_roles(audio_engine=self.audio_engine)
            if auto_load_config and self.config_path and self.config_path.exists():
                self.load_from_file(self.config_path)
            else:
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

    def set_role_enabled(self, role_id: str, enabled: bool, auto_save: bool = True) -> None:
        """Active ou désactive un rôle spécifique."""
        role = self.get_role(role_id)
        if role:
            role.enabled = enabled
            if not enabled:
                role.reset()
            if auto_save and self.config_path:
                self.save_to_file()

    def move_role_up(self, role_id: str, auto_save: bool = True) -> bool:
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
                if auto_save and self.config_path:
                    self.save_to_file()
                return True
        return False

    def move_role_down(self, role_id: str, auto_save: bool = True) -> bool:
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
                if auto_save and self.config_path:
                    self.save_to_file()
                return True
        return False

    def reorder_roles(self, ordered_role_ids: List[str], auto_save: bool = True) -> None:
        """
        Réassigne les priorités de l'ensemble des rôles selon l'ordre fourni.
        Le premier élément recevra la priorité la plus haute (ex: 100, 90, 80...).
        """
        base_priority = max(100, (len(ordered_role_ids) + len(self._roles)) * 10)
        for index, r_id in enumerate(ordered_role_ids):
            role = self.get_role(r_id)
            if role:
                role.priority = base_priority - (index * 10)
        self._sort_roles()
        if auto_save and self.config_path:
            self.save_to_file()

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

    def set_master_enabled(self, enabled: bool, auto_save: bool = True) -> None:
        """Active ou désactive globalement le Race Engineer."""
        self.enabled = enabled
        if auto_save and self.config_path:
            self.save_to_file()

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
            self.reorder_roles(order, auto_save=False)
        else:
            self._sort_roles()

    def save_to_file(self, filepath: Optional[Path] = None) -> bool:
        """Sauvegarde la configuration actuelle des rôles dans un fichier JSON."""
        target_path = filepath or self.config_path
        if not target_path:
            return False
        try:
            target_path = Path(target_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(self.save_configuration(), f, indent=2)
            logger.info(f"[RaceEngineer] Configuration sauvegardée dans '{target_path}'.")
            return True
        except Exception as e:
            logger.error(f"[RaceEngineer] Erreur lors de la sauvegarde dans '{target_path}': {e}")
            return False

    def load_from_file(self, filepath: Optional[Path] = None) -> bool:
        """Charge la configuration des rôles depuis un fichier JSON."""
        target_path = filepath or self.config_path
        if not target_path:
            return False
        target_path = Path(target_path)
        if not target_path.exists():
            return False
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            if isinstance(config, dict):
                self.load_configuration(config)
                logger.info(f"[RaceEngineer] Configuration chargée depuis '{target_path}'.")
                return True
            return False
        except Exception as e:
            logger.error(f"[RaceEngineer] Erreur lors du chargement de '{target_path}': {e}")
            return False
