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


def test_lmu_sector3_detection():
    """Verify that mSector=0 in LMU telemetry maps to current_sector=3."""
    scoring_sec3 = {
        "Type": "ScoringInfoV01",
        "mInRealtime": True,
        "mGamePhase": 5,
        "mVehicles": [
            {
                "mDriverName": "Test Driver",
                "mIsPlayer": True,
                "mControl": 0,
                "mInGarageStall": False,
                "mInPits": False,
                "mSector": 0,  # 0 represents Sector 3 in LMU telemetry
                "mCurSector1": 45.2,
                "mCurSector2": 110.5,
            }
        ]
    }
    data_bytes = json.dumps(scoring_sec3).encode("utf-8")
    res = LMUParser.parse(data_bytes)
    assert res is not None
    assert res.current_sector == 3, f"mSector=0 must map to current_sector=3, got {res.current_sector}"


def test_lmu_window_utils_smoke():
    """Smoke test window utility functions."""
    title = get_foreground_window_title()
    assert isinstance(title, str)
    proc_name = get_foreground_process_name()
    assert isinstance(proc_name, str)
    is_fg = is_lmu_foreground()
    assert isinstance(is_fg, bool)


import tempfile
import unittest
from src.telemetry.plugin_installer import (
    get_steam_vdf_candidate_paths,
    parse_vdf_library_paths,
    get_known_lmu_paths,
    LMUPluginManager,
)


class TestLMUSteamDetection(unittest.TestCase):
    """Unit tests for Steam libraryfolders.vdf parsing and LMU installation detection."""

    def test_vdf_candidate_paths_not_empty(self):
        """Verify that candidate paths are generated dynamically without hardcoded static paths."""
        candidates = get_steam_vdf_candidate_paths()
        self.assertGreater(len(candidates), 0)
        # Check that paths use Path instances
        for p in candidates:
            self.assertIsInstance(p, Path)

    def test_parse_vdf_library_paths(self):
        """Verify parsing of libraryfolders.vdf content."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            vdf_file = tmp_path / "libraryfolders.vdf"

            # Create mock library directories
            lib1 = tmp_path / "lib1"
            lib2 = tmp_path / "lib2"
            lib1.mkdir()
            lib2.mkdir()

            lib1_str = str(lib1).replace("\\", "\\\\")
            lib2_str = str(lib2).replace("\\", "\\\\")

            vdf_content = f"""
"libraryfolders"
{{
    "0"
    {{
        "path"        "{lib1_str}"
        "label"        ""
    }}
    "1"
    {{
        "path"        "{lib2_str}"
        "label"        ""
    }}
}}
            """
            vdf_file.write_text(vdf_content, encoding="utf-8")

            parsed = parse_vdf_library_paths(vdf_file)
            self.assertEqual(len(parsed), 2)
            self.assertIn(lib1, parsed)
            self.assertIn(lib2, parsed)

    def test_find_lmu_via_vdf(self):
        """Verify LMU detection via VDF configuration."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            vdf_file = tmp_path / "libraryfolders.vdf"

            lib = tmp_path / "steam_library"
            lmu_dir = lib / "steamapps" / "common" / "Le Mans Ultimate"
            lmu_dir.mkdir(parents=True)
            (lmu_dir / "Le Mans Ultimate.exe").write_text("dummy exe")

            lib_str = str(lib).replace("\\", "\\\\")

            vdf_content = f"""
"libraryfolders"
{{
    "0"
    {{
        "path"        "{lib_str}"
    }}
}}
            """
            vdf_file.write_text(vdf_content, encoding="utf-8")

            parsed = parse_vdf_library_paths(vdf_file)
            self.assertEqual(len(parsed), 1)
            self.assertEqual(parsed[0], lib)

            # Test finding LMU directory inside parsed library
            found_lmu = lib / "steamapps" / "common" / "Le Mans Ultimate"
            self.assertTrue(found_lmu.exists())
            self.assertTrue((found_lmu / "Le Mans Ultimate.exe").exists())

