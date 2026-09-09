"""
SimPulse SDK — Fuel/Energy & Session Gauge Packet.
Same dispatch shape as LapDeltaPacket (simpulse_sdk/models/delta.py): one
strongly-typed, immutable packet built once per physics tick, pushed into
TelemetryStateStore (single source of truth — TelemetryView.energy) and
emitted as a push signal (TelemetryBus.energy_updated), instead of every
consumer re-deriving or polling FuelEnergyEngine/session_energy_gauge itself.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class EnergyPacket:
    """
    Strongly-typed data packet representing authoritative fuel/energy
    consumption and session-completion projections. Dispatched to all
    plugins/UI components the same way LapDeltaPacket is — built by
    TelemetryBus._apply_fuel_fields() from FuelEnergyEngine (per-lap medians)
    and session_energy_gauge.compute_session_energy_gauge() (session-length
    projection).
    """

    # Instantaneous level + unit — mirrors VehicleSensors.fuel_level/.energy_is_percentage.
    level: float = 0.0
    is_percentage: bool = False  # True: Hypercar virtual-energy % (0-100); False: raw fuel liters

    # FuelEnergyEngine's medians over its last-64-laps history (persisted —
    # see ref_<track>_<car>.energy.json), never a best/PB time — see its
    # docstring for why a median is the deliberate choice here.
    consumption_per_lap: float = 0.0
    lap_time_median: float = 0.0
    projected_laps: float = 0.0  # level / consumption_per_lap — laps the tank can still do

    # session_energy_gauge's "will this last to the end of the session?" —
    # every field below is None until the session's length is knowable (no
    # lap limit AND no resolved end time yet, e.g. practice/warmup) — see
    # SessionEnergyGaugeResult's docstring.
    session_time_ratio: Optional[float] = None
    session_lap_ratio: Optional[float] = None
    session_laps_left: Optional[float] = None
    session_energy_needed: Optional[float] = None
    session_energy_ratio: Optional[float] = None  # >= 1.0 -> enough to finish

    # Raw figures backing the two ratios above, for display ("12:34 / 45:00",
    # "8 / 20") — session_time_total/session_laps_total are None exactly
    # when session_time_ratio/session_lap_ratio are.
    session_time_elapsed: float = 0.0
    session_time_total: Optional[float] = None
    session_laps_done: int = 0
    session_laps_total: Optional[int] = None

    # FuelEnergyEngine.has_insufficient_fuel_anomaly(): not enough energy to
    # finish the session AND the tank isn't topped up — see its docstring for
    # why that combination (not just session_energy_ratio < 1.0 alone) is
    # what actually deserves a driver's attention.
    fuel_anomaly: bool = False

    track_name: str = ""
    vehicle_class: str = ""
    vehicle_name: str = ""
    timestamp: float = field(default_factory=time.time)
