"""
SimPad Qt6 Game Telemetry Plugin Installer & Channel Configuration Hub.
Manages native isiMotor_RawUDP.dll installation, CustomPluginVariables.JSON,
Settings.JSON, and channel frequency negotiation with SimPad plugins.
"""

from __future__ import annotations
import json
import shutil
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal

from simpad_qt.core.telemetry_channels import TelemetryChannel, ChannelRequirement
from src.telemetry.plugin_installer import LMUPluginManager, SimulatorInstallInfo

logger = logging.getLogger("simpad.game_plugin_manager")


@dataclass
class GamePluginInstallationState:
    """Status of the primary game telemetry plugin installation (for backwards compatibility)."""
    game_found: bool = False
    game_dir: Optional[Path] = None
    plugin_installed: bool = False
    status_message: str = "Unverified"
    plugin_variables_path: Optional[Path] = None


@dataclass
class ChannelSettings:
    """Strongly-typed rates configuration for all telemetry channels."""
    target_ip: str = "127.0.0.1"
    target_port: int = 5000
    inbound_port: int = 5001
    enable_logging: bool = False
    rates: Dict[TelemetryChannel, str] = field(default_factory=lambda: {
        TelemetryChannel.TELEMETRY: "unlimited",
        TelemetryChannel.OPPONENT_TELEMETRY: "off",
        TelemetryChannel.COMPACT_SCORING: "10Hz",
        TelemetryChannel.FULL_SCORING: "5Hz",
        TelemetryChannel.WEATHER: "1Hz",
        TelemetryChannel.EXTENDED_STATE: "10Hz",
        TelemetryChannel.FORCE_FEEDBACK: "off",
        TelemetryChannel.GRAPHICS: "off",
        TelemetryChannel.TRACK_RULES: "off",
        TelemetryChannel.PIT_MENU: "off",
        TelemetryChannel.SYSTEM_EVENTS: "Enabled",
    })

    def to_dict(self) -> dict:
        return {
            "target_ip": self.target_ip,
            "target_port": self.target_port,
            "inbound_port": self.inbound_port,
            "enable_logging": self.enable_logging,
            "rates": {ch.name: val for ch, val in self.rates.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> ChannelSettings:
        settings = cls(
            target_ip=data.get("target_ip", "127.0.0.1"),
            target_port=int(data.get("target_port", 5000)),
            inbound_port=int(data.get("inbound_port", 5001)),
            enable_logging=bool(data.get("enable_logging", False)),
        )
        rates_dict = data.get("rates", {})
        for ch in TelemetryChannel:
            # Check by Enum member name or Enum value or json variable name
            val = rates_dict.get(ch.name, rates_dict.get(ch.value, rates_dict.get(ch.json_variable_name)))
            if val is not None:
                settings.rates[ch] = str(val)
        return settings


class GamePluginManager(QObject):
    """
    Manages detection, multi-simulator DLL deployment, local settings persistence,
    and JSON rate configuration across all supported simulators (Le Mans Ultimate, rFactor 2).
    """

    state_changed = Signal()
    rates_applied = Signal()

    LOCAL_SETTINGS_PATH = Path("config") / "game_plugin_settings.json"

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.settings = ChannelSettings()
        self.state = GamePluginInstallationState()
        self.simulators: List[SimulatorInstallInfo] = []
        
        self.refresh_installation_state()
        self.load_local_settings()

    def refresh_installation_state(self) -> GamePluginInstallationState:
        """Scan system for all supported game installations (LMU, rFactor 2) and DLL presence."""
        self.simulators = LMUPluginManager.detect_all_simulators()

        # Update primary state (LMU prioritized, or first detected sim)
        lmu_sim = next((s for s in self.simulators if s.game_key == "LMU"), None)
        primary_sim = lmu_sim or (self.simulators[0] if self.simulators else None)

        if not primary_sim:
            self.state = GamePluginInstallationState(
                game_found=False,
                game_dir=None,
                plugin_installed=False,
                status_message="No supported simulators found in Steam libraries.",
                plugin_variables_path=None,
            )
        else:
            vars_path = primary_sim.custom_variables_paths[0] if primary_sim.custom_variables_paths else None
            self.state = GamePluginInstallationState(
                game_found=True,
                game_dir=primary_sim.game_dir,
                plugin_installed=primary_sim.plugin_installed,
                status_message=primary_sim.status_message,
                plugin_variables_path=vars_path,
            )

        self.state_changed.emit()
        return self.state

    def load_local_settings(self) -> None:
        """
        Load preferences locally from SimPad's persistent storage.
        If local file doesn't exist, try importing from the first detected simulator JSON.
        """
        if self.LOCAL_SETTINGS_PATH.exists():
            try:
                content = self.LOCAL_SETTINGS_PATH.read_text(encoding="utf-8", errors="ignore")
                data = json.loads(content)
                self.settings = ChannelSettings.from_dict(data)
                logger.info(f"Loaded local game plugin preferences from {self.LOCAL_SETTINGS_PATH}")
                return
            except Exception as e:
                logger.warning(f"Failed to read local settings {self.LOCAL_SETTINGS_PATH}: {e}")

        # Fallback: Check if any detected simulator already has custom variables
        for sim in self.simulators:
            for cv_path in sim.custom_variables_paths:
                if cv_path.exists():
                    try:
                        content = cv_path.read_text(encoding="utf-8", errors="ignore")
                        data = json.loads(content)
                        entry = data.get("isiMotor_RawUDP.dll", data.get("isiMotor_RawUDP", {}))
                        if isinstance(entry, dict):
                            self.settings.target_ip = entry.get("TargetIP", "127.0.0.1")
                            self.settings.target_port = int(entry.get("TargetPort", 5000))
                            self.settings.inbound_port = int(entry.get("InboundPort", 5001))
                            log_val = str(entry.get("EnableLogging", "Disabled")).lower()
                            self.settings.enable_logging = log_val in ("enabled", "1", "true")

                            for channel in TelemetryChannel:
                                var_name = channel.json_variable_name
                                if var_name in entry:
                                    self.settings.rates[channel] = entry[var_name]

                            self.save_local_settings()
                            logger.info(f"Initialized local settings from {cv_path}")
                            return
                    except Exception as e:
                        logger.warning(f"Failed to import initial rates from {cv_path}: {e}")

    def save_local_settings(self) -> bool:
        """Persist current preferences locally in SimPad storage."""
        try:
            self.LOCAL_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            self.LOCAL_SETTINGS_PATH.write_text(
                json.dumps(self.settings.to_dict(), indent=2), encoding="utf-8"
            )
            logger.info(f"Saved local game plugin settings to {self.LOCAL_SETTINGS_PATH}")
            return True
        except Exception as e:
            logger.error(f"Failed to save local settings {self.LOCAL_SETTINGS_PATH}: {e}")
            return False

    def install_plugin_for_simulator(self, sim: SimulatorInstallInfo) -> Tuple[bool, str]:
        """Install DLL and configure JSON for a specific detected simulator."""
        src_dll = LMUPluginManager.get_source_dll(download_if_missing=True)
        if not src_dll or not src_dll.exists():
            return False, "Plugin DLL source binary not found."

        try:
            plugins_dir = sim.game_dir / "Plugins"
            plugins_dir.mkdir(parents=True, exist_ok=True)
            target_dll = plugins_dir / src_dll.name
            shutil.copy(src_dll, target_dll)

            self.apply_rates_to_game()
            self.refresh_installation_state()
            return True, f"Installed {src_dll.name} to {sim.name} ({sim.game_dir})"
        except Exception as e:
            logger.error(f"Failed to install DLL to {sim.game_dir}: {e}")
            return False, str(e)

    def install_plugin_dll(self) -> Tuple[bool, str]:
        """Install native DLL and configure JSON across ALL detected simulators."""
        if not self.simulators:
            self.refresh_installation_state()

        if not self.simulators:
            return False, "No simulator installations found to deploy plugin."

        installed_count = 0
        errors = []
        for sim in self.simulators:
            ok, msg = self.install_plugin_for_simulator(sim)
            if ok:
                installed_count += 1
            else:
                errors.append(f"{sim.name}: {msg}")

        self.refresh_installation_state()
        if installed_count > 0:
            err_suffix = f" (Errors: {', '.join(errors)})" if errors else ""
            return True, f"Plugin deployed to {installed_count} simulator(s){err_suffix}."
        return False, f"Installation failed: {'; '.join(errors)}"

    def apply_rates_to_game(self) -> bool:
        """
        1. Saves settings locally in SimPad.
        2. Writes current ChannelSettings to CustomPluginVariables.JSON and Settings.JSON
           across ALL detected simulator directories.
        """
        # Save local preferences first
        self.save_local_settings()

        # Collect all unique game directories
        target_dirs: List[Path] = [s.game_dir for s in self.simulators]
        for extra in LMUPluginManager.get_all_lmu_install_dirs():
            if extra not in target_dirs:
                target_dirs.append(extra)

        if not target_dirs:
            logger.warning("No simulator directories found to apply rates.")
            return True  # Saved locally successfully

        try:
            for gdir in target_dirs:
                for sub in ["UserData/player", "UserData"]:
                    user_json = gdir / sub / "CustomPluginVariables.JSON"
                    user_json.parent.mkdir(parents=True, exist_ok=True)

                    data = {}
                    if user_json.exists():
                        try:
                            data = json.loads(user_json.read_text(encoding="utf-8", errors="ignore"))
                        except Exception:
                            data = {}

                    plugin_entry = {
                        " Enabled": 1,
                        "EnableLogging": "Enabled" if self.settings.enable_logging else "Disabled",
                        "TargetIP": str(self.settings.target_ip),
                        "TargetPort": str(self.settings.target_port),
                        "InboundControl": "Enabled",
                        "InboundPort": str(self.settings.inbound_port),
                        "UnsubscribedBuffersMask": "0",
                    }

                    for channel, rate_val in self.settings.rates.items():
                        plugin_entry[channel.json_variable_name] = rate_val

                    # Remove legacy unextended key for our plugin to prevent duplicate entries
                    if "isiMotor_RawUDP" in data:
                        del data["isiMotor_RawUDP"]

                    data["isiMotor_RawUDP.dll"] = plugin_entry
                    user_json.write_text(json.dumps(data, indent=2), encoding="utf-8")

                # Update Settings.JSON
                for sub in ["UserData/player", "UserData"]:
                    settings_path = gdir / sub / "Settings.JSON"
                    if settings_path.parent.exists():
                        sdata = {}
                        if settings_path.exists():
                            try:
                                sdata = json.loads(settings_path.read_text(encoding="utf-8", errors="ignore"))
                            except Exception:
                                sdata = {}
                        sdata["Enable external plugins"] = True
                        sdata["Plugin Mask"] = 255
                        settings_path.write_text(json.dumps(sdata, indent=2), encoding="utf-8")

            logger.info(f"Successfully propagated channel rates to {len(target_dirs)} simulator installation(s).")
            self.rates_applied.emit()
            return True
        except Exception as e:
            logger.error(f"Failed to apply channel rates to game JSON: {e}")
            return False

    def compute_recommended_rates(
        self, requirements: Dict[str, List[ChannelRequirement]]
    ) -> Dict[TelemetryChannel, str]:
        """
        Aggregate channel requirements from all active plugins and determine the optimal rates.
        Selects the highest requested frequency for each channel.
        """
        recommended: Dict[TelemetryChannel, str] = {
            ch: "off" for ch in TelemetryChannel
        }
        recommended[TelemetryChannel.SYSTEM_EVENTS] = "Enabled"

        # Channel Hz mappings
        for plugin_id, req_list in requirements.items():
            for req in req_list:
                ch = req.channel
                avail = ch.available_rates
                if ch == TelemetryChannel.SYSTEM_EVENTS:
                    recommended[ch] = "Enabled"
                    continue

                req_hz = req.preferred_hz
                current_rate = recommended[ch]

                # Map numerical Hz to closest available rate string
                chosen_rate = "off"
                if req_hz >= 100 and "unlimited" in avail:
                    chosen_rate = "unlimited"
                elif req_hz >= 60 and "60Hz" in avail:
                    chosen_rate = "60Hz"
                elif req_hz >= 50 and "50Hz" in avail:
                    chosen_rate = "50Hz"
                elif req_hz >= 20 and "20Hz" in avail:
                    chosen_rate = "20Hz"
                elif req_hz >= 10 and "10Hz" in avail:
                    chosen_rate = "10Hz"
                elif req_hz >= 5 and "5Hz" in avail:
                    chosen_rate = "5Hz"
                elif req_hz >= 2 and "2Hz" in avail:
                    chosen_rate = "2Hz"
                elif req_hz >= 1 and "1Hz" in avail:
                    chosen_rate = "1Hz"
                elif req_hz > 0:
                    chosen_rate = avail[-2] if len(avail) > 1 else "off"

                # Check if this requirement is higher than current
                def _rate_to_num(r: str) -> int:
                    if r == "unlimited": return 1000
                    if r == "off" or r == "Disabled": return 0
                    if r == "Enabled": return 1
                    return int(r.replace("Hz", "").replace(".5", "0"))

                if _rate_to_num(chosen_rate) > _rate_to_num(current_rate):
                    recommended[ch] = chosen_rate

        return recommended
