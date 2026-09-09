"""Unit tests for session_energy_gauge.compute_session_energy_gauge()."""

import unittest

from simpulse.core.telemetry.session_energy_gauge import compute_session_energy_gauge


class TestSessionEnergyGauge(unittest.TestCase):
    def test_unlimited_session_yields_all_none(self):
        # Practice/warmup: no lap limit, no resolved end time.
        result = compute_session_energy_gauge(
            current_et=120.0, end_et=0.0, max_laps=0, total_laps=2,
            energy_level=50.0, median_consumption_per_lap=5.0, median_lap_time=100.0,
        )
        self.assertIsNone(result.time_ratio)
        self.assertIsNone(result.lap_ratio)
        self.assertIsNone(result.laps_left_in_session)
        self.assertIsNone(result.energy_needed_to_finish)
        self.assertIsNone(result.energy_ratio)

    def test_lap_limited_race(self):
        # 20-lap race, 8 done, 5L/lap median consumption.
        result = compute_session_energy_gauge(
            current_et=800.0, end_et=0.0, max_laps=20, total_laps=8,
            energy_level=50.0, median_consumption_per_lap=5.0, median_lap_time=100.0,
        )
        self.assertIsNone(result.time_ratio)
        self.assertAlmostEqual(result.lap_ratio, 8 / 20)
        self.assertAlmostEqual(result.laps_left_in_session, 12.0)
        self.assertAlmostEqual(result.energy_needed_to_finish, 60.0)  # 12 * 5
        self.assertAlmostEqual(result.energy_ratio, 50.0 / 60.0)  # not enough — < 1.0

    def test_time_limited_race(self):
        # 45-minute race, 800s elapsed, 100s/lap median.
        result = compute_session_energy_gauge(
            current_et=800.0, end_et=2700.0, max_laps=0, total_laps=8,
            energy_level=100.0, median_consumption_per_lap=5.0, median_lap_time=100.0,
        )
        self.assertAlmostEqual(result.time_ratio, 800.0 / 2700.0)
        self.assertIsNone(result.lap_ratio)
        # time_left = 1900s / 100s per lap = 19 laps (ceil)
        self.assertAlmostEqual(result.laps_left_in_session, 19.0)
        self.assertAlmostEqual(result.energy_needed_to_finish, 95.0)  # 19 * 5
        self.assertAlmostEqual(result.energy_ratio, 100.0 / 95.0)  # enough — > 1.0

    def test_mixed_limits_take_the_more_constraining_one(self):
        # "45 minutes or 10 laps, whichever comes first" — 8 laps done, only
        # 2 laps left by lap count, but ~9 laps' worth of time left: laps
        # (the tighter constraint) must win.
        result = compute_session_energy_gauge(
            current_et=800.0, end_et=2700.0, max_laps=10, total_laps=8,
            energy_level=100.0, median_consumption_per_lap=5.0, median_lap_time=100.0,
        )
        self.assertAlmostEqual(result.laps_left_in_session, 2.0)
        self.assertAlmostEqual(result.energy_needed_to_finish, 10.0)  # 2 * 5

    def test_mixed_limits_time_can_be_the_constraining_one(self):
        # Same mixed session, but now time is about to run out well before
        # the lap count would (e.g. a slow, incident-filled race).
        result = compute_session_energy_gauge(
            current_et=2650.0, end_et=2700.0, max_laps=50, total_laps=8,
            energy_level=100.0, median_consumption_per_lap=5.0, median_lap_time=100.0,
        )
        # time_left = 50s -> ceil(50/100) = 1 lap, vs 42 laps left by count.
        self.assertAlmostEqual(result.laps_left_in_session, 1.0)
        self.assertAlmostEqual(result.energy_needed_to_finish, 5.0)

    def test_no_energy_ratio_without_a_consumption_estimate_yet(self):
        result = compute_session_energy_gauge(
            current_et=800.0, end_et=0.0, max_laps=20, total_laps=8,
            energy_level=50.0, median_consumption_per_lap=0.0, median_lap_time=100.0,
        )
        self.assertAlmostEqual(result.lap_ratio, 8 / 20)
        self.assertIsNone(result.energy_needed_to_finish)
        self.assertIsNone(result.energy_ratio)

    def test_time_limited_without_a_lap_time_estimate_yet(self):
        # Time-limited session but FuelEnergyEngine hasn't completed a lap
        # yet this combo (median_lap_time == 0.0, e.g. lap 1 of a fresh
        # combo with no persisted history) — time_ratio is still known, but
        # laps_left_in_session can't be derived from time alone.
        result = compute_session_energy_gauge(
            current_et=100.0, end_et=2700.0, max_laps=0, total_laps=0,
            energy_level=100.0, median_consumption_per_lap=5.0, median_lap_time=0.0,
        )
        self.assertAlmostEqual(result.time_ratio, 100.0 / 2700.0)
        self.assertIsNone(result.laps_left_in_session)
        self.assertIsNone(result.energy_ratio)


class TestSessionEnergyGaugeRawFigures(unittest.TestCase):
    """time_elapsed/time_total/laps_done/laps_total — the raw numbers behind
    time_ratio/lap_ratio, for display ("12:34 / 45:00", "8 / 20")."""

    def test_lap_limited_carries_raw_laps_no_raw_time(self):
        result = compute_session_energy_gauge(
            current_et=800.0, end_et=0.0, max_laps=20, total_laps=8,
            energy_level=50.0, median_consumption_per_lap=5.0, median_lap_time=100.0,
        )
        self.assertEqual(result.laps_done, 8)
        self.assertEqual(result.laps_total, 20)
        self.assertEqual(result.time_elapsed, 800.0)
        self.assertIsNone(result.time_total)

    def test_time_limited_carries_raw_time_no_raw_laps_total(self):
        result = compute_session_energy_gauge(
            current_et=800.0, end_et=2700.0, max_laps=0, total_laps=8,
            energy_level=100.0, median_consumption_per_lap=5.0, median_lap_time=100.0,
        )
        self.assertEqual(result.time_elapsed, 800.0)
        self.assertEqual(result.time_total, 2700.0)
        self.assertEqual(result.laps_done, 8)
        self.assertIsNone(result.laps_total)

    def test_unlimited_session_still_carries_time_elapsed_and_laps_done(self):
        # Only the *_total figures are None when a limit is unknown — elapsed
        # time and laps done so far are always real, known numbers.
        result = compute_session_energy_gauge(
            current_et=120.0, end_et=0.0, max_laps=0, total_laps=2,
            energy_level=50.0, median_consumption_per_lap=5.0, median_lap_time=100.0,
        )
        self.assertEqual(result.time_elapsed, 120.0)
        self.assertEqual(result.laps_done, 2)
        self.assertIsNone(result.time_total)
        self.assertIsNone(result.laps_total)


if __name__ == "__main__":
    unittest.main()
