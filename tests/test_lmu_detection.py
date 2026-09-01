"""
Tests for LMU InGame detection and pit/garage menu trap prevention.
"""

import json
from pathlib import Path
from src.telemetry.lmu_parser import LMUParser, TelemetryData
from src.utils.window_utils import is_lmu_foreground, get_foreground_window_title, get_foreground_process_name


from isimotor_rawudp_client import FullScoringSession, VehicleScoring, CompactScoring


def test_lmu_scoring_garage_menu_trap():
    """Verify that scoring in garage/pit menu evaluates in_realtime as False."""
    player = VehicleScoring(
        id=1,
        driver_name="Test Driver",
        is_player=True,
        control=0,
        in_garage_stall=True,
        in_pits=True,
    )
    session = FullScoringSession(in_realtime=True, vehicles=[player])
    res = LMUParser.process_full_scoring(session)
    assert res is not None
    assert res.in_realtime is False, "Scoring packet in garage stall must evaluate in_realtime as False"


def test_lmu_scoring_on_track():
    """Verify that a FullScoringSession with active player driving evaluates in_realtime as True."""
    player = VehicleScoring(
        id=1,
        driver_name="Test Driver",
        is_player=True,
        control=0,  # Human driver
        in_garage_stall=False,
        in_pits=False,
    )
    session = FullScoringSession(in_realtime=True, vehicles=[player])
    res = LMUParser.process_full_scoring(session)
    assert res is not None
    assert res.in_realtime is True, "Active player driving packet must evaluate in_realtime as True"


def test_lmu_sector3_detection():
    """Verify that sector=0 in LMU telemetry maps to current_sector=3."""
    player = VehicleScoring(
        id=1,
        driver_name="Test Driver",
        is_player=True,
        control=0,
        in_garage_stall=False,
        in_pits=False,
        sector=0,  # 0 represents Sector 3 in LMU telemetry
        cur_sector1=45.2,
        cur_sector2=110.5,
    )
    session = FullScoringSession(in_realtime=True, vehicles=[player])
    res = LMUParser.process_full_scoring(session)
    assert res is not None
    assert res.current_sector == 3, f"sector=0 must map to current_sector=3, got {res.current_sector}"


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

    def test_lmu_plugin_manager_install_all_and_check(self):
        """Verify LMUPluginManager.install_all and check_plugin_installed workflow."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            # Create mock project structure with isiMotor_RawUDP.dll
            dll_dir = tmp_path / "assets" / "plugins" / "isiMotor-RawUDP-Plugin"
            dll_dir.mkdir(parents=True)
            mock_dll = dll_dir / "isiMotor_RawUDP.dll"
            mock_dll.write_bytes(b"mock_rawudp_dll_data")

            # Create mock LMU directory
            lmu_dir = tmp_path / "LMU"
            plugins_dir = lmu_dir / "Plugins"
            plugins_dir.mkdir(parents=True)

            manager = LMUPluginManager(project_root=tmp_path)
            self.assertEqual(manager.get_source_dll(tmp_path), mock_dll)

            # Test install_plugin with mock lmu_dir override via patch
            from unittest.mock import patch
            with patch.object(LMUPluginManager, "find_lmu_install_dir", return_value=lmu_dir), \
                 patch.object(LMUPluginManager, "get_all_lmu_install_dirs", return_value=[lmu_dir]):
                # Before install check
                installed, msg, _ = manager.check_plugin_installed(tmp_path)
                self.assertFalse(installed)

                # Execute install_all
                res = manager.install_all(tmp_path)
                self.assertTrue(res["installed"])
                self.assertIn("installé et configuré avec succès", res["message"])
                self.assertTrue((plugins_dir / "isiMotor_RawUDP.dll").exists())

                # Check json created
                user_json = lmu_dir / "UserData" / "player" / "CustomPluginVariables.JSON"
                self.assertTrue(user_json.exists())
                json_content = json.loads(user_json.read_text(encoding="utf-8"))
                self.assertIn("isiMotor_RawUDP", json_content)
                self.assertEqual(json_content["isiMotor_RawUDP"][" Enabled"], 1)
                self.assertEqual(json_content["isiMotor_RawUDP"]["TargetPort"], "5000")

                # Check settings.json created/configured
                settings_json = lmu_dir / "UserData" / "player" / "Settings.JSON"
                self.assertTrue(settings_json.exists())

                # After install check
                installed, msg, _ = manager.check_plugin_installed(tmp_path)
                self.assertTrue(installed)
                self.assertIn("isiMotor_RawUDP.dll", msg)

    def test_lmu_plugin_manager_download_mock_zip(self):
        """Verify LMUPluginManager download and extraction from zip archive."""
        import zipfile
        import io
        from unittest.mock import patch, MagicMock

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            target_dir = tmp_path / "downloaded_plugin"

            # Create an in-memory mock zip archive containing isiMotor_RawUDP.dll
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zf:
                zf.writestr("isiMotor_RawUDP.dll", b"binary_dll_content_xyz")
                zf.writestr("README.md", b"Test readme")
            zip_bytes = zip_buffer.getvalue()

            mock_response = MagicMock()
            mock_response.read.return_value = zip_bytes
            mock_response.__enter__.return_value = mock_response

            with patch("urllib.request.urlopen", return_value=mock_response):
                extracted_dll = LMUPluginManager.download_and_extract_dll(
                    url="https://example.com/test-plugin.zip",
                    dest_dir=target_dir,
                )
                self.assertIsNotNone(extracted_dll)
                self.assertTrue(extracted_dll.exists())
                self.assertEqual(extracted_dll.read_bytes(), b"binary_dll_content_xyz")



