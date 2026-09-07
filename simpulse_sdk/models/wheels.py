"""
SimPulse SDK — Per-Corner Wheel Models.

Replaces the historical "flat bag" convention on VehicleSensors (front_left_lock,
front_right_lock, rear_left_lock, rear_right_lock, ... x6 quantities) with a real
composite: one TireCorner per wheel, addressed by WheelPosition, grouped in a
WheelSet that also knows how to answer axle/laterality questions (front/rear,
left/right averages) instead of every consumer re-deriving that by hand.

T-A of the VehicleSensors remodel: pure, standalone models. VehicleSensors itself
is untouched by this module — a later ticket adds a `wheels: WheelSet` field to it
and turns the legacy flat fields into compat properties delegating here.
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class WheelPosition(str, Enum):
    """The four wheel corners, isiMotor FL/FR/RL/RR convention."""
    FRONT_LEFT = "front_left"
    FRONT_RIGHT = "front_right"
    REAR_LEFT = "rear_left"
    REAR_RIGHT = "rear_right"

    def __str__(self) -> str:
        return self.value

    @property
    def is_front(self) -> bool:
        return self in (WheelPosition.FRONT_LEFT, WheelPosition.FRONT_RIGHT)

    @property
    def is_rear(self) -> bool:
        return not self.is_front

    @property
    def is_left(self) -> bool:
        return self in (WheelPosition.FRONT_LEFT, WheelPosition.REAR_LEFT)

    @property
    def is_right(self) -> bool:
        return not self.is_left


# Canonical iteration order, matching the isiMotor TelemWheel[4] wire layout
# (FL, FR, RL, RR) that from_wheel_velocities()/from_telem_info() already consume.
ALL_WHEEL_POSITIONS: Tuple[WheelPosition, ...] = (
    WheelPosition.FRONT_LEFT,
    WheelPosition.FRONT_RIGHT,
    WheelPosition.REAR_LEFT,
    WheelPosition.REAR_RIGHT,
)


@dataclass(frozen=True)
class TireCorner:
    """
    Dimensionless normalized sensor bundle for a single wheel corner (0.0 to 1.0
    unless noted). One instance replaces the 6 same-suffixed flat fields
    (front_left_lock, front_left_spin, front_left_lat_slip, front_left_lat_signed,
    front_left_travel, front_left_grip) that used to live directly on VehicleSensors.
    """

    # Longitudinal slip — braking / wheel lock
    lock: float = 0.0
    # Longitudinal slip — acceleration / TC spin
    spin: float = 0.0
    # Lateral slip — cornering / sliding [0.0 to 1.0]
    lat_slip: float = 0.0
    # Signed lateral slip, left (-1.0) / right (+1.0), for horizontal gauges
    lat_signed: float = 0.0
    # Suspension travel [0.0 to 1.0]
    travel: float = 0.0
    # Tire grip fraction [0.0 to 1.0]
    grip: float = 1.0


@dataclass(frozen=True)
class WheelSet:
    """
    The four TireCorner instances for a vehicle, plus axle/laterality aggregates.
    Deliberately named-field (not a bare 4-tuple) so `wheels.front_left.grip` reads
    the same as the legacy `sensors.front_left_grip` it replaces — only flattened
    one level instead of six.
    """

    front_left: TireCorner = TireCorner()
    front_right: TireCorner = TireCorner()
    rear_left: TireCorner = TireCorner()
    rear_right: TireCorner = TireCorner()

    def __getitem__(self, position: WheelPosition) -> TireCorner:
        return getattr(self, position.value)

    def __iter__(self):
        for position in ALL_WHEEL_POSITIONS:
            yield self[position]

    @property
    def front(self) -> Tuple[TireCorner, TireCorner]:
        return (self.front_left, self.front_right)

    @property
    def rear(self) -> Tuple[TireCorner, TireCorner]:
        return (self.rear_left, self.rear_right)

    @property
    def left(self) -> Tuple[TireCorner, TireCorner]:
        return (self.front_left, self.rear_left)

    @property
    def right(self) -> Tuple[TireCorner, TireCorner]:
        return (self.front_right, self.rear_right)

    @staticmethod
    def _avg(corners: Tuple[TireCorner, TireCorner], attr: str) -> float:
        return sum(getattr(c, attr) for c in corners) / 2.0

    def axle_avg_grip(self, front: bool) -> float:
        return self._avg(self.front if front else self.rear, "grip")

    def axle_avg_lock(self, front: bool) -> float:
        return self._avg(self.front if front else self.rear, "lock")

    def axle_avg_spin(self, front: bool) -> float:
        return self._avg(self.front if front else self.rear, "spin")

    def side_avg_grip(self, left: bool) -> float:
        return self._avg(self.left if left else self.right, "grip")

    @classmethod
    def from_tuples(
        cls,
        locks: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
        spins: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
        lat_slips: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
        lat_signed: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
        travels: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
        grips: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
    ) -> "WheelSet":
        """Builds a WheelSet from the legacy FL/FR/RL/RR-ordered flat tuples that
        from_wheel_velocities()'s internal per-wheel loop already produces — the
        bridge a later ticket uses to fill VehicleSensors.wheels without rewriting
        that loop's math."""
        corners = [
            TireCorner(
                lock=locks[i],
                spin=spins[i],
                lat_slip=lat_slips[i],
                lat_signed=lat_signed[i],
                travel=travels[i],
                grip=grips[i],
            )
            for i in range(4)
        ]
        return cls(
            front_left=corners[0],
            front_right=corners[1],
            rear_left=corners[2],
            rear_right=corners[3],
        )
