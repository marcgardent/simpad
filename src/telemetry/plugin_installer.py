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

    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = Path(project_root) if project_root else self.get_project_root()

    @classmethod
    def get_project_root(cls) -> Path:
        """Returns default project root path."""
        return Path(__file__).resolve().parent.parent.parent

    @classmethod
    def get_all_lmu_install_dirs(cls) -> List[Path]:
        """Detects all LMU installation directories across Steam library paths."""
        found: List[Path] = []
        vdf_candidates = get_steam_vdf_candidate_paths()
        for vdf_path in vdf_candidates:
            if vdf_path.exists():
                lib_paths = parse_vdf_library_paths(vdf_path)
                for lib in lib_paths:
                    lmu_path = lib / "steamapps" / "common" / "Le Mans Ultimate"
                    if lmu_path.exists() and (lmu_path / "Le Mans Ultimate.exe").exists():
                        if lmu_path not in found:
                            found.append(lmu_path)

        for p in get_known_lmu_paths():
            if p.exists() and (p / "Le Mans Ultimate.exe").exists():
                if p not in found:
                    found.append(p)

        return found

    @staticmethod
    def find_lmu_install_dir() -> Optional[Path]:
        """Detects primary LMU installation directory."""
        dirs = LMUPluginManager.get_all_lmu_install_dirs()
        return dirs[0] if dirs else None

    @classmethod
    def get_source_dll(cls, project_root: Optional[Path] = None) -> Optional[Path]:
        """Find source plugin DLL in project root."""
        root = project_root or cls.get_project_root()
        candidate = root / "assets" / "plugins" / "lmu" / "LeMansUltimateTelemetryPlugin" / "LeMansUltimateTelemetryPlugin.dll"
        if candidate.exists():
            return candidate
        return None

    @classmethod
    def check_plugin_installed(cls, project_root: Optional[Path] = None) -> Tuple[bool, str, Optional[Path]]:
        """
        Checks if LMU plugin is installed in the game directory and configured in JSON.
        Returns (is_installed, status_message, lmu_dir_path).
        """
        lmu_dir = cls.find_lmu_install_dir()
        if not lmu_dir:
            return False, "LMU Game Directory Not Found", None

        plugins_dir = lmu_dir / "Plugins"
        target_dll = plugins_dir / "LeMansUltimateTelemetryPlugin.dll"
        if target_dll.exists() and target_dll.stat().st_size > 0:
            return True, "Plugin Active & Configured", lmu_dir

        return False, "Plugin DLL missing in Plugins/", lmu_dir

    @classmethod
    def configure_plugin_json(cls, lmu_dir: Path) -> bool:
        """Configures CustomPluginVariables.JSON to enable LeMansUltimateTelemetryPlugin.dll."""
        json_targets = [
            lmu_dir / "UserData" / "player" / "CustomPluginVariables.JSON",
            lmu_dir / "UserData" / "CustomPluginVariables.JSON",
        ]

        # Note: rFactor 2 / LMU engine uses " Enabled" (with leading space) and exact keys matched in main.cpp
        plugin_entry = {
            " Enabled": 1,
            "telemetry": 1,
            "scoring": 1,
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
                data["LeMansUltimateTelemetryPlugin"] = plugin_entry
                jpath.write_text(json.dumps(data, indent=2), encoding="utf-8")
                logger.info(f"[PluginManager] Configured JSON: {jpath}")
                print(f"[PluginManager] Configured JSON: {jpath}", flush=True)
            except Exception as e:
                logger.error(f"[PluginManager] Failed to write JSON {jpath}: {e}")
                success = False

        # Also configure Settings.JSON to enable plugin mask (Plugin Mask = 255, Enable external plugins = True)
        settings_paths = [
            lmu_dir / "UserData" / "player" / "Settings.JSON",
            lmu_dir / "UserData" / "Settings.JSON",
        ]
        for spath in settings_paths:
            if spath.exists():
                try:
                    content = spath.read_text(encoding="utf-8", errors="ignore").strip()
                    sdata = json.loads(content) if content else {}
                    if isinstance(sdata, dict):
                        sdata["Enable external plugins"] = True
                        sdata["Plugin Mask"] = 255
                        spath.write_text(json.dumps(sdata, indent=2), encoding="utf-8")
                        logger.info(f"[PluginManager] Configured Settings.JSON Plugin Mask: {spath}")
                except Exception as e:
                    logger.error(f"[PluginManager] Failed to update Settings.JSON {spath}: {e}")

        return success

    @classmethod
    def install_plugin(cls, project_root: Optional[Path] = None) -> Tuple[bool, str]:
        """
        Copies source DLL into LMU/Plugins/ and configures CustomPluginVariables.JSON.
        Returns (success, result_message).
        """
        root = project_root or cls.get_project_root()
        src_dll = cls.get_source_dll(root)
        if not src_dll:
            return False, f"Source DLL not found in project root ({root})"

        primary_dir = cls.find_lmu_install_dir()
        if not primary_dir:
            return False, "Le Mans Ultimate installation directory not found"

        lmu_dirs = cls.get_all_lmu_install_dirs()
        if primary_dir not in lmu_dirs:
            lmu_dirs.insert(0, primary_dir)

        installed_count = 0
        for lmu_dir in lmu_dirs:
            plugins_dir = lmu_dir / "Plugins"
            try:
                # 1. Copy DLL to Plugins/ and root folder
                plugins_dir.mkdir(parents=True, exist_ok=True)
                target_dll = plugins_dir / src_dll.name
                shutil.copy(src_dll, target_dll)
                root_dll = lmu_dir / src_dll.name
                shutil.copy(src_dll, root_dll)
                print(f"[PluginManager] Copied DLL -> {target_dll}", flush=True)

                # 2. Configure JSON
                cls.configure_plugin_json(lmu_dir)
                installed_count += 1
            except Exception as e:
                logger.error(f"[PluginManager] Install error for {lmu_dir}: {e}")

        # Also check Flatpak Steam UserData directory if present
        home = Path.home()
        flatpak_lmu = home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam" / "steamapps" / "common" / "Le Mans Ultimate"
        if flatpak_lmu.exists() and flatpak_lmu not in lmu_dirs:
            try:
                flatpak_plugins = flatpak_lmu / "Plugins"
                flatpak_plugins.mkdir(parents=True, exist_ok=True)
                shutil.copy(src_dll, flatpak_plugins / src_dll.name)
                cls.configure_plugin_json(flatpak_lmu)
            except Exception:
                pass

        if installed_count > 0:
            return True, f"Successfully installed & configured {src_dll.name}!"
        return False, "Installation failed"

    @classmethod
    def install_all(cls, project_root: Optional[Path] = None) -> dict:
        """
        Runs complete plugin installation workflow.
        Returns a dict with 'installed' (bool), 'message' (str), and 'lmu_dir' (Optional[Path]).
        """
        root = project_root or cls.get_project_root()
        success, message = cls.install_plugin(root)
        lmu_dir = cls.find_lmu_install_dir()
        return {
            "installed": success,
            "message": message,
            "lmu_dir": lmu_dir,
        }

