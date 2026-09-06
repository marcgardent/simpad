"""
Sector paint recorder (diagnostics only — no behaviour change).

Records every frame-level transition of what the Official Cockpit HUD sector
widget is about to paint for the three boxes, including one-frame background
flickers (e.g. a frozen green/purple box briefly rendered with the dark 'default'
background). Controlled solely by config.json loggers.sector_paint (default
off); the app calls set_sector_paint_enabled() at startup.
"""
from __future__ import annotations
import time
from pathlib import Path

_LOG = Path(__file__).resolve().parents[4] / "sector_paint.log"

_ENABLED = False
_fh = None
_last = None


def set_sector_paint_enabled(enabled: bool) -> None:
    """Enables or disables the recorder (config loggers.sector_paint)."""
    global _ENABLED
    _ENABLED = bool(enabled)


def record(curr_sector: int, boxes: list, mode: list, rgb: list) -> None:
    """Called each paint. boxes[i]=drawn text, mode[i] in ('live','frozen'),
    rgb[i]=(r,g,b) background actually drawn for box i."""
    global _fh, _last
    if not _ENABLED:
        return
    key = tuple(zip(boxes, mode, rgb))
    if _last == key:
        return
    _last = key
    if _fh is None:
        try:
            _fh = open(_LOG, "a", encoding="utf-8", buffering=1)
            _fh.write(f"\n{'=' * 108}\n[SECTOR_PAINT START {time.strftime('%Y-%m-%d %H:%M:%S')}]\n{'=' * 108}\n")
        except Exception:
            _fh = None
            return
    now = time.time()
    ts = time.strftime("%H:%M:%S") + f".{int((now % 1) * 1000):03d}"
    parts = []
    for i in range(3):
        parts.append(f"b{i+1}={boxes[i]}|{mode[i]}|{rgb[i][0]},{rgb[i][1]},{rgb[i][2]}")
    line = f"[{ts}] cur=S{curr_sector} " + " ".join(parts)
    try:
        _fh.write(line + "\n")
    except Exception:
        pass
