"""
Global test fixtures.

TelemetryStateStore holds its state as singleton state rather than per-test
instance state, so nothing resets it between tests automatically. Left alone, a
test that leaves it in a non-default state silently pollutes whichever test
happens to run next in the same process — order-dependent failures that don't
reproduce when the polluted test is run alone.

This autouse, session-wide fixture resets it before and after every test, so
individual test files no longer need to (and can't forget to) declare their own
reset_state_store-style fixture.
"""
import pytest

from simpulse.core.telemetry.state_store import TelemetryStateStore


@pytest.fixture(autouse=True)
def _reset_telemetry_singletons():
    TelemetryStateStore.get_instance().reset()
    yield
    TelemetryStateStore.get_instance().reset()


@pytest.fixture(autouse=True, scope="session")
def _disable_real_diagnostic_loggers():
    """Several file-writing diagnostic loggers default to enabled=True at
    the module/class level (delta_debug.log, hud_overlay_glitch.log,
    track_limits_debug.log, telemetry_live.log) — real config.json's
    "loggers" booleans only get applied by the real app's bootstrap
    (runtime_loggers.apply_logger_settings), which the test suite never
    runs. Left alone, every test exercising DeltaEngine/OverlayStateMachine/
    telemetry writes real-looking entries (fake track/vehicle names, fake
    laps) straight into these files at the repo root, indistinguishable
    from a real driving session to a human reading them afterwards — this
    is what actually happened (see the "ref_spa_hypercar.energy.json" and
    delta_debug.log pollution incidents). sector_eval/sector_paint already
    default to off and don't need this.

    Session-scoped (not per-test): each of these is a singleton/module
    global, so flipping it 1000+ times per run adds nothing a single
    session-wide flip doesn't already cover — and a session-scoped fixture
    runs before per-test collection can construct any singleton lazily.
    """
    import simpulse.core.telemetry.delta_engine as delta_engine_module
    from simpulse.core.telemetry.overlay_anomaly_logger import OverlayAnomalyLogger
    from simpulse.core.telemetry.track_limits_logger import TrackLimitsLogger
    from simpulse.core.telemetry.telemetry_logger import TelemetryDiagnosticLogger

    orig_delta_debug = delta_engine_module.DELTA_DEBUG_ENABLED
    delta_engine_module.DELTA_DEBUG_ENABLED = False

    OverlayAnomalyLogger.default_enabled = False
    OverlayAnomalyLogger.get_instance().enabled = False

    TrackLimitsLogger.default_enabled = False
    TrackLimitsLogger.get_instance().enabled = False

    TelemetryDiagnosticLogger.get_instance().enabled = False

    yield

    delta_engine_module.DELTA_DEBUG_ENABLED = orig_delta_debug
