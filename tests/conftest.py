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
