"""
SimPad Haptics — Subplugin Manager & Multi-Channel Mixer.
Coordinates active haptic subplugins, orchestrates real-time evaluation, and mixes multichannel outputs.
"""

from __future__ import annotations
import logging
from typing import Dict, List, Optional
from .models import HapticMotorOutput
from .subplugins.base import BaseHapticSubplugin
from .subplugins import get_default_subplugins
from ..telemetry.sensors import VehicleSensors

logger = logging.getLogger("simpad.haptics.manager")


class HapticSubpluginManager:
    """
    Manager for modular haptic subplugins.
    Dispatches telemetry frames to active subplugins and aggregates motor rumble intensities.
    """

    def __init__(self, subplugins: Optional[List[BaseHapticSubplugin]] = None):
        self._subplugins: Dict[str, BaseHapticSubplugin] = {}
        self._subplugin_order: List[str] = []

        initial = subplugins if subplugins is not None else get_default_subplugins()
        for sp in initial:
            self.register_subplugin(sp)

    def register_subplugin(self, subplugin: BaseHapticSubplugin) -> None:
        """Registers a subplugin in the manager."""
        pid = subplugin.subplugin_id
        if pid not in self._subplugins:
            self._subplugin_order.append(pid)
        self._subplugins[pid] = subplugin

    def get_subplugin(self, subplugin_id: str) -> Optional[BaseHapticSubplugin]:
        """Returns a registered subplugin by ID."""
        return self._subplugins.get(subplugin_id)

    def get_all_subplugins(self) -> List[BaseHapticSubplugin]:
        """Returns all registered subplugins in user order."""
        return [self._subplugins[pid] for pid in self._subplugin_order if pid in self._subplugins]

    def set_subplugin_enabled(self, subplugin_id: str, enabled: bool) -> bool:
        """Enables or disables a subplugin."""
        sp = self.get_subplugin(subplugin_id)
        if sp:
            sp.enabled = enabled
            return True
        return False

    def is_subplugin_enabled(self, subplugin_id: str) -> bool:
        """Returns True if the subplugin is registered and enabled."""
        sp = self.get_subplugin(subplugin_id)
        return sp.enabled if sp else False

    def evaluate(self, sensors: VehicleSensors, time_s: float) -> HapticMotorOutput:
        """
        Evaluates current vehicle telemetry across all active subplugins and mixes outputs.
        Uses MAX combination across active effects so peak sensation is always preserved.
        """
        combined = HapticMotorOutput()
        for pid in self._subplugin_order:
            sp = self._subplugins.get(pid)
            if sp and sp.enabled:
                try:
                    out = sp.evaluate(sensors, time_s)
                    combined = combined.combine_max(out)
                except Exception as e:
                    logger.warning(f"Error evaluating haptic subplugin '{pid}': {e}")

        return combined

    def get_config_dict(self) -> Dict[str, object]:
        """Serializes all subplugin configurations."""
        return {
            "order": list(self._subplugin_order),
            "subplugins": {
                pid: sp.get_config_dict() for pid, sp in self._subplugins.items()
            }
        }

    def load_config_dict(self, cfg: Dict[str, object]) -> None:
        """Applies saved configuration to all registered subplugins."""
        if not isinstance(cfg, dict):
            return

        order = cfg.get("order", [])
        if isinstance(order, list) and order:
            new_order = [pid for pid in order if pid in self._subplugins]
            for pid in self._subplugin_order:
                if pid not in new_order:
                    new_order.append(pid)
            self._subplugin_order = new_order

        subplugins_cfg = cfg.get("subplugins", {})
        if isinstance(subplugins_cfg, dict):
            for pid, sp_cfg in subplugins_cfg.items():
                sp = self._subplugins.get(pid)
                if sp and isinstance(sp_cfg, dict):
                    sp.load_config_dict(sp_cfg)
