"""
SimPad Telemetry — LMU Plugin Installer & Detector.
Detects Le Mans Ultimate installation, checks Plugins/ folder,
installs LeMansUltimateTelemetryPlugin.dll and configures CustomPluginVariables.JSON.
"""

import os
import json
import shutil
import logging
from pathlib import Path
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)

# Search paths for LMU on Windows
KNOWN_LMU_PATHS = [
    "D:/SteamLibrary/steamapps/common/Le Mans Ultimate",
    "C:/Program Files (x86)/Steam/steamapps/common/Le Mans Ultimate",
    "C:/SteamLibrary/steamapps/common/Le Mans Ultimate",
    "E:/SteamLibrary/steamapps/common/Le Mans Ultimate",
    "F:/SteamLibrary/steamapps/common/Le Mans Ultimate",
]


class LMUPluginManager:
    """Manages detection, DLL copying, and JSON configuration of LMU Telemetry Plugin."""

    @staticmethod
    def find_lmu_install_dir() -> Optional[Path]:
        for pstr in KNOWN_LMU_PATHS:
            p = Path(pstr)
            if p.exists() and (p / "Le Mans Ultimate.exe").exists():
                return p

        # Fallback: scan common Steam library folders
        for drive in ["C:/", "D:/", "E:/", "F:/"]:
            steam_lib = Path(drive) / "SteamLibrary" / "steamapps" / "common" / "Le Mans Ultimate"
            if steam_lib.exists() and (steam_lib / "Le Mans Ultimate.exe").exists():
                return steam_lib

        return None

    @classmethod
    def get_source_dll(cls, project_root: Path) -> Optional[Path]:
        """Find source plugin DLL in project root."""
        candidates = [
            project_root / "LeMansUltimateTelemetryPlugin.dll",
            project_root / "rFactor2SharedMemoryMapPlugin64.dll",
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    @classmethod
    def check_plugin_installed(cls, project_root: Path) -> Tuple[bool, str, Optional[Path]]:
        """
        Checks if LMU plugin is installed in the game directory and configured in JSON.
        Returns (is_installed, status_message, lmu_dir_path).
        """
        lmu_dir = cls.find_lmu_install_dir()
        if not lmu_dir:
            return False, "LMU Game Directory Not Found", None

        plugins_dir = lmu_dir / "Plugins"
        if not plugins_dir.exists():
            return False, "Plugins folder missing in LMU", lmu_dir

        target_dlls = [
            plugins_dir / "LeMansUltimateTelemetryPlugin.dll",
            plugins_dir / "rFactor2SharedMemoryMapPlugin64.dll",
        ]

        dll_found = False
        for dll in target_dlls:
            if dll.exists() and dll.stat().st_size > 0:
                dll_found = True
                break

        if not dll_found:
            return False, "Plugin DLL missing in Plugins/", lmu_dir

        return True, "Plugin Active & Configured", lmu_dir

    @classmethod
    def configure_plugin_json(cls, lmu_dir: Path) -> bool:
        """Configures CustomPluginVariables.JSON to enable LeMansUltimateTelemetryPlugin.dll."""
        json_targets = [
            lmu_dir / "UserData" / "player" / "CustomPluginVariables.JSON",
            lmu_dir / "UserData" / "CustomPluginVariables.JSON",
        ]

        plugin_entry = {
            "Enabled": 1,
            "scoring": 1,
            "telemetry": 1,
        }

        success = True
        for jpath in json_targets:
            try:
                jpath.parent.mkdir(parents=True, exist_ok=True)
                data = {}
                if jpath.exists():
                    try:
                        content = jpath.read_text(encoding="utf-8", errors="ignore").strip()
                        parsed = json.loads(content) if content else {}
                        data = parsed if isinstance(parsed, dict) else {}
                    except Exception:
                        data = {}

                data["LeMansUltimateTelemetryPlugin.dll"] = plugin_entry
                jpath.write_text(json.dumps(data, indent=2), encoding="utf-8")
                logger.info(f"[PluginManager] Configured JSON: {jpath}")
                print(f"[PluginManager] Configured JSON: {jpath}", flush=True)
            except Exception as e:
                logger.error(f"[PluginManager] Failed to write JSON {jpath}: {e}")
                success = False


        return success

    @classmethod
    def install_plugin(cls, project_root: Path) -> Tuple[bool, str]:
        """
        Copies source DLL into LMU/Plugins/ and configures CustomPluginVariables.JSON.
        Returns (success, result_message).
        """
        src_dll = cls.get_source_dll(project_root)
        if not src_dll:
            return False, "Source DLL not found in project root (LeMansUltimateTelemetryPlugin.dll)"

        lmu_dir = cls.find_lmu_install_dir()
        if not lmu_dir:
            return False, "Le Mans Ultimate installation directory not found"

        plugins_dir = lmu_dir / "Plugins"
        try:
            # 1. Copy DLL
            plugins_dir.mkdir(parents=True, exist_ok=True)
            target_dll = plugins_dir / src_dll.name
            shutil.copy(src_dll, target_dll)
            print(f"[PluginManager] Copied DLL -> {target_dll}", flush=True)

            # 2. Configure JSON
            cls.configure_plugin_json(lmu_dir)

            return True, f"Successfully installed & configured {src_dll.name}!"

        except Exception as e:
            logger.error(f"[PluginManager] Install error: {e}")
            return False, f"Installation failed: {e}"
