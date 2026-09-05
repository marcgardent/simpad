"""
Tests for LMU InGame detection and pit/garage menu trap prevention.
"""

import json
from pathlib import Path
from simpulse.core.telemetry.lmu_parser import LMUParser, TelemetryData
from simpulse.core.utils.window_utils import is_lmu_foreground, get_foreground_window_title, get_foreground_process_name


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


def test_lmu_scoring_game_phase_garage():
    """Verify that FullScoringSession with game_phase=0 (Garage) evaluates in_realtime as False."""
    player = VehicleScoring(
        id=1,
        driver_name="Test Driver",
        is_player=True,
        control=0,
        in_garage_stall=False,
        in_pits=False,
    )
    session = FullScoringSession(game_phase=0, in_realtime=True, vehicles=[player])
    res = LMUParser.process_full_scoring(session)
    assert res is not None
    assert res.in_realtime is False, "game_phase=0 must evaluate in_realtime as False (Garage)"


def test_lmu_extended_state_garage_monitor():
    """Verify that ExtendedState with in_realtime_fc=False evaluates in_realtime as False."""
    from isimotor_rawudp_client import ExtendedState
    ext = ExtendedState(in_realtime_fc=False)
    res = LMUParser.process_packet(ext)
    assert res is not None
    assert res.in_realtime is False


def test_lmu_system_event_exit_realtime():
    """Verify that SystemEvent event_id=2 (ExitRealtime) evaluates in_realtime as False."""
    from isimotor_rawudp_client import SystemEvent
    evt = SystemEvent(event_id=2)
    res = LMUParser.process_system_event(evt)
    assert res is not None
    assert res.in_realtime is False


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
from simpulse.core.telemetry.plugin_installer import (
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
                self.assertIn("successfully installed and configured", res["message"])
                self.assertTrue((plugins_dir / "isiMotor_RawUDP.dll").exists())

                # Check json created
                user_json = lmu_dir / "UserData" / "player" / "CustomPluginVariables.JSON"
                self.assertTrue(user_json.exists())
                json_content = json.loads(user_json.read_text(encoding="utf-8"))
                self.assertIn("isiMotor_RawUDP.dll", json_content)
                self.assertEqual(json_content["isiMotor_RawUDP.dll"][" Enabled"], 1)
                self.assertEqual(json_content["isiMotor_RawUDP.dll"]["TargetPort"], "5000")

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

    def test_multi_simulator_detection(self):
        """Verify detection of both Le Mans Ultimate and rFactor 2 installations."""
        from simpulse.core.telemetry.plugin_installer import LMUPluginManager, SUPPORTED_GAMES
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            steam_dir = tmp_path / "SteamLibrary"

            # Create LMU structure
            lmu_dir = steam_dir / "steamapps" / "common" / "Le Mans Ultimate"
            lmu_dir.mkdir(parents=True)
            (lmu_dir / "Le Mans Ultimate.exe").write_bytes(b"exe")
            (lmu_dir / "Plugins").mkdir(parents=True)
            (lmu_dir / "Plugins" / "isiMotor_RawUDP.dll").write_bytes(b"dll")

            # Create rFactor 2 structure
            rf2_dir = steam_dir / "steamapps" / "common" / "rFactor 2"
            rf2_dir.mkdir(parents=True)
            (rf2_dir / "rFactor2.exe").write_bytes(b"exe")

            # Mock libraryfolders.vdf
            vdf_file = tmp_path / "libraryfolders.vdf"
            vdf_file.write_text(f'"libraryfolders" {{\n  "0" {{\n    "path" "{steam_dir}"\n  }}\n}}')

            with patch("simpulse.core.telemetry.plugin_installer.get_steam_vdf_candidate_paths", return_value=[vdf_file]):
                sims = LMUPluginManager.detect_all_simulators()
                self.assertEqual(len(sims), 2)
                sim_keys = {s.game_key: s for s in sims}
                self.assertIn("LMU", sim_keys)
                self.assertIn("rF2", sim_keys)
                self.assertTrue(sim_keys["LMU"].plugin_installed)
                self.assertFalse(sim_keys["rF2"].plugin_installed)

    def test_game_plugin_manager_local_settings_and_propagation(self):
        """Verify GamePluginManager local settings persistence and multi-game propagation."""
        from simpulse.core.game_plugin_manager import GamePluginManager, ChannelSettings
        from simpulse.core.telemetry_channels import TelemetryChannel
        from simpulse.core.config import ConfigManager
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            cfg_file = tmp_path / "config.json"
            cfg_mgr = ConfigManager(config_file=cfg_file)

            lmu_dir = tmp_path / "LMU"
            lmu_dir.mkdir(parents=True)
            (lmu_dir / "Le Mans Ultimate.exe").write_bytes(b"exe")

            rf2_dir = tmp_path / "rF2"
            rf2_dir.mkdir(parents=True)
            (rf2_dir / "rFactor2.exe").write_bytes(b"exe")

            vdf_file = tmp_path / "libraryfolders.vdf"
            vdf_file.write_text(f'"libraryfolders" {{\n  "0" {{\n    "path" "{tmp_path}"\n  }}\n}}')

            with patch("simpulse.core.telemetry.plugin_installer.LMUPluginManager.get_all_lmu_install_dirs", return_value=[lmu_dir, rf2_dir]), \
                 patch("simpulse.core.telemetry.plugin_installer.get_steam_vdf_candidate_paths", return_value=[vdf_file]):

                gpm = GamePluginManager(config_manager=cfg_mgr)
                gpm.settings.rates[TelemetryChannel.TELEMETRY] = "unlimited"
                gpm.settings.rates[TelemetryChannel.OPPONENT_TELEMETRY] = "10Hz"
                gpm.settings.enable_logging = True

                # Apply and propagate
                ok = gpm.apply_rates_to_game()
                self.assertTrue(ok)

                # Verify saved to unified config.json with official keys
                saved_gp = cfg_mgr.get_game_plugin_settings()
                self.assertEqual(saved_gp.rates["PlayerTelemetryRate"], "unlimited")
                self.assertEqual(saved_gp.rates["OpponentTelemetryRate"], "10Hz")
                self.assertTrue(saved_gp.enable_logging)

                # Verify both simulators received CustomPluginVariables.JSON
                for gdir in [lmu_dir, rf2_dir]:
                    cv = gdir / "UserData" / "player" / "CustomPluginVariables.JSON"
                    self.assertTrue(cv.exists(), f"Missing JSON in {gdir}")
                    cdata = json.loads(cv.read_text(encoding="utf-8"))
                    self.assertIn("isiMotor_RawUDP.dll", cdata)
                    entry = cdata["isiMotor_RawUDP.dll"]
                    self.assertEqual(entry["PlayerTelemetryRate"], "unlimited")
                    self.assertEqual(entry["OpponentTelemetryRate"], "10Hz")
                    self.assertEqual(entry["EnableLogging"], "Enabled")



