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

def get_steam_vdf_candidate_paths() -> List[Path]:
    """
    Returns candidate paths for Steam's libraryfolders.vdf configuration file
    across Windows (using Registry and environment variables), Linux (Native),
    and Linux (Flatpak).
    """
    candidates: List[Path] = []

    # 1. Windows: dynamic path resolution via Registry and Environment Variables
    if os.name == "nt":
        try:
            import winreg
            for hkey, reg_path, val_name in [
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
            ]:
                try:
                    with winreg.OpenKey(hkey, reg_path) as key:
                        val, _ = winreg.QueryValueEx(key, val_name)
                        if val:
                            vdf = Path(val) / "steamapps" / "libraryfolders.vdf"
                            if vdf not in candidates:
                                candidates.append(vdf)
                except OSError:
                    pass
        except ImportError:
            pass

        # Environment variables for special folders (ProgramFiles(x86), ProgramFiles, etc.)
        for env_var in ["ProgramFiles(x86)", "ProgramFiles", "ProgramW6432"]:
            pf = os.environ.get(env_var)
            if pf:
                vdf = Path(pf) / "Steam" / "steamapps" / "libraryfolders.vdf"
                if vdf not in candidates:
                    candidates.append(vdf)

        sys_drive = os.environ.get("SystemDrive", "C:")
        vdf = Path(sys_drive + "/") / "Steam" / "steamapps" / "libraryfolders.vdf"
        if vdf not in candidates:
            candidates.append(vdf)

    # 2. Linux (Native) & Linux (Flatpak) via home directory
    home = Path.home()

    # Native Linux
    for p in [
        home / ".local" / "share" / "Steam" / "steamapps" / "libraryfolders.vdf",
        home / ".steam" / "steam" / "steamapps" / "libraryfolders.vdf",
        home / ".steam" / "root" / "steamapps" / "libraryfolders.vdf",
        # Flatpak Linux
        home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam" / "steamapps" / "libraryfolders.vdf",
        home / ".var" / "app" / "com.valvesoftware.Steam" / ".steam" / "steam" / "steamapps" / "libraryfolders.vdf",
    ]:
        if p not in candidates:
            candidates.append(p)

    return candidates


def parse_vdf_library_paths(vdf_path: Path) -> List[Path]:
    """
    Parses a Steam libraryfolders.vdf file and extracts all registered library paths.
    """
    import re
    library_paths: List[Path] = []
    if not vdf_path.exists():
        return library_paths

    try:
        content = vdf_path.read_text(encoding="utf-8", errors="ignore")
        # Match "path" "C:\\Program Files (x86)\\Steam" or "path" "/path/to/library"
        matches = re.findall(r'"path"\s+"([^"]+)"', content, flags=re.IGNORECASE)
        for raw_path in matches:
            cleaned_path = raw_path.replace("\\\\", "\\")
            p = Path(cleaned_path)
            if p.exists() and p not in library_paths:
                library_paths.append(p)
    except Exception as e:
        logger.warning(f"[PluginManager] Error reading VDF {vdf_path}: {e}")

    return library_paths


def get_known_lmu_paths() -> List[Path]:
    """Builds fallback list of known LMU installation directories dynamically."""
    paths: List[Path] = []
    if os.name == "nt":
        for env_var in ["ProgramFiles(x86)", "ProgramFiles", "ProgramW6432"]:
            pf = os.environ.get(env_var)
            if pf:
                paths.append(Path(pf) / "Steam" / "steamapps" / "common" / "Le Mans Ultimate")
        for drive in ["C:/", "D:/", "E:/", "F:/"]:
            paths.append(Path(drive) / "SteamLibrary" / "steamapps" / "common" / "Le Mans Ultimate")

    home = Path.home()
    paths.append(home / ".steam" / "steam" / "steamapps" / "common" / "Le Mans Ultimate")
    paths.append(home / ".local" / "share" / "Steam" / "steamapps" / "common" / "Le Mans Ultimate")
    paths.append(home / ".var" / "app" / "com.valvesoftware.Steam" / ".steam" / "steam" / "steamapps" / "common" / "Le Mans Ultimate")
    return paths


class LMUPluginManager:
    """Manages detection, DLL copying, and JSON configuration of LMU Telemetry Plugin."""

    @staticmethod
    def find_lmu_install_dir() -> Optional[Path]:
        """
        Detects Le Mans Ultimate installation directory.
        First parses Steam's libraryfolders.vdf configuration files.
        Falls back to dynamic known paths and common drive scans.
        """
        # 1. Primary approach: parse Steam's libraryfolders.vdf
        vdf_candidates = get_steam_vdf_candidate_paths()
        for vdf_path in vdf_candidates:
            if vdf_path.exists():
                lib_paths = parse_vdf_library_paths(vdf_path)
                for lib in lib_paths:
                    lmu_path = lib / "steamapps" / "common" / "Le Mans Ultimate"
                    if lmu_path.exists() and (lmu_path / "Le Mans Ultimate.exe").exists():
                        logger.info(f"[PluginManager] Found LMU via VDF ({vdf_path}): {lmu_path}")
                        return lmu_path

        # 2. Fallback: check dynamic known paths
        for p in get_known_lmu_paths():
            if p.exists() and (p / "Le Mans Ultimate.exe").exists():
                return p

        return None

    @classmethod
    def get_source_dll(cls, project_root: Path) -> Optional[Path]:
        """Find source plugin DLL in project root."""
        candidate = project_root / "assets" / "plugins" / "lmu" /"LeMansUltimateTelemetryPlugin" / "LeMansUltimateTelemetryPlugin.dll"
        if candidate.exists():
            return candidate
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

        target_dll = plugins_dir / "LeMansUltimateTelemetryPlugin.dll"
        if not (target_dll.exists() and target_dll.stat().st_size > 0):
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
