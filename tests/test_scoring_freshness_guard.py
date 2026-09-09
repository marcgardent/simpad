"""Unit tests for ScoringFreshnessGuard (simpulse_sdk/models/scoring_freshness.py)."""

import unittest

from simpulse_sdk.models.scoring_freshness import ScoringFreshnessGuard


class TestScoringFreshnessGuard(unittest.TestCase):
    def test_first_packet_always_accepted(self):
        guard = ScoringFreshnessGuard()
        self.assertTrue(guard.should_accept(12.5))

    def test_increasing_current_et_always_accepted(self):
        guard = ScoringFreshnessGuard()
        self.assertTrue(guard.should_accept(10.0))
        self.assertTrue(guard.should_accept(10.1))
        self.assertTrue(guard.should_accept(15.0))

    def test_equal_current_et_accepted(self):
        """Two packets can legitimately report the same current_et (e.g. the
        same game tick observed by both CompactScoring and FullScoringSession)
        — not a regression, must not be rejected."""
        guard = ScoringFreshnessGuard()
        self.assertTrue(guard.should_accept(10.0))
        self.assertTrue(guard.should_accept(10.0))

    def test_out_of_order_packet_rejected(self):
        """A stale/out-of-order packet (UDP delivery is not FIFO) — a small
        backwards jump, well within session_reset_tolerance_s — is rejected."""
        guard = ScoringFreshnessGuard()
        self.assertTrue(guard.should_accept(20.0))
        self.assertFalse(guard.should_accept(19.8))
        # Baseline must stay at 20.0, not silently move to the rejected value.
        self.assertFalse(guard.should_accept(19.9))
        self.assertTrue(guard.should_accept(20.1))

    def test_large_backwards_jump_treated_as_session_restart(self):
        """A big drop (session restart, garage re-entry, current_et itself
        resetting near 0) is accepted, not rejected forever."""
        guard = ScoringFreshnessGuard(session_reset_tolerance_s=5.0)
        self.assertTrue(guard.should_accept(300.0))
        self.assertFalse(guard.should_accept(295.5))  # small jitter -> rejected
        self.assertTrue(guard.should_accept(0.0))      # session restart -> accepted
        self.assertTrue(guard.should_accept(0.1))       # resumes normal advance

    def test_reset_clears_baseline(self):
        guard = ScoringFreshnessGuard()
        guard.should_accept(500.0)
        guard.reset()
        # Without reset, 1.0 would be a huge backwards jump but still within
        # tolerance of a *fresh* guard (no baseline yet) -> always accepted.
        self.assertTrue(guard.should_accept(1.0))


if __name__ == "__main__":
    unittest.main()
