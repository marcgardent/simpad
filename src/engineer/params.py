"""
SimPad Race Engineer — Paramètres Configurables Déclaratifs pour les Rôles.
Fournit les descripteurs de types pour les paramètres de rôles (BoolParam, IntRangeParam, FloatRangeParam).
Architecture SOLID (SRP, OCP, LSP).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, Dict, List


@dataclass
class RoleParam(ABC):
    """
    Descripteur abstrait d'un paramètre configurable d'un rôle.
    Chaque paramètre possède un identifiant unique (name), un libellé (label),
    une description textuelle (description) et une valeur par défaut.
    """
    name: str
    label: str
    description: str = ""
    default: Any = None

    @abstractmethod
    def cast_and_validate(self, value: Any) -> Any:
        """Convertit et borne la valeur selon les contraintes du descripteur."""
        pass


@dataclass
class BoolParam(RoleParam):
    """Paramètre booléen (rendu sous forme de case à cocher Checkbox dans l'IHM)."""
    default: bool = True

    def cast_and_validate(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)


@dataclass
class IntRangeParam(RoleParam):
    """Paramètre entier avec plage bornée (min, max, step, unité) pour curseur/slider."""
    min_val: int = 0
    max_val: int = 100
    step: int = 1
    unit: str = ""
    default: int = 0

    def cast_and_validate(self, value: Any) -> int:
        try:
            val_int = int(round(float(value)))
            return max(self.min_val, min(self.max_val, val_int))
        except (ValueError, TypeError):
            return self.default


@dataclass
class FloatRangeParam(RoleParam):
    """Paramètre flottant avec plage bornée (min, max, step, unité) pour curseur/slider."""
    min_val: float = 0.0
    max_val: float = 100.0
    step: float = 0.1
    unit: str = ""
    default: float = 0.0

    def cast_and_validate(self, value: Any) -> float:
        try:
            val_flt = float(value)
            val_rounded = round(val_flt, 3)
            return max(self.min_val, min(self.max_val, val_rounded))
        except (ValueError, TypeError):
            return self.default
