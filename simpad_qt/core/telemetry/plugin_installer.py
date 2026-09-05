"""
SimPad Telemetry — LMU / isiMotor Plugin Installer & Detector.
Detects Le Mans Ultimate installation, downloads isiMotor-RawUDP-Plugin from GitHub Release,
installs isiMotor_RawUDP.dll into Plugins/ folder and configures CustomPluginVariables.JSON + Settings.JSON.
"""

import os
import io
import json
import shutil
import logging
import zipfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple, List, Dict

logger = logging.getLogger(__name__)

DEFAULT_PLUGIN_RELEASE_URL = "https://github.com/marcgardent/isiMotor-RawUDP-Plugin/releases/download/v0.3.0/isiMotor-RawUDP-Plugin-v0.3.0-Windows-x64-MinGW-w64.zip"
PLUGIN_DLL_NAME = "isiMotor_RawUDP.dll"

SUPPORTED_GAMES: Dict[str, Dict[str, str]] = { # TODO MGT on créer un type
    "LMU": {
        "name": "Le Mans Ultimate",
        "appid": "2399420",
        "subpath": "Le Mans Ultimate",
        "exe": "Le Mans Ultimate.exe",
    },
    "rF2": {
        "name": "rFactor 2",
        "appid": "365960",
        "subpath": "rFactor 2",
        "exe": "rFactor2.exe",
    },
}


@dataclass
class SimulatorInstallInfo:
    """Represents an installed simulator (LMU, rF2, etc.) and its plugin status."""
    game_key: str              # "LMU", "rF2"
    name: str                  # "Le Mans Ultimate", "rFactor 2"
    game_dir: Path
    exe_path: Path
    plugin_installed: bool
    status_message: str
    custom_variables_paths: List[Path] = field(default_factory=list)
    settings_paths: List[Path] = field(default_factory=list)


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


class LMUPluginManager:
    """Manages detection, remote download, DLL copying, and JSON configuration of isiMotor-RawUDP Plugin."""

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
        return found

    @classmethod
    def find_lmu_install_dir(cls) -> Optional[Path]:
        """Detects primary LMU installation directory."""
        dirs = cls.get_all_lmu_install_dirs()
        return dirs[0] if dirs else None

    @classmethod
    def download_and_extract_dll(
        cls,
        url: str = DEFAULT_PLUGIN_RELEASE_URL,
        dest_dir: Optional[Path] = None,
        timeout: float = 20.0,
    ) -> Optional[Path]:
        """
        Downloads the native plugin ZIP archive from GitHub Releases and extracts isiMotor_RawUDP.dll.
        """
        dest_dir = dest_dir or (cls.get_project_root() / "assets" / "plugins" / "isiMotor-RawUDP-Plugin")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_dll = dest_dir / PLUGIN_DLL_NAME

        try:
            logger.info(f"[PluginManager] Downloading plugin from {url}...")
            print(f"[PluginManager] Downloading plugin from {url}...", flush=True)
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "SimPad-PluginInstaller/0.1.2"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                zip_bytes = response.read()

            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                for member in zf.namelist():
                    if member.endswith(".dll") or member.lower() == PLUGIN_DLL_NAME.lower():
                        with zf.open(member) as src, open(dest_dll, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        logger.info(f"[PluginManager] Extracted {member} -> {dest_dll}")
                        print(f"[PluginManager] Extracted {member} -> {dest_dll}", flush=True)
                        return dest_dll

            logger.error(f"[PluginManager] DLL {PLUGIN_DLL_NAME} not found in zip archive")
            return None
        except Exception as e:
            logger.error(f"[PluginManager] Error downloading/extracting from {url}: {e}")
            print(f"[PluginManager] Error downloading plugin: {e}", flush=True)
            return None

    @classmethod
    def get_source_dll(
        cls,
        project_root: Optional[Path] = None,
        download_if_missing: bool = True,
        url: str = DEFAULT_PLUGIN_RELEASE_URL,
    ) -> Optional[Path]:
        """
        Locates the source plugin DLL in the project root or downloads it from the release URL if missing.
        """
        root = project_root or cls.get_project_root()

        # 1. Check primary modern directory
        candidate = root / "assets" / "plugins" / "isiMotor-RawUDP-Plugin" / PLUGIN_DLL_NAME
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate

        # 2. Check alternative plugin directories
        for sub in ["lmu", "isiMotor", ""]:
            c = root / "assets" / "plugins" / sub / PLUGIN_DLL_NAME
            if c.exists() and c.stat().st_size > 0:
                return c

        # 3. Download from GitHub release URL
        if download_if_missing:
            target_dir = root / "assets" / "plugins" / "isiMotor-RawUDP-Plugin"
            return cls.download_and_extract_dll(url=url, dest_dir=target_dir)

        return None

    @classmethod
    def check_plugin_installed(cls, project_root: Optional[Path] = None) -> Tuple[bool, str, Optional[Path]]:
        """
        Checks if the telemetry plugin is installed in the game directory and active.
        Returns (is_installed, status_message, lmu_dir_path).
        """
        lmu_dir = cls.find_lmu_install_dir()
        if not lmu_dir:
            return False, "LMU Game Directory Not Found", None

        plugins_dir = lmu_dir / "Plugins"

        # Check plugin DLL
        target_dll = plugins_dir / PLUGIN_DLL_NAME
        if target_dll.exists() and target_dll.stat().st_size > 0:
            return True, f"Plugin Active ({PLUGIN_DLL_NAME})", lmu_dir

        return False, "Plugin DLL missing in Plugins/", lmu_dir

    @classmethod
    def detect_all_simulators(cls) -> List[SimulatorInstallInfo]:
        """
        Detects all installed isiMotor / rFactor 2 / Le Mans Ultimate game directories.
        Strictly searches all Steam libraries.
        """
        results: List[SimulatorInstallInfo] = []
        vdf_candidates = get_steam_vdf_candidate_paths()
        all_lib_paths: List[Path] = []

        for vdf in vdf_candidates:
            if vdf.exists() and vdf.is_file():
                for lib in parse_vdf_library_paths(vdf):
                    if lib not in all_lib_paths:
                        all_lib_paths.append(lib)

        for game_key, info in SUPPORTED_GAMES.items():
            for lib in all_lib_paths:
                game_dir = lib / "steamapps" / "common" / info["subpath"]
                exe_path = game_dir / info["exe"]
                if game_dir.exists() and exe_path.exists():
                    try:
                        resolved_dir = game_dir.resolve()
                    except Exception:
                        resolved_dir = game_dir

                    if any(s.game_dir == resolved_dir for s in results):
                        continue

                    plugins_dir = resolved_dir / "Plugins"
                    target_dll = plugins_dir / PLUGIN_DLL_NAME
                    is_installed = target_dll.exists() and target_dll.stat().st_size > 0
                    msg = f"Plugin Active ({PLUGIN_DLL_NAME})" if is_installed else "Plugin Missing in Plugins/"

                    cv_paths: List[Path] = []
                    set_paths: List[Path] = []
                    for sub in ["UserData/player", "UserData"]:
                        p_cv = resolved_dir / sub / "CustomPluginVariables.JSON"
                        if p_cv.parent.exists():
                            cv_paths.append(p_cv)
                        p_set = resolved_dir / sub / "Settings.JSON"
                        if p_set.parent.exists():
                            set_paths.append(p_set)

                    results.append(SimulatorInstallInfo(
                        game_key=game_key,
                        name=info["name"],
                        game_dir=resolved_dir,
                        exe_path=exe_path,
                        plugin_installed=is_installed,
                        status_message=msg,
                        custom_variables_paths=cv_paths,
                        settings_paths=set_paths,
                    ))

        return results

    @classmethod
    def configure_plugin_json(
        cls,
        lmu_dir: Path,
        target_ip: str = "127.0.0.1",
        target_port: int = 5000,
        inbound_port: int = 5001,
        enable_logging: bool = False,
    ) -> bool:
        """
        Configures CustomPluginVariables.JSON and Settings.JSON to enable isiMotor_RawUDP streaming.
        """
        user_json = lmu_dir / "UserData" / "player" / "CustomPluginVariables.JSON"

        plugin_entry = {
            " Enabled": 1,
            "EnableLogging": "Enabled" if enable_logging else "Disabled",
            "TargetIP": str(target_ip),
            "TargetPort": str(target_port),
            "InboundControl": "Enabled",
            "InboundPort": str(inbound_port),
            "PlayerTelemetryRate": "unlimited",
            "OpponentTelemetryRate": "off",
            "CompactScoringRate": "10Hz",
            "FullScoringRate": "5Hz",
            "WeatherRate": "1Hz",
            "ExtendedStateRate": "5Hz",
            "ForceFeedbackRate": "unlimited",
            "GraphicsRate": "60Hz",
            "SystemEvents": "Enabled",
            "UnsubscribedBuffersMask": "0",
            "TrackRulesRate": "off",
            "PitMenuRate": "off",
        }

        success = True
        try:
            user_json.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if user_json.exists():
                try:
                    content = user_json.read_text(encoding="utf-8", errors="ignore").strip()
                    parsed = json.loads(content) if content else {}
                    data = parsed if isinstance(parsed, dict) else {}
                except Exception:
                    data = {}

            # Remove legacy unextended key for our plugin to prevent duplicate entries
            if "isiMotor_RawUDP" in data:
                del data["isiMotor_RawUDP"]

            data["isiMotor_RawUDP.dll"] = plugin_entry
            user_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
            logger.info(f"[PluginManager] Configured CustomPluginVariables.JSON: {user_json}")
            print(f"[PluginManager] Configured CustomPluginVariables.JSON: {user_json}", flush=True)
        except Exception as e:
            logger.error(f"[PluginManager] Failed to write JSON {user_json}: {e}")
            success = False

        # Configure Settings.JSON to enable external plugins
        settings_path = lmu_dir / "UserData" / "player" / "Settings.JSON"
        try:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            sdata = {}
            if settings_path.exists():
                try:
                    content = settings_path.read_text(encoding="utf-8", errors="ignore").strip()
                    parsed_s = json.loads(content) if content else {}
                    sdata = parsed_s if isinstance(parsed_s, dict) else {}
                except Exception:
                    sdata = {}
            sdata["Enable external plugins"] = True
            sdata["Plugin Mask"] = 255
            settings_path.write_text(json.dumps(sdata, indent=2), encoding="utf-8")
            logger.info(f"[PluginManager] Configured Settings.JSON Plugin Mask: {settings_path}")
        except Exception as e:
            logger.error(f"[PluginManager] Failed to update Settings.JSON {settings_path}: {e}")

        return success

    @classmethod
    def install_plugin(
        cls,
        project_root: Optional[Path] = None,
        url: str = DEFAULT_PLUGIN_RELEASE_URL,
    ) -> Tuple[bool, str]:
        """
        Retrieves source DLL (or downloads it from release URL), copies it into LMU/Plugins/ and configures JSON.
        Returns (success, result_message).
        """
        root = project_root or cls.get_project_root()
        src_dll = cls.get_source_dll(root, download_if_missing=True, url=url)
        if not src_dll or not src_dll.exists():
            return False, f"Unable to retrieve {PLUGIN_DLL_NAME} from {url} or local cache."

        lmu_dirs = cls.get_all_lmu_install_dirs()
        if not lmu_dirs:
            return False, "Le Mans Ultimate installation directory not found on system."

        installed_count = 0
        for lmu_dir in lmu_dirs:
            plugins_dir = lmu_dir / "Plugins"
            try:
                # 1. Copy DLL to Plugins/
                plugins_dir.mkdir(parents=True, exist_ok=True)
                target_dll = plugins_dir / src_dll.name
                shutil.copy(src_dll, target_dll)
                print(f"[PluginManager] Copied DLL -> {target_dll}", flush=True)

                # 2. Configure JSON
                cls.configure_plugin_json(lmu_dir)
                installed_count += 1
            except Exception as e:
                logger.error(f"[PluginManager] Install error for {lmu_dir}: {e}")

        if installed_count > 0:
            return True, f"Plugin {src_dll.name} successfully installed and configured!"
        return False, "Failed to install plugin."

    @classmethod
    def install_all(
        cls,
        project_root: Optional[Path] = None,
        url: str = DEFAULT_PLUGIN_RELEASE_URL,
    ) -> dict:
        """
        Runs complete plugin installation workflow.
        Returns a dict with 'installed' (bool), 'message' (str), and 'lmu_dir' (Optional[Path]).
        """
        root = project_root or cls.get_project_root()
        success, message = cls.install_plugin(root, url=url)
        lmu_dir = cls.find_lmu_install_dir()
        return {
            "installed": success,
            "message": message,
            "lmu_dir": lmu_dir,
        }


