"""
SimPad Race Engineer — Abstractions de base pour les Rôles de l'Ingénieur de Course.
Architecture SOLID, modulaire et extensible.
"""

from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass, field
import time
from typing import Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.engineer.context import EngineerContext


class RoleStatus(str, Enum):
    """État d'activité d'un rôle de l'ingénieur de course."""
    IDLE = "IDLE"      # Rôle en veille / inactif / aucune alerte
    BUSY = "BUSY"      # Rôle actif / en cours d'annonce / séquence critique


@dataclass
class EngineerMessage:
    """Message audio / vocal émis par un rôle."""
    phrase_key: str
    priority: int = 50
    interrupt: bool = False
    text_override: Optional[str] = None
    role_id: str = ""
    timestamp: float = field(default_factory=time.time)


class BaseRole(ABC):
    """
    Classe abstraite de base pour tous les rôles de l'ingénieur de course.
    Chaque rôle a une responsabilité unique (Clean/Dirty lap, Traffic spotter, etc.),
    une priorité configurable, et indique s'il est IDLE ou BUSY.
    """

    def __init__(
        self,
        role_id: str,
        name: str,
        description: str = "",
        priority: int = 50,
        enabled: bool = True,
        audio_engine: Optional[Any] = None,
    ):
        self.role_id = role_id
        self.name = name
        self.description = description
        self.priority = priority
        self.enabled = enabled
        self.audio_engine = audio_engine

    @property
    def status(self) -> RoleStatus:
        """Retourne l'état d'activité courant du rôle (IDLE ou BUSY)."""
        return RoleStatus.BUSY if self.is_busy() else RoleStatus.IDLE

    @abstractmethod
    def is_busy(self) -> bool:
        """Indique si le rôle est actuellement engagé dans une séquence active ou critique."""
        pass

    @abstractmethod
    def update(self, context: "EngineerContext") -> Optional[EngineerMessage]:
        """
        Évalue les données télémétriques et scoring à chaque tick.
        Retourne un message s'il doit être prononcé, ou None.
        """
        pass

    def reset(self) -> None:
        """Réinitialise l'état interne du rôle."""
        pass

    def get_state_summary(self) -> Dict[str, Any]:
        """Retourne un résumé d'état sérialisable pour l'interface graphique (IHM) et le debug."""
        return {
            "role_id": self.role_id,
            "name": self.name,
            "status": self.status.value,
            "enabled": self.enabled,
            "priority": self.priority,
        }

    def get_config(self) -> Dict[str, Any]:
        """Retourne les paramètres configurables du rôle pour sauvegarde."""
        return {
            "enabled": self.enabled,
            "priority": self.priority,
        }

    def set_config(self, config: Dict[str, Any]) -> None:
        """Applique une configuration externe."""
        if "enabled" in config:
            self.enabled = bool(config["enabled"])
        if "priority" in config:
            self.priority = int(config["priority"])

    def emit_sound(self, phrase_key: str, interrupt: bool = False) -> None:
        """Joue un son via l'audio engine injecté s'il est configuré."""
        if self.audio_engine:
            if hasattr(self.audio_engine, "play_phrase"):
                self.audio_engine.play_phrase(phrase_key, interrupt=interrupt)
            elif callable(self.audio_engine):
                self.audio_engine(phrase_key, interrupt=interrupt)
