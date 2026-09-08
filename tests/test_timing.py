"""
Contract: TimeTarget/is_personal_record_target are resolved by two independent
functions (resolve_target / resolve_is_personal_record_target) — never merged
into one value. See TIME_STATUS_SPEC.md.
"""
import unittest

from simpulse_sdk.models.timing import (
    TimeLap,
    TimeTarget,
    WallOfFameTimes,
    resolve_is_personal_record_target,
    resolve_target,
)

EPS = 0.1


def _wof(ever=0.0, session=0.0, paddock=0.0) -> WallOfFameTimes:
    return WallOfFameTimes(
        my_best_all_time=TimeLap(total=ever),
        my_best_session=TimeLap(total=session),
        paddock_session_best=TimeLap(total=paddock),
    )


class TestTimeLap(unittest.TestCase):
    def test_is_valid(self):
        self.assertFalse(TimeLap().is_valid)
        self.assertFalse(TimeLap(total=999900.0).is_valid)
        self.assertTrue(TimeLap(total=90.0).is_valid)

    def test_formatters(self):
        lap = TimeLap(sector1=30.0, sector2=30.0, sector3=30.0, total=90.0)
        self.assertEqual(lap.total_str, "01:30.000")
        self.assertEqual(lap.sector1_str, "00:30.000")


class TestResolveTarget(unittest.TestCase):
    """Priority: PADDOCK > SESSION > BEHIND > NONE."""

    def test_no_reference_is_none(self):
        wof = _wof()
        self.assertEqual(resolve_target(90.0, wof, "total", EPS), TimeTarget.NONE)

    def test_unknown_current_is_none(self):
        wof = _wof(session=100.0)
        self.assertEqual(resolve_target(0.0, wof, "total", EPS), TimeTarget.NONE)

    def test_behind_known_reference_not_beaten(self):
        wof = _wof(session=100.0)
        self.assertEqual(resolve_target(101.0, wof, "total", EPS), TimeTarget.BEHIND)

    def test_session_beaten(self):
        wof = _wof(session=100.0)
        self.assertEqual(resolve_target(99.0, wof, "total", EPS), TimeTarget.SESSION)

    def test_paddock_beats_session_priority(self):
        wof = _wof(session=100.0, paddock=99.5)
        # Beats both -> paddock wins (higher priority), even though session is
        # also beaten.
        self.assertEqual(resolve_target(99.0, wof, "total", EPS), TimeTarget.PADDOCK)

    def test_beats_session_only_not_paddock(self):
        wof = _wof(session=100.0, paddock=95.0)
        self.assertEqual(resolve_target(99.0, wof, "total", EPS), TimeTarget.SESSION)

    def test_all_time_best_never_considered(self):
        # ever alone (no session/paddock known) must never promote to
        # SESSION/PADDOCK — resolve_target ignores my_best_all_time entirely.
        wof = _wof(ever=50.0)
        self.assertEqual(resolve_target(10.0, wof, "total", EPS), TimeTarget.NONE)

    def test_equality_within_eps_counts_as_beaten(self):
        wof = _wof(session=100.0)
        self.assertEqual(resolve_target(100.05, wof, "total", EPS), TimeTarget.SESSION)

    def test_sector_key(self):
        wof = WallOfFameTimes(my_best_session=TimeLap(sector1=30.0))
        self.assertEqual(resolve_target(29.5, wof, "sector1", EPS), TimeTarget.SESSION)
        self.assertEqual(resolve_target(29.5, wof, "sector2", EPS), TimeTarget.NONE)


class TestResolveIsPersonalRecordTarget(unittest.TestCase):
    """Independent of resolve_target: looks ONLY at my_best_all_time."""

    def test_no_all_time_known(self):
        wof = _wof(session=100.0)
        self.assertFalse(resolve_is_personal_record_target(90.0, wof, "total", EPS))

    def test_strictly_better_required(self):
        wof = _wof(ever=100.0)
        # Exactly equal to `ever` (delta == 0 at lap start) must NOT be a PR.
        self.assertFalse(resolve_is_personal_record_target(100.0, wof, "total", EPS))
        # Within eps of equal is also not enough (strict, not "or equal").
        self.assertFalse(resolve_is_personal_record_target(99.95, wof, "total", EPS))
        # Genuinely beats it by more than eps.
        self.assertTrue(resolve_is_personal_record_target(99.5, wof, "total", EPS))

    def test_beats_all_time_without_beating_paddock(self):
        """The reason these two functions are separate: beating my all-time
        best (slower than the paddock) must report is_personal_record_target
        True while target stays SESSION or BEHIND — never merged into one
        enum value."""
        wof = _wof(ever=100.0, session=105.0, paddock=90.0)
        current = 99.0  # beats ever(100) and session(105), but not paddock(90)
        self.assertEqual(resolve_target(current, wof, "total", EPS), TimeTarget.SESSION)
        self.assertTrue(resolve_is_personal_record_target(current, wof, "total", EPS))

    def test_unknown_current_is_false(self):
        wof = _wof(ever=100.0)
        self.assertFalse(resolve_is_personal_record_target(0.0, wof, "total", EPS))


if __name__ == "__main__":
    unittest.main()
