"""Unit tests for resolve_fuel_or_energy_level (simpulse_sdk/models/telemetry.py)."""

import unittest

from isimotor_rawudp_client import TelemInfo
from isimotor_rawudp_client.models.lmu import LMUTelemetryExtension
from simpulse_sdk.models.telemetry import resolve_fuel_or_energy_level


class TestResolveFuelOrEnergyLevel(unittest.TestCase):
    def test_real_session_bug_gte_car_with_subnormal_virtual_energy_noise(self):
        """Real Fuji Speedway packet for a GTE car (not a Hypercar): fuel=
        73.6L, correctly populated, but virtual_energy=1.4854197949e-313 —
        leftover memory noise in the LMU expansion block, not a real
        reading. The library's own has_hypercar_energy (virtual_energy >
        0.0) is fooled by this; this must not be. The real, correctly
        populated fuel must win."""
        telem = TelemInfo(fuel=73.60673429379628, lmu=LMUTelemetryExtension(virtual_energy=1.4854197949e-313))
        level, is_percentage = resolve_fuel_or_energy_level(telem)
        self.assertFalse(is_percentage)
        self.assertAlmostEqual(level, 73.60673429379628)

    def test_no_lmu_extension_uses_raw_fuel(self):
        telem = TelemInfo(fuel=42.5, lmu=None)
        level, is_percentage = resolve_fuel_or_energy_level(telem)
        self.assertFalse(is_percentage)
        self.assertAlmostEqual(level, 42.5)

    def test_zero_virtual_energy_uses_raw_fuel(self):
        telem = TelemInfo(fuel=55.0, lmu=LMUTelemetryExtension(virtual_energy=0.0))
        level, is_percentage = resolve_fuel_or_energy_level(telem)
        self.assertFalse(is_percentage)
        self.assertAlmostEqual(level, 55.0)

    def test_real_hypercar_virtual_energy_is_used_as_percentage(self):
        """A genuine Hypercar reading (a real 0.0-1.0 fraction, e.g. 0.82 =
        82% remaining) must still resolve to the virtual-energy percentage,
        not fuel — the fix must not overcorrect into ignoring real Hypercar
        data."""
        telem = TelemInfo(fuel=0.3, lmu=LMUTelemetryExtension(virtual_energy=0.82))
        level, is_percentage = resolve_fuel_or_energy_level(telem)
        self.assertTrue(is_percentage)
        self.assertAlmostEqual(level, 82.0)

    def test_hypercar_virtual_energy_near_empty_still_resolves_as_percentage(self):
        """A Hypercar nearly out of energy (a small but genuine fraction,
        e.g. 0.001 = 0.1%) must still be treated as real — well above the
        noise threshold, must not be mistaken for garbage."""
        telem = TelemInfo(fuel=0.0, lmu=LMUTelemetryExtension(virtual_energy=0.001))
        level, is_percentage = resolve_fuel_or_energy_level(telem)
        self.assertTrue(is_percentage)
        self.assertAlmostEqual(level, 0.1)


if __name__ == "__main__":
    unittest.main()
