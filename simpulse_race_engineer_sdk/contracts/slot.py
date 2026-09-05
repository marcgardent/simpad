"""
SimPulse Race Engineer — Role Host Slot Contract.
Encapsulates host-side activation state (enabled) and evaluation dispatch
for a single BaseRole subplugin.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any, Union, List, TYPE_CHECKING
from .role import BaseRole
from ..models.message import EngineerMessage, RoleStatus

if TYPE_CHECKING:
    from ..models.context import EngineerContext


@dataclass
class RoleHostSlot:
    """
    Host-side slot managing activation state, execution dispatch,
    and configuration serialization for a single BaseRole instance.
    """
    role: BaseRole
    enabled: bool = True

    @property
    def role_id(self) -> str:
        return self.role.role_id

    @property
    def priority(self) -> int:
        return self.role.priority

    @priority.setter
    def priority(self, val: int) -> None:
        self.role.priority = val

    @property
    def status(self) -> RoleStatus:
        """Reports IDLE if disabled, otherwise delegates to role status."""
        if not self.enabled:
            return RoleStatus.IDLE
        return self.role.status

    def is_busy(self) -> bool:
        """Returns False if disabled, otherwise delegates to role."""
        if not self.enabled:
            return False
        return self.role.is_busy()

    def update(self, context: EngineerContext) -> Optional[EngineerMessage]:
        """Evaluates role if enabled, otherwise returns None."""
        if not self.enabled:
            return None
        return self.role.update(context)

    def reset(self) -> None:
        """Resets the hosted role state."""
        self.role.reset()

    def get_state_summary(self) -> Dict[str, Union[str, int, float, bool, List[str], None]]:
        """Returns serializable state summary including host slot activation state."""
        summary = self.role.get_state_summary()
        summary["enabled"] = self.enabled
        summary["status"] = self.status.value
        return summary

    def get_config(self) -> Dict[str, Any]:
        """Serializes slot configuration and role parameters."""
        cfg = self.role.get_config()
        cfg["enabled"] = self.enabled
        return cfg

    def set_config(self, config: Dict[str, Any]) -> None:
        """Restores slot configuration and role parameters."""
        if not isinstance(config, dict):
            return
        if "enabled" in config:
            self.enabled = bool(config["enabled"])
        self.role.set_config(config)


EngineerHostSlot = RoleHostSlot
SubpluginHostSlot = RoleHostSlot
