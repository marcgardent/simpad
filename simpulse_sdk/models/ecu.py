"""
SimPulse SDK — ECU Domain Models (LMU Electronics & Cockpit Data).

Replaces the historical LmuTelemetryData flat bag (18 same-prefixed ecu_* fields,
itself duplicated a second time as flat ecu_* fields directly on VehicleSensors —
two copies of the same 18 values) with one composite split by business domain:
anti-lock, traction control, powertrain, chassis balance, cockpit.

T-A of the VehicleSensors remodel: pure, standalone models. Neither
VehicleSensors nor LmuTelemetryData is touched by this module yet — a later
ticket makes VehicleSensors.ecu: VehicleECU the single source of truth and turns
both the flat ecu_* fields and LmuTelemetryData into compat shims delegating here.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AntiLockECU:
    """ABS: activation + level relative to its car-defined max."""
    active_raw: Optional[bool] = None
    level: int = 0
    level_max: int = 0

    @property
    def is_engaged(self) -> bool:
        return bool(self.active_raw)

    @property
    def level_fraction(self) -> float:
        return (self.level / self.level_max) if self.level_max > 0 else 0.0


@dataclass(frozen=True)
class TractionControlECU:
    """TC: activation, level, cut strength and slip target, each with its max."""
    active_raw: Optional[bool] = None
    level: int = 0
    level_max: int = 0
    cut: int = 0
    cut_max: int = 0
    slip: int = 0
    slip_max: int = 0

    @property
    def is_engaged(self) -> bool:
        return bool(self.active_raw)

    @property
    def level_fraction(self) -> float:
        return (self.level / self.level_max) if self.level_max > 0 else 0.0


@dataclass(frozen=True)
class PowertrainECU:
    """Engine map selection and lift-and-coast (fuel-saving) setting."""
    motor_map: int = 0
    motor_map_max: int = 0
    lift_and_coast: float = 0.0


@dataclass(frozen=True)
class ChassisECU:
    """Driver-adjustable chassis balance: brake bias migration and anti-roll bars."""
    brake_migration: int = 0
    brake_migration_max: int = 0
    front_arb: int = 0
    front_arb_max: int = 0
    rear_arb: int = 0
    rear_arb_max: int = 0


@dataclass(frozen=True)
class CockpitECU:
    """Cockpit switches not owned by another ECU domain."""
    wiper_state: int = 0


@dataclass(frozen=True)
class VehicleECU:
    """
    Composite of every LMU electronic/cockpit sub-system, split by business
    domain instead of one flat ecu_* bag. Optional as a whole: absent (None)
    on non-LMU telemetry sources, same as the legacy LmuTelemetryData it replaces.
    """
    abs: AntiLockECU = AntiLockECU()
    tc: TractionControlECU = TractionControlECU()
    powertrain: PowertrainECU = PowertrainECU()
    chassis: ChassisECU = ChassisECU()
    cockpit: CockpitECU = CockpitECU()
