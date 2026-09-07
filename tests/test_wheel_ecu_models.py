"""
Unit Tests for the composite WheelSet/TireCorner and VehicleECU domain models
(T-A of the VehicleSensors "flat bag" remodel — see simpulse_sdk/models/wheels.py
and simpulse_sdk/models/ecu.py). These models are standalone at this stage:
VehicleSensors does not consume them yet.
"""

import unittest

from simpulse_sdk.models.wheels import (
    ALL_WHEEL_POSITIONS,
    TireCorner,
    WheelPosition,
    WheelSet,
)
from simpulse_sdk.models.ecu import (
    AntiLockECU,
    ChassisECU,
    CockpitECU,
    PowertrainECU,
    TractionControlECU,
    VehicleECU,
)


class TestWheelPosition(unittest.TestCase):
    def test_axle_membership(self):
        self.assertTrue(WheelPosition.FRONT_LEFT.is_front)
        self.assertTrue(WheelPosition.FRONT_RIGHT.is_front)
        self.assertFalse(WheelPosition.REAR_LEFT.is_front)
        self.assertTrue(WheelPosition.REAR_RIGHT.is_rear)

    def test_side_membership(self):
        self.assertTrue(WheelPosition.FRONT_LEFT.is_left)
        self.assertTrue(WheelPosition.REAR_LEFT.is_left)
        self.assertFalse(WheelPosition.FRONT_RIGHT.is_left)
        self.assertTrue(WheelPosition.REAR_RIGHT.is_right)

    def test_str_is_plain_value(self):
        self.assertEqual(str(WheelPosition.FRONT_LEFT), "front_left")

    def test_all_wheel_positions_order_matches_fl_fr_rl_rr(self):
        self.assertEqual(
            ALL_WHEEL_POSITIONS,
            (
                WheelPosition.FRONT_LEFT,
                WheelPosition.FRONT_RIGHT,
                WheelPosition.REAR_LEFT,
                WheelPosition.REAR_RIGHT,
            ),
        )


class TestWheelSet(unittest.TestCase):
    def setUp(self):
        self.wheels = WheelSet.from_tuples(
            locks=(0.1, 0.2, 0.3, 0.4),
            spins=(0.0, 0.0, 0.5, 0.6),
            grips=(1.0, 0.9, 0.8, 0.7),
        )

    def test_getitem_by_position(self):
        self.assertEqual(self.wheels[WheelPosition.FRONT_LEFT].lock, 0.1)
        self.assertEqual(self.wheels[WheelPosition.REAR_RIGHT].grip, 0.7)

    def test_iteration_yields_four_corners_in_fl_fr_rl_rr_order(self):
        locks = [corner.lock for corner in self.wheels]
        self.assertEqual(locks, [0.1, 0.2, 0.3, 0.4])

    def test_front_rear_left_right_groupings(self):
        self.assertEqual(self.wheels.front, (self.wheels.front_left, self.wheels.front_right))
        self.assertEqual(self.wheels.rear, (self.wheels.rear_left, self.wheels.rear_right))
        self.assertEqual(self.wheels.left, (self.wheels.front_left, self.wheels.rear_left))
        self.assertEqual(self.wheels.right, (self.wheels.front_right, self.wheels.rear_right))

    def test_axle_avg_grip(self):
        self.assertAlmostEqual(self.wheels.axle_avg_grip(front=True), (1.0 + 0.9) / 2.0)
        self.assertAlmostEqual(self.wheels.axle_avg_grip(front=False), (0.8 + 0.7) / 2.0)

    def test_axle_avg_spin_rear_only_engaged(self):
        self.assertAlmostEqual(self.wheels.axle_avg_spin(front=True), 0.0)
        self.assertAlmostEqual(self.wheels.axle_avg_spin(front=False), (0.5 + 0.6) / 2.0)

    def test_side_avg_grip(self):
        self.assertAlmostEqual(self.wheels.side_avg_grip(left=True), (1.0 + 0.8) / 2.0)
        self.assertAlmostEqual(self.wheels.side_avg_grip(left=False), (0.9 + 0.7) / 2.0)

    def test_default_wheelset_is_full_grip_no_slip(self):
        default = WheelSet()
        for corner in default:
            self.assertEqual(corner.lock, 0.0)
            self.assertEqual(corner.spin, 0.0)
            self.assertEqual(corner.grip, 1.0)

    def test_frozen_corner_is_immutable(self):
        corner = TireCorner(grip=0.5)
        with self.assertRaises(Exception):
            corner.grip = 0.9  # type: ignore[misc]


class TestVehicleECU(unittest.TestCase):
    def test_defaults_are_disengaged(self):
        ecu = VehicleECU()
        self.assertFalse(ecu.abs.is_engaged)
        self.assertFalse(ecu.tc.is_engaged)
        self.assertEqual(ecu.powertrain.motor_map, 0)
        self.assertEqual(ecu.chassis.front_arb, 0)
        self.assertEqual(ecu.cockpit.wiper_state, 0)

    def test_abs_level_fraction(self):
        abs_ecu = AntiLockECU(active_raw=True, level=3, level_max=6)
        self.assertTrue(abs_ecu.is_engaged)
        self.assertAlmostEqual(abs_ecu.level_fraction, 0.5)

    def test_abs_level_fraction_zero_max_is_zero_not_divide_by_zero(self):
        abs_ecu = AntiLockECU(level=3, level_max=0)
        self.assertEqual(abs_ecu.level_fraction, 0.0)

    def test_tc_level_fraction(self):
        tc = TractionControlECU(active_raw=True, level=2, level_max=8, cut=1, cut_max=4, slip=5, slip_max=10)
        self.assertTrue(tc.is_engaged)
        self.assertAlmostEqual(tc.level_fraction, 0.25)

    def test_composite_holds_independent_domains(self):
        ecu = VehicleECU(
            abs=AntiLockECU(active_raw=True, level=1, level_max=2),
            tc=TractionControlECU(active_raw=False, level=0, level_max=2),
            powertrain=PowertrainECU(motor_map=3, motor_map_max=6, lift_and_coast=0.2),
            chassis=ChassisECU(brake_migration=5, brake_migration_max=10, front_arb=1, front_arb_max=3, rear_arb=2, rear_arb_max=3),
            cockpit=CockpitECU(wiper_state=1),
        )
        self.assertTrue(ecu.abs.is_engaged)
        self.assertFalse(ecu.tc.is_engaged)
        self.assertEqual(ecu.powertrain.lift_and_coast, 0.2)
        self.assertEqual(ecu.chassis.rear_arb, 2)
        self.assertEqual(ecu.cockpit.wiper_state, 1)


if __name__ == "__main__":
    unittest.main()
