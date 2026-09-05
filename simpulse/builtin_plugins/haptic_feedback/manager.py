"""
SimPulse Haptics — Subplugin Manager & Multi-Channel Mixer.
Coordinates active haptic subplugin host slots, orchestrates real-time evaluation, and mixes multichannel outputs.
"""

from __future__ import annotations
import logging
from typing import Dict, List, Optional
from .models import HapticMotorOutput
from .subplugins.base import BaseHapticSubplugin, HapticHostSlot
from .subplugins import get_default_subplugins
from simpulse.core.telemetry.sensors import VehicleSensors

logger = logging.getLogger("simpulse.haptics.manager")

# Marc profile effects enabled by default
DEFAULT_ENABLED_SUBPLUGIN_IDS = {"marc_abs", "marc_tc", "marc_engine_shift"}


class HapticSubpluginManager:
    """
    Manager / Hoster for modular haptic subplugins.
    Owns HapticHostSlots that hold activation state (enabled) and intensity scaling (master_gain).
    Dispatches telemetry frames to active subplugins and aggregates motor rumble intensities.
    """

    def __init__(self, subplugins: Optional[List[BaseHapticSubplugin]] = None):
        self._slots: Dict[str, HapticHostSlot] = {}
        self._subplugin_order: List[str] = []

        initial = subplugins if subplugins is not None else get_default_subplugins()
        for sp in initial:
            default_enabled = sp.subplugin_id in DEFAULT_ENABLED_SUBPLUGIN_IDS
            self.register_subplugin(sp, enabled=default_enabled)

    def register_subplugin(
        self,
        subplugin: BaseHapticSubplugin,
        enabled: bool = True,
        master_gain: float = 1.0,
    ) -> None:
        """Registers a subplugin within a new or updated host slot."""
        pid = subplugin.subplugin_id
        if pid not in self._slots:
            self._subplugin_order.append(pid)
            self._slots[pid] = HapticHostSlot(
                subplugin=subplugin,
                enabled=enabled,
                master_gain=master_gain,
            )
        else:
            self._slots[pid].subplugin = subplugin
            self._slots[pid].enabled = enabled
            self._slots[pid].master_gain = master_gain

    def get_slot(self, subplugin_id: str) -> Optional[HapticHostSlot]:
        """Returns the host slot for a given subplugin ID."""
        return self._slots.get(subplugin_id)

    def get_all_slots(self) -> List[HapticHostSlot]:
        """Returns all host slots in user order."""
        return [self._slots[pid] for pid in self._subplugin_order if pid in self._slots]

    def get_subplugin(self, subplugin_id: str) -> Optional[BaseHapticSubplugin]:
        """Returns a registered subplugin by ID."""
        slot = self._slots.get(subplugin_id)
        return slot.subplugin if slot else None

    def get_all_subplugins(self) -> List[BaseHapticSubplugin]:
        """Returns all registered subplugins in user order."""
        return [self._slots[pid].subplugin for pid in self._subplugin_order if pid in self._slots]

    def set_subplugin_enabled(self, subplugin_id: str, enabled: bool) -> bool:
        """Enables or disables a subplugin host slot."""
        slot = self.get_slot(subplugin_id)
        if slot:
            slot.enabled = enabled
            return True
        return False

    def is_subplugin_enabled(self, subplugin_id: str) -> bool:
        """Returns True if the subplugin host slot is registered and enabled."""
        slot = self.get_slot(subplugin_id)
        return slot.enabled if slot else False

    def set_subplugin_gain(self, subplugin_id: str, gain: float) -> bool:
        """Sets the master gain on a subplugin host slot."""
        slot = self.get_slot(subplugin_id)
        if slot:
            slot.master_gain = max(0.0, min(5.0, float(gain)))
            return True
        return False

    def get_subplugin_gain(self, subplugin_id: str) -> float:
        """Gets the master gain for a subplugin host slot."""
        slot = self.get_slot(subplugin_id)
        return slot.master_gain if slot else 1.0

    def evaluate(self, sensors: VehicleSensors, time_s: float) -> HapticMotorOutput:
        """
        Evaluates current vehicle telemetry across all active subplugins and mixes outputs.
        Uses MAX combination across active effects so peak sensation is always preserved.
        """
        combined = HapticMotorOutput()
        for pid in self._subplugin_order:
            slot = self._slots.get(pid)
            if slot and slot.enabled:
                try:
                    out = slot.evaluate(sensors, time_s)
                    combined = combined.combine_max(out)
                except Exception as e:
                    logger.warning(f"Error evaluating haptic subplugin '{pid}': {e}")

        return combined

    def get_config_dict(self) -> Dict[str, object]:
        """Serializes all subplugin configurations."""
        return {
            "order": list(self._subplugin_order),
            "subplugins": {
                pid: slot.get_config_dict() for pid, slot in self._slots.items()
            }
        }

    def load_config_dict(self, cfg: Dict[str, object]) -> None:
        """Applies saved configuration to all registered subplugin host slots."""
        if not isinstance(cfg, dict):
            return

        order = cfg.get("order", [])
        if isinstance(order, list) and order:
            new_order = [pid for pid in order if pid in self._slots]
            for pid in self._subplugin_order:
                if pid not in new_order:
                    new_order.append(pid)
            self._subplugin_order = new_order

        subplugins_cfg = cfg.get("subplugins", {})
        if isinstance(subplugins_cfg, dict):
            for pid, sp_cfg in subplugins_cfg.items():
                slot = self._slots.get(pid)
                if slot and isinstance(sp_cfg, dict):
                    slot.load_config_dict(sp_cfg)
