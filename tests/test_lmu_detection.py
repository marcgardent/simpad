"""
Tests for LMU InGame detection and pit/garage menu trap prevention.
"""

import json
from pathlib import Path
from src.telemetry.lmu_parser import LMUParser, TelemetryData
from src.utils.window_utils import is_lmu_foreground, get_foreground_window_title, get_foreground_process_name


def test_lmu_scoring_garage_menu_trap():
    """Verify that scoring.json (which represents garage/pit menu) evaluates in_realtime as False."""
    scoring_path = Path(__file__).resolve().parent.parent / "assets" / "plugins" / "lmu" / "LeMansUltimateTelemetryPlugin" / "scoring.json"
    assert scoring_path.exists(), f"File {scoring_path} does not exist"

    with open(scoring_path, "r", encoding="utf-8") as f:
        data_bytes = f.read().encode("utf-8")

    res = LMUParser.parse(data_bytes)
    assert res is not None
    assert res.in_realtime is False, "Scoring packet in garage stall must evaluate in_realtime as False"


def test_lmu_scoring_on_track():
    """Verify that a ScoringInfoV01 packet with active player driving evaluates in_realtime as True."""
    on_track_scoring = {
        "Type": "ScoringInfoV01",
        "mInRealtime": True,
        "mGamePhase": 5,
        "mVehicles": [
            {
                "mDriverName": "Test Driver",
                "mIsPlayer": True,
                "mControl": 0,  # Human driver
                "mInGarageStall": False,
                "mInPits": False,
            }
        ]
    }
    data_bytes = json.dumps(on_track_scoring).encode("utf-8")
    res = LMUParser.parse(data_bytes)
    assert res is not None
    assert res.in_realtime is True, "Active player driving packet must evaluate in_realtime as True"


def test_lmu_window_utils_smoke():
    """Smoke test window utility functions."""
    title = get_foreground_window_title()
    assert isinstance(title, str)
    proc_name = get_foreground_process_name()
    assert isinstance(proc_name, str)
    is_fg = is_lmu_foreground()
    assert isinstance(is_fg, bool)
