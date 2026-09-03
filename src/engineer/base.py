"""
SimPad Race Engineer — Abstractions de base pour les Rôles de l'Ingénieur de Course.
Architecture SOLID, modulaire et extensible.
"""

from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass, field
import time
from typing import Optional, Dict, Any, List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from src.engineer.context import EngineerContext

try:
    from simpad_qt.core.telemetry_channels import ChannelRequirement, TelemetryChannel
except ImportError:
    ChannelRequirement = Any
    TelemetryChannel = Any


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
    Classe abstraite de base pour tous les sous-plugins / rôles de l'ingénieur de course.
    Chaque rôle :
    - a une responsabilité unique (Clean/Dirty lap, Traffic spotter, etc.),
    - déclare ses besoins d'abonnement télémétrie (ChannelRequirement),
    - déclare les sons/phrases vocales nécessaires à son fonctionnement,
    - a une priorité configurable et indique son état IDLE ou BUSY.
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
        if not self.enabled:
            return RoleStatus.IDLE
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

    def get_channel_requirements(self) -> List[Any]:
        """
        Déclare les canaux de télémétrie et fréquences préférées requises par ce sous-plugin / rôle.
        Le plugin principal RaceEngineer agrège les besoins de tous ses sous-plugins.
        """
        return []

    def get_sound_requirements(self) -> Dict[str, str]:
        """
        Déclare le catalogue des sons / phrases vocales requis par ce sous-plugin (phrase_key -> texte à synthétiser).
        Le plugin principal RaceEngineer agrège les sons et gère leur génération/vérification.
        """
        return {}

    def reset(self) -> None:
        """Réinitialise l'état interne du rôle."""
        pass

    def get_parameters(self) -> List[Any]:
        """
        Retourne la liste déclarative des descripteurs de paramètres (RoleParam)
        propres à ce rôle (ex: BoolParam, IntRangeParam, FloatRangeParam).
        """
        return []

    def get_param_value(self, name: str) -> Any:
        """Retourne la valeur actuelle d'un paramètre nommé."""
        if hasattr(self, name):
            return getattr(self, name)
        for p in self.get_parameters():
            if p.name == name:
                return p.default
        return None

    def set_param_value(self, name: str, value: Any) -> None:
        """Définit la valeur d'un paramètre avec validation et typage."""
        for p in self.get_parameters():
            if p.name == name:
                valid_val = p.cast_and_validate(value)
                setattr(self, name, valid_val)
                return
        setattr(self, name, value)

    def get_state_summary(self) -> Dict[str, Any]:
        """Retourne un résumé d'état sérialisable pour l'interface graphique (IHM) et le debug."""
        summary = {
            "role_id": self.role_id,
            "name": self.name,
            "status": self.status.value,
            "enabled": self.enabled,
            "priority": self.priority,
        }
        for p in self.get_parameters():
            summary[p.name] = self.get_param_value(p.name)
        return summary

    def get_config(self) -> Dict[str, Any]:
        """Retourne les paramètres configurables du rôle pour sauvegarde."""
        cfg = {
            "enabled": self.enabled,
            "priority": self.priority,
        }
        for p in self.get_parameters():
            cfg[p.name] = self.get_param_value(p.name)
        return cfg

    def set_config(self, config: Dict[str, Any]) -> None:
        """Applique une configuration externe."""
        if "enabled" in config:
            self.enabled = bool(config["enabled"])
        if "priority" in config:
            self.priority = int(config["priority"])
        for p in self.get_parameters():
            if p.name in config:
                self.set_param_value(p.name, config[p.name])

    def emit_sound(self, phrase_key: str, interrupt: bool = False) -> None:
        """Joue un son via l'audio engine injecté s'il est configuré."""
        if self.audio_engine:
            if hasattr(self.audio_engine, "play_phrase"):
                self.audio_engine.play_phrase(phrase_key, interrupt=interrupt)
            elif callable(self.audio_engine):
                self.audio_engine(phrase_key, interrupt=interrupt)
