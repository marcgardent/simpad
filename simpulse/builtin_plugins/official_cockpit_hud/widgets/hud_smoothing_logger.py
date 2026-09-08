"""
HUD smoothing debug logger (diagnostics only — no behaviour change).

Records, for every live sample fed into a HudTimeWindowAverage (Delta Timer
and Sector Times boxes — see display_cache.py), both the RAW reading and the
SMOOTHED one side by side, so it's possible to confirm from the log alone
whether smoothing is actually doing anything and on which widget. Controlled
solely by config.json ``loggers.hud_smoothing`` (default off); the app calls
set_hud_smoothing_enabled() at startup — same wiring as sector_paint/
delta_debug/sector_eval, see runtime_loggers.py.
"""
from __future__ import annotations
import time
from pathlib import Path

_LOG = Path(__file__).resolve().parents[4] / "hud_smoothing.log"

_ENABLED = False
_fh = None
_last_line = None


def set_hud_smoothing_enabled(enabled: bool) -> None:
    """Enables or disables the recorder (config loggers.hud_smoothing)."""
    global _ENABLED
    _ENABLED = bool(enabled)


def record_smoothing(
    label: str,
    raw_value: float,
    raw_text: str,
    smoothed_value: float,
    smoothed_text: str,
    window_s: float,
    game_time_s: float,
) -> None:
    """Called once per sample that a HudTimeWindowAverage actually averaged.

    ``label``: which readout this is ("delta_timer", "sector1", "sector2",
    "sector3"). See ``record_passthrough`` for the "no data" case (nothing
    to average — call that instead of this one)."""
    _write(
        f"label={label} window_s={window_s:.3f} game_t={game_time_s:.3f} "
        f"raw={raw_value:+.4f} ({raw_text!r}) -> smoothed={smoothed_value:+.4f} ({smoothed_text!r})"
    )


def record_passthrough(label: str, raw_text: str, window_s: float, game_time_s: float) -> None:
    """Called once per sample a HudTimeWindowAverage passed through as-is
    (raw_text was "--"/no reference — window reset, nothing averaged)."""
    _write(f"label={label} window_s={window_s:.3f} game_t={game_time_s:.3f} passthrough ({raw_text!r})")


def _write(line: str) -> None:
    global _fh, _last_line
    if not _ENABLED:
        return
    if line == _last_line:
        return
    _last_line = line

    if _fh is None:
        try:
            _fh = open(_LOG, "a", encoding="utf-8", buffering=1)
            _fh.write(f"\n{'=' * 108}\n[HUD_SMOOTHING START {time.strftime('%Y-%m-%d %H:%M:%S')}]\n{'=' * 108}\n")
        except Exception:
            _fh = None
            return

    now = time.time()
    ts = time.strftime("%H:%M:%S") + f".{int((now % 1) * 1000):03d}"
    try:
        _fh.write(f"[{ts}] {line}\n")
    except Exception:
        pass
