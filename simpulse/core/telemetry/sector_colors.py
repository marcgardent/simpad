"""
Single source of truth for *sector split* colour status.

The Cockpit HUD paints each completed (frozen) sector box with a colour driven by
"sectorN_status". Two parsers/engines previously re-implemented their own rule:

  * DeltaEngine  : green when split better than personal best, never purple.
  * LMUParser    : purple when split also better than the session best.

Because both write the same box model, the same 38.437 s split oscillated between
green and purple frame-to-frame (~1 flash per low-frequency packet). This module
is the only place allowed to answer "what colour is this split".

Rule (in priority order):
  1. unknown / invalid value            -> "default"
  2. split ≤ session best (+ tolerance) -> "purple"
  3. split ≤ personal best (+ tolerance)-> "green"
  4. otherwise                          -> "default"

EPSILON mirrors the historical comparisons (val <= best + 0.001).
"""
from __future__ import annotations
import time as _time
from pathlib import Path as _Path

from simpulse_sdk.models.delta import ExpectedStatus, SplitStatus

_EPS = 0.001

# ---- sector_eval diagnostic gating -------------------------------------
# sector_eval.log is off by default; enable it via config.json
# ("loggers": {"sector_eval": true}) which calls set_sector_eval_enabled(True).
_AUDIT_ENABLED: bool = False


def set_sector_eval_enabled(enabled: bool) -> None:
    """Enables or disables writing to sector_eval.log (config loggers.sector_eval)."""
    global _AUDIT_ENABLED
    _AUDIT_ENABLED = bool(enabled)


# ---- diagnostics ------------------------------------------------------------
# Audit file for every split-colour decision (won't alter behaviour); useful to
# prove which producer (delta/lmu) evaluates a paint and on which references.
_EVAL_LOG = _Path(__file__).resolve().parents[3] / "sector_eval.log"


def _audit(source: str, value: float, best: float, sess: float, status: str) -> None:
    if not _AUDIT_ENABLED:
        return
    try:
        now = _time.time()
        ts = _time.strftime("%H:%M:%S") + f".{int((now % 1) * 1000):03d}"
        with open(_EVAL_LOG, "a", encoding="utf-8", buffering=1) as fh:
            fh.write(f"[{ts}] src={source} split={value:.3f} personal={best:.3f} "
                     f"session={sess:.3f} -> {status}\n")
    except Exception:
        pass


def sector_split_status(
    value: float,
    personal_best: float,
    session_best: float | None = None,
    *, source: str = "model",
) -> SplitStatus:
    """Colour status of an individual sector split.

    Racing standard:
      - session/purple: split at or better than the best split of the whole session
        (equal record included);
      - personal/pink : split better than this car's personal best only;
      - default       : otherwise (dark).
    """
    try:
        val = float(value)
    except (TypeError, ValueError):
        return SplitStatus.DEFAULT
    if val <= 0.0 or val >= 999900.0:
        return SplitStatus.DEFAULT

    sess = 0.0
    if session_best is not None:
        try:
            sess = float(session_best)
        except (TypeError, ValueError):
            sess = 0.0
        if sess < 0.0:
            sess = 0.0

    try:
        best = float(personal_best)
    except (TypeError, ValueError):
        best = 0.0

    # Purple only while the session best is genuinely stricter than the personal
    # best (a rival improved it). Solo / no-session packets report the same value
    # for both bounds and must NOT claim an equal-record purple.
    if 0.0 < sess < 999900.0 and 0.0 < best < 999900.0 and sess <= (best - _EPS):
        if val <= (sess + _EPS):
            _audit(source, val, best, sess, "purple")
            return SplitStatus.PURPLE

    if 0.0 < best < 999900.0 and val <= (best + _EPS):
        _audit(source, val, best, sess, "pink")
        return SplitStatus.PINK
    _audit(source, val, best, sess, "default")
    return SplitStatus.DEFAULT


def expected_status(
    expected: float,
    *,
    ever=None,
    paddock=None,
    session=None,
    invalid: bool = False,
    eps: float = _EPS,
    source: str = "expected",
) -> ExpectedStatus:
    """Colour of an *expected (projected) lap time* under the unified rule.

    The expected/estimated lap time is the projection at the current instant
    (reference + live delta).  It is compared here, with strict priority, to the
    three scalar baselines:

      * ``pink``   → expected better-or-equal my **best-ever** (all-sessions);
      * ``purple`` → else better-or-equal the **paddock** best (other cars, session);
      * ``green``  → else better-or-equal **my session** best;
      * ``yellow`` → else a *valid* expected value slower than my session;
      * ``white``  → no usable reference at all (still tracking before any lap).

    Comparisons are “better-or-equal with EPS” (equal record counts as beaten).
    Missing reference values (None / 0 / ≥999900) never demote the colour: pink
    and purple are simply skipped when their baseline is unknown.
    """
    try:
        v = float(expected)
    except (TypeError, ValueError):
        v = 0.0
    if invalid:
        return ExpectedStatus.INVALID
    if not (0.0 < v < 999900.0):
        return ExpectedStatus.WHITE

    def _num(x):
        if x is None:
            return None
        try:
            f = float(x)
        except (TypeError, ValueError):
            return None
        return f if 0.0 < f < 999900.0 else None

    ev = _num(ever)
    pd = _num(paddock)
    ss = _num(session)
    if ev is not None and v <= ev + eps:
        return ExpectedStatus.PINK
    if pd is not None and v <= pd + eps:
        return ExpectedStatus.PURPLE
    if ss is not None:
        return ExpectedStatus.GREEN if v <= ss + eps else ExpectedStatus.YELLOW
    return ExpectedStatus.WHITE


__all__ = ["sector_split_status", "expected_status", "set_sector_eval_enabled"]
