"""Unit tests for FuelEnergyEngine (simpulse/core/telemetry/fuel_engine.py)."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import simpulse.core.telemetry.delta_engine as delta_engine_module
from simpulse.core.telemetry.delta_engine import DeltaEngine
from simpulse.core.telemetry.fuel_engine import FuelEnergyEngine
from simpulse.core.telemetry_channels import TelemetryChannel


class TestFuelEnergyEngine(unittest.TestCase):
    def test_no_estimate_before_first_completed_lap(self):
        engine = FuelEnergyEngine()
        engine.update(level=80.0, total_laps=0)
        engine.update(level=75.0, total_laps=0)
        self.assertEqual(engine.estimated_consumption_per_lap, 0.0)
        self.assertEqual(engine.estimated_laps_remaining, 0.0)

    def test_records_consumption_on_lap_transition(self):
        engine = FuelEnergyEngine()
        engine.update(level=80.0, total_laps=0)   # lap 1 starts at 80
        engine.update(level=77.0, total_laps=0)   # still lap 1
        recorded = engine.update(level=75.0, total_laps=1)   # lap 1 -> lap 2, consumed 5
        self.assertTrue(recorded)
        self.assertAlmostEqual(engine.last_lap_consumption, 5.0)
        self.assertAlmostEqual(engine.estimated_consumption_per_lap, 5.0)
        self.assertAlmostEqual(engine.estimated_laps_remaining, 75.0 / 5.0)

    def test_update_returns_false_when_no_lap_transition(self):
        engine = FuelEnergyEngine()
        self.assertFalse(engine.update(level=80.0, total_laps=0))
        self.assertFalse(engine.update(level=77.0, total_laps=0))

    def test_projection_uses_rolling_median(self):
        engine = FuelEnergyEngine()
        levels_and_laps = [
            (100.0, 0),
            (95.0, 1),   # lap 0 consumed 5
            (89.0, 2),   # lap 1 consumed 6
            (84.0, 3),   # lap 2 consumed 5
        ]
        for level, laps in levels_and_laps:
            engine.update(level=level, total_laps=laps)
        # median([5.0, 6.0, 5.0]) == 5.0 — an outlier lap (the 6L one) doesn't
        # drag the estimate the way a mean would.
        self.assertAlmostEqual(engine.estimated_consumption_per_lap, 5.0)
        self.assertAlmostEqual(engine.estimated_laps_remaining, 84.0 / 5.0)

    def test_history_caps_at_64_laps(self):
        engine = FuelEnergyEngine()
        level = 1000.0
        engine.update(level=level, total_laps=0)
        for lap in range(1, 70):
            level -= 5.0
            engine.update(level=level, total_laps=lap)
        self.assertEqual(len(engine._history), FuelEnergyEngine.HISTORY_SIZE)

    def test_refuel_across_lap_boundary_is_ignored(self):
        engine = FuelEnergyEngine()
        engine.update(level=10.0, total_laps=0)
        recorded = engine.update(level=100.0, total_laps=1)  # pit refuel mid-transition, level rose
        self.assertFalse(recorded)
        self.assertEqual(engine.estimated_consumption_per_lap, 0.0)
        engine.update(level=95.0, total_laps=2)   # normal lap now, consumed 5
        self.assertAlmostEqual(engine.estimated_consumption_per_lap, 5.0)

    def test_pit_lap_is_excluded_from_history(self):
        engine = FuelEnergyEngine()
        engine.update(level=80.0, total_laps=0)
        engine.update(level=75.0, total_laps=1)   # normal lap, consumed 5
        self.assertAlmostEqual(engine.estimated_consumption_per_lap, 5.0)
        engine.update(level=74.0, total_laps=1, is_pit_lap=True)  # pit visit mid-lap
        recorded = engine.update(level=70.0, total_laps=2, is_pit_lap=True)  # lap ends: skip (pit lap)
        self.assertFalse(recorded)
        # Rolling average unaffected by the pit lap's raw delta.
        self.assertAlmostEqual(engine.estimated_consumption_per_lap, 5.0)

    def test_session_restart_resets_history(self):
        engine = FuelEnergyEngine()
        engine.update(level=80.0, total_laps=0)
        engine.update(level=75.0, total_laps=1)
        self.assertAlmostEqual(engine.estimated_consumption_per_lap, 5.0)
        # total_laps goes backwards -> session restart / re-join.
        engine.update(level=100.0, total_laps=0)
        self.assertEqual(engine.estimated_consumption_per_lap, 0.0)
        self.assertEqual(engine.estimated_laps_remaining, 0.0)

    def test_save_and_load_history_round_trip(self):
        engine = FuelEnergyEngine()
        engine.update(level=80.0, total_laps=0)
        engine.update(level=75.0, total_laps=1, lap_time=100.0)   # consumed 5, 100s
        engine.update(level=69.0, total_laps=2, lap_time=102.0)   # consumed 6, 102s

        with tempfile.TemporaryDirectory() as tmp:
            filepath = Path(tmp) / "ref_spa_hypercar.energy.json"
            engine.save_history(filepath)
            self.assertTrue(filepath.exists())
            on_disk = json.loads(filepath.read_text(encoding="utf-8"))
            self.assertEqual(
                on_disk["laps"],
                [{"fuel": 5.0, "lap_time": 100.0}, {"fuel": 6.0, "lap_time": 102.0}],
            )

            fresh_engine = FuelEnergyEngine()
            fresh_engine.load_history(filepath)
            self.assertAlmostEqual(fresh_engine.estimated_consumption_per_lap, 5.5)
            self.assertAlmostEqual(fresh_engine.estimated_lap_time, 101.0)
            # A projection is meaningful immediately, before this session/combo
            # has completed a single lap of its own — the whole point of
            # persisting history (spot a missed refuel from lap 1 of warmup).
            fresh_engine.update(level=40.0, total_laps=0)
            self.assertAlmostEqual(fresh_engine.estimated_laps_remaining, 40.0 / 5.5)

    def test_load_history_missing_file_is_a_noop(self):
        engine = FuelEnergyEngine()
        engine.load_history(Path("/nonexistent/ref_x_y.energy.json"))
        self.assertEqual(engine.estimated_consumption_per_lap, 0.0)

    def test_load_history_backcompat_with_old_fuel_only_schema(self):
        # Older files written before lap_time was added used a flat
        # {"history": [floats]} schema — still loadable, just fuel-only.
        with tempfile.TemporaryDirectory() as tmp:
            filepath = Path(tmp) / "ref_spa_hypercar.energy.json"
            filepath.write_text(json.dumps({"history": [5.0, 6.0]}), encoding="utf-8")
            engine = FuelEnergyEngine()
            engine.load_history(filepath)
            self.assertAlmostEqual(engine.estimated_consumption_per_lap, 5.5)
            self.assertEqual(engine.estimated_lap_time, 0.0)

    def test_lap_time_median_recorded_alongside_consumption(self):
        engine = FuelEnergyEngine()
        engine.update(level=100.0, total_laps=0, lap_time=0.0)
        engine.update(level=95.0, total_laps=1, lap_time=100.0)   # lap: 5L, 100s
        engine.update(level=90.0, total_laps=2, lap_time=110.0)   # lap: 5L, 110s (traffic)
        engine.update(level=85.0, total_laps=3, lap_time=99.0)    # lap: 5L, 99s
        self.assertAlmostEqual(engine.estimated_lap_time, 100.0)  # median([100, 110, 99])

    def test_pit_lap_excludes_lap_time_too(self):
        engine = FuelEnergyEngine()
        engine.update(level=80.0, total_laps=0)
        engine.update(level=75.0, total_laps=1, lap_time=100.0)   # normal lap
        engine.update(level=74.0, total_laps=1, lap_time=0.0, is_pit_lap=True)  # pit visit mid-lap
        # Pit-in lap: much slower — must not drag the median lap time down.
        recorded = engine.update(level=70.0, total_laps=2, lap_time=140.0, is_pit_lap=True)
        self.assertFalse(recorded)
        self.assertAlmostEqual(engine.estimated_lap_time, 100.0)

    def test_missing_lap_time_does_not_lose_fuel_sample(self):
        # lap_time reporting 0.0 the very tick total_laps increments must not
        # cost the fuel sample its place in history.
        engine = FuelEnergyEngine()
        engine.update(level=80.0, total_laps=0)
        recorded = engine.update(level=75.0, total_laps=1, lap_time=0.0)
        self.assertTrue(recorded)
        self.assertAlmostEqual(engine.estimated_consumption_per_lap, 5.0)
        self.assertEqual(engine.estimated_lap_time, 0.0)


class TestFuelHistoryFilepath(unittest.TestCase):
    """DeltaEngine.get_energy_history_filepath() — the ref_<track>_<car>.energy.json
    naming FuelEnergyEngine's persistence keys off, resolved independently of
    any best-lap state (see its docstring for why it's a sibling file rather
    than a key merged into ref_<track>_<car>.json itself)."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_ref_dir = delta_engine_module._REF_LAPS_DIR
        delta_engine_module._REF_LAPS_DIR = Path(self.temp_dir)
        self.engine = DeltaEngine()

    def tearDown(self):
        delta_engine_module._REF_LAPS_DIR = self.original_ref_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_none_before_track_resolved(self):
        self.assertIsNone(self.engine.get_energy_history_filepath())

    def test_matches_reference_lap_naming_family(self):
        self.engine._track_name = "Spa-Francorchamps"
        self.engine._vehicle_class = "Hypercar"
        path = self.engine.get_energy_history_filepath()
        self.assertEqual(path, Path(self.temp_dir) / "ref_spa-francorchamps_hypercar.energy.json")
        # Same directory/prefix as the telemetry + marks files for this combo.
        self.assertEqual(
            path.name,
            Path(self.engine._get_profile_filepath()).name.replace(".json", ".energy.json"),
        )

    def test_does_not_perturb_has_reference(self):
        # Resolving the filepath (and, downstream, FuelEnergyEngine writing to
        # it) must never flip DeltaEngine.has_reference — that gate is driven
        # solely by _apply_active_profile()'s t_grid, which this never touches.
        self.engine._track_name = "Spa"
        self.engine._vehicle_class = "Hypercar"
        self.engine.get_energy_history_filepath()
        self.assertFalse(self.engine.has_reference)


class TestFuelEngineTelemetryBusIntegration(unittest.TestCase):
    """End-to-end: DeltaEngine identity -> ReferenceLapManager.get_energy_history_filepath()
    -> FuelEnergyEngine persistence, the same path TelemetryBus._sync_fuel_history_combo()/
    _apply_fuel_fields() drive on every physics tick."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_ref_dir = delta_engine_module._REF_LAPS_DIR
        delta_engine_module._REF_LAPS_DIR = Path(self.temp_dir)

    def tearDown(self):
        delta_engine_module._REF_LAPS_DIR = self.original_ref_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_persisted_history_survives_a_fresh_engine_for_the_same_combo(self):
        from simpulse.core.reference_lap import ReferenceLapManager

        mgr = ReferenceLapManager()
        mgr.delta_engine._track_name = "Spa"
        mgr.delta_engine._vehicle_class = "Hypercar"
        filepath = mgr.get_energy_history_filepath()
        self.assertIsNotNone(filepath)

        # Simulate a stint: 3 laps at 5L/lap.
        engine = FuelEnergyEngine()
        level = 100.0
        for lap in range(0, 4):
            if lap > 0:
                level -= 5.0
            recorded = engine.update(level=level, total_laps=lap)
            if recorded:
                engine.save_history(filepath)
        self.assertTrue(filepath.exists())

        # A brand new engine for the SAME combo (e.g. next session's warmup,
        # before any lap of its own) already has a meaningful projection.
        fresh = FuelEnergyEngine()
        fresh.load_history(filepath)
        self.assertAlmostEqual(fresh.estimated_consumption_per_lap, 5.0)
        fresh.update(level=12.0, total_laps=0)
        self.assertAlmostEqual(fresh.estimated_laps_remaining, 12.0 / 5.0)

    def test_real_bus_captures_consumption_across_a_lap_even_with_an_out_of_order_packet(self):
        """End-to-end through the REAL TelemetryBus.process_raw_packet ->
        _apply_fuel_fields() -> FuelEnergyEngine.update() path (not a direct
        engine.update() call) — the exact pipeline that failed to capture any
        consumption before ScoringFreshnessGuard: a stale/out-of-order
        CompactScoring packet regressing TelemetryStateStore.total_laps mid-
        lap made FuelEnergyEngine see a spurious "lap transition" (or a
        transition back to the wrong lap number), snapshotting the wrong
        _lap_start_level and corrupting/losing that lap's consumption sample
        — even though DeltaEngine's own sample-collection bug (see
        test_scoring_freshness_guard.py) was the one actually noticed first."""
        from isimotor_rawudp_client import TelemInfo, CompactScoring
        from simpulse.core.reference_lap import ReferenceLapManager
        from simpulse.core.telemetry_bus import TelemetryBus
        from simpulse_sdk.models.state_store import TelemetryStateStore

        store = TelemetryStateStore.get_instance()
        store.reset()
        try:
            bus = TelemetryBus(reference_lap_mgr=ReferenceLapManager())
            bus.reference_lap_mgr.delta_engine._track_name = "Spa"
            bus.reference_lap_mgr.delta_engine._vehicle_class = "Hypercar"

            # total_laps=0 baseline, tank at 80L. _apply_fuel_fields() only
            # runs on a TelemInfo tick, so the CompactScoring establishing
            # total_laps must land BEFORE the TelemInfo tick that's supposed
            # to observe it — mirrors the real UDP feed's ordering.
            bus.process_raw_packet(
                TelemetryChannel.COMPACT_SCORING,
                CompactScoring(current_et=5.0, total_laps=0, count_lap_flag=2),
                184,
            )
            bus.process_raw_packet(
                TelemetryChannel.TELEMETRY, TelemInfo(fuel=80.0), 640
            )

            # Lap crosses to 1, tank down to 60L (20L burned this lap).
            bus.process_raw_packet(
                TelemetryChannel.COMPACT_SCORING,
                CompactScoring(current_et=100.0, total_laps=1, count_lap_flag=2),
                184,
            )
            bus.process_raw_packet(
                TelemetryChannel.TELEMETRY, TelemInfo(fuel=60.0), 640
            )
            self.assertAlmostEqual(bus.fuel_engine.last_lap_consumption, 20.0)
            self.assertAlmostEqual(bus.fuel_engine.estimated_consumption_per_lap, 20.0)

            # A stale/out-of-order CompactScoring regressing total_laps back
            # to 0 arrives late (UDP is not FIFO) — must be rejected, not
            # treated as a real transition back to lap 0, which would make
            # FuelEnergyEngine.update() see total_laps go backwards and
            # wipe its whole history (see FuelEnergyEngine.update()'s
            # `total_laps < self._last_total_laps -> self.reset()`).
            bus.process_raw_packet(
                TelemetryChannel.COMPACT_SCORING,
                CompactScoring(current_et=99.5, total_laps=0, count_lap_flag=2),
                184,
            )

            # One more physics tick (tank unchanged, still mid-lap): if the
            # stale packet had been accepted, this call would see total_laps
            # regress under FuelEnergyEngine's own last-seen value and reset
            # everything it just captured.
            bus.process_raw_packet(
                TelemetryChannel.TELEMETRY, TelemInfo(fuel=60.0), 640
            )

            self.assertAlmostEqual(bus.fuel_engine.last_lap_consumption, 20.0)
            self.assertAlmostEqual(bus.fuel_engine.estimated_consumption_per_lap, 20.0)
            self.assertAlmostEqual(bus.latest_energy.consumption_per_lap, 20.0)
        finally:
            store.reset()


class TestFuelAnomalyDetection(unittest.TestCase):
    """FuelEnergyEngine.is_tank_full()/has_insufficient_fuel_anomaly() — the
    "fuel insufficient to finish AND tank not topped up" anomaly."""

    def test_is_tank_full_before_anything_observed(self):
        engine = FuelEnergyEngine()
        self.assertTrue(engine.is_tank_full(0.0))
        self.assertTrue(engine.is_tank_full(50.0))

    def test_is_tank_full_tracks_the_session_peak(self):
        engine = FuelEnergyEngine()
        engine.update(level=100.0, total_laps=0)  # race-start full tank
        engine.update(level=95.0, total_laps=1)
        self.assertFalse(engine.is_tank_full(95.0))
        self.assertTrue(engine.is_tank_full(100.0))
        # Within tolerance of the peak still counts as full.
        self.assertTrue(engine.is_tank_full(99.5))

    def test_is_tank_full_rises_after_a_refuel(self):
        engine = FuelEnergyEngine()
        engine.update(level=60.0, total_laps=0)  # started at 60% (not full)
        engine.update(level=90.0, total_laps=1)  # topped up mid-session to 90
        self.assertTrue(engine.is_tank_full(90.0))
        self.assertFalse(engine.is_tank_full(60.0))

    def test_no_anomaly_when_session_length_unknown(self):
        engine = FuelEnergyEngine()
        engine.update(level=10.0, total_laps=0)
        self.assertFalse(engine.has_insufficient_fuel_anomaly(10.0, session_energy_ratio=None))

    def test_no_anomaly_when_energy_ratio_is_sufficient(self):
        engine = FuelEnergyEngine()
        engine.update(level=100.0, total_laps=0)
        self.assertFalse(engine.has_insufficient_fuel_anomaly(100.0, session_energy_ratio=1.0))
        self.assertFalse(engine.has_insufficient_fuel_anomaly(100.0, session_energy_ratio=1.2))

    def test_no_anomaly_when_insufficient_but_tank_is_full(self):
        # Structurally can't do the whole session on one tank — normal for
        # endurance racing, not a "forgot to refuel" anomaly.
        engine = FuelEnergyEngine()
        engine.update(level=100.0, total_laps=0)
        self.assertFalse(engine.has_insufficient_fuel_anomaly(100.0, session_energy_ratio=0.8))

    def test_anomaly_when_insufficient_and_tank_not_topped_up(self):
        engine = FuelEnergyEngine()
        engine.update(level=100.0, total_laps=0)  # peak seen: 100
        engine.update(level=95.0, total_laps=1)   # currently at 95 — not full
        self.assertTrue(engine.has_insufficient_fuel_anomaly(95.0, session_energy_ratio=0.8))

    def test_max_level_seen_resets_on_session_restart(self):
        engine = FuelEnergyEngine()
        engine.update(level=100.0, total_laps=0)
        engine.update(level=95.0, total_laps=1)
        engine.update(level=50.0, total_laps=0)  # total_laps regressed -> reset
        self.assertEqual(engine.max_level_seen, 50.0)


if __name__ == "__main__":
    unittest.main()
