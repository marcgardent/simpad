"""
Sector paint recorder (diagnostics only — no behaviour change).

Records every frame-level transition of what the Official Cockpit HUD sector
widget is about to paint for the three boxes, including one-frame background
flickers (e.g. a frozen green/purple box briefly rendered with the dark 'default'
background). Driven by SIMPULSE_SECTOR_PAINT_LOG (default on) for up to
SIMPULSE_SECTOR_PAINT_LOG_SEC seconds (default 3600).
"""
from __future__ import annotations
import os
import time
from pathlib import Path

v = os.environ.get("SIMPULSE_SECTOR_PAINT_LOG", "1").strip().lower()
_ENABLED = v not in ("", "0", "false", "no", "off")
try:
    _MAX_SECONDS = float(os.environ.get("SIMPULSE_SECTOR_PAINT_LOG_SEC", "3600"))
except ValueError:
    _MAX_SECONDS = 3600.0
_LOG = Path(__file__).resolve().parents[4] / "sector_paint.log"

_fh = None
_start = None
_last = None


def record(curr_sector: int, boxes: list, mode: list, rgb: list) -> None:
    """Called each paint. boxes[i]=drawn text, mode[i] in ('live','frozen'),
    rgb[i]=(r,g,b) background actually drawn for box i."""
    global _fh, _start, _last
    if not _ENABLED:
        return
    now = time.time()
    if _fh is None:
        try:
            _fh = open(_LOG, "a", encoding="utf-8", buffering=1)
            _fh.write(f"\n{'='*108}\n[SECTOR_PAINT START {time.strftime('%Y-%m-%d %H:%M:%S')}]\n{'='*108}\n")
        except Exception:
            _fh = None
        _start = now
    if _start and (now - _start) > _MAX_SECONDS:
        return
    key = tuple(zip(boxes, mode, rgb))
    if _last == key:
        return
    _last = key
    ts = time.strftime("%H:%M:%S") + f".{int((now % 1) * 1000):03d}"
    parts = []
    for i in range(3):
        parts.append(f"b{i+1}={boxes[i]}|{mode[i]}|{rgb[i][0]},{rgb[i][1]},{rgb[i][2]}")
    line = f"[{ts}] cur=S{curr_sector} " + " ".join(parts)
    if _fh is not None:
        try:
            _fh.write(line + "\n")
        except Exception:
            pass
