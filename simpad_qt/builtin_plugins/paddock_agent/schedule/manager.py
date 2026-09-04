"""
SimPad Official LMU Race Schedule & Notification Engine.
Direct integration with the official LMU API (https://api.lmuschedule.com/racingschedules).
Management and activation by SETUP <Level> <Classes> <Circuit> with collision-free FIFO audio broadcasting.
"""

import os
import sys
import time
import json
import shutil
import logging
import datetime
import threading
import subprocess
import urllib.request
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple, Set, Callable, Union

from simpad_qt.core.utils.audio import AudioAnnouncer

logger = logging.getLogger(__name__)

SetupConfigScalar = Union[str, int, bool]
NotificationLogEntry = Dict[str, str]
TriggeredAlertDict = Dict[str, Union[str, float]]
JSONScheduleSeries = Dict[str, Union[str, int, float, bool, list, dict]]

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
DEFAULT_SCHEDULE_CONFIG_PATH = _PROJECT_ROOT / "schedule_config.json"
DEFAULT_CACHE_PATH = _PROJECT_ROOT / "lmu_schedule_cache.json"
API_URL = "https://api.lmuschedule.com/racingschedules"

API_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "content-type": "application/json",
    "dnt": "1",
    "origin": "https://www.lmuschedule.com",
    "priority": "u=1, i",
    "referer": "https://www.lmuschedule.com/",
    "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Linux"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
}


def clean_series_key(name: str) -> str:
    """Generates a normalized identification key for a string."""
    return name.lower().replace(" ", "_").replace("-", "_").replace("(", "").replace(")", "").replace(",", "").strip("_")


def make_setup_key(difficulty: str, car_classes: str, circuit: str) -> str:
    """Generates unique key for a Setup <Level><Classes><Circuit>."""
    return clean_series_key(f"{difficulty}_{car_classes}_{circuit}")


@dataclass
class RaceSetupConfig:
    """Individual configuration for each Setup <Level><Classes><Circuit>."""
    setup_id: str                         # Unique key (e.g. "lmgt3_fixed" or "beginner_gt3_fuji_wec")
    difficulty: str = "Beginner"          # <Level> : "Beginner", "Intermediate", "Advanced", "Weekly"
    car_classes: str = "GT3"              # <Classes> : "GT3", "LMP2 (ELMS), LMP3, GT3", "HYP, GT3"
    circuit: str = ""                     # <Circuit> : "Fuji (WEC)", "Silverstone (ELMS)"
    series_name: str = ""                 # Series name (e.g. "LMGT3 Fixed")
    race_type: str = "Daily Races"        # "Daily Races", "Weekly Races"
    tier_category: str = "Bronze"         # "Bronze", "Silver", "Gold", "Weekly"
    race_length_min: int = 20             # Duration in minutes
    setup_type: str = "fixed"             # "fixed" or "open"
    enabled: bool = False                 # Default: Unchecked
    notify_15m: bool = False              # Default: Unchecked
    notify_10m: bool = False              # Default: Unchecked
    notify_5m: bool = False               # Default: Unchecked
    notify_1m: bool = False               # Default: Unchecked
    notify_reg_open: bool = False         # Default: Unchecked
    notify_start: bool = False            # Default: Unchecked
    sound_key: str = ""                   # Primary audio key

    # Backward compatible alias
    @property
    def race_id(self) -> str:
        return self.setup_id

    @property
    def name(self) -> str:
        return self.series_name or self.display_title

    @property
    def display_title(self) -> str:
        """Clear standardized title: <Level> • <Classes> • <Circuit>"""
        return f"[{self.difficulty}] {self.car_classes} @ {self.circuit}"

    def __post_init__(self):
        if not self.sound_key:
            self.sound_key = clean_series_key(self.series_name) if self.series_name else self.setup_id

    def to_dict(self) -> Dict[str, SetupConfigScalar]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, SetupConfigScalar]) -> "RaceSetupConfig":
        # Backward compatibility with legacy configuration keys
        mapped_data = dict(data)
        if "race_id" in mapped_data and "setup_id" not in mapped_data:
            mapped_data["setup_id"] = mapped_data["race_id"]
        if "name" in mapped_data and not mapped_data.get("series_name"):
            mapped_data["series_name"] = mapped_data["name"]
        return cls(**{k: v for k, v in mapped_data.items() if k in cls.__dataclass_fields__})


# Backward compatible alias
RaceTierConfig = RaceSetupConfig


@dataclass
class RaceEvent:
    """LMU race session dynamically generated for a Setup <Level><Classes><Circuit>."""
    setup_id: str                         # Setup unique key
    series_name: str                      # Series name (e.g. "LMGT3 Fixed")
    difficulty: str                       # <Level> : "Beginner", "Intermediate", "Advanced", "Weekly"
    car_classes: str                      # <Classes> : "GT3", "LMP2", etc.
    track_name: str                       # <Circuit> : "Fuji (WEC)", etc.
    tier_category: str                    # "Bronze", "Silver", "Gold", "Weekly"
    start_time: float                     # Race start epoch timestamp
    end_time: float                       # Race end epoch timestamp
    reg_open_time: float                  # Registration open epoch timestamp (T-15 min)
    setup_type: str                       # "fixed", "open"
    race_length_min: int                  # Duration in minutes
    status: str                           # "UPCOMING", "REGISTRATION_OPEN", "IN_PROGRESS", "FINISHED"
    time_until_start: float               # Seconds remaining before start
    time_until_reg: float                 # Seconds remaining before registration

    # Backward compatible alias
    @property
    def race_id(self) -> str:
        return self.setup_id

    @property
    def race_type(self) -> str:
        if self.tier_category == "Weekly" or "weekly" in self.series_name.lower():
            return "Weekly Races"
        return "Daily Races"

    @property
    def start_time_str(self) -> str:
        dt = datetime.datetime.fromtimestamp(self.start_time)
        return dt.strftime("%H:%M")

    @property
    def reg_open_time_str(self) -> str:
        dt = datetime.datetime.fromtimestamp(self.reg_open_time)
        return dt.strftime("%H:%M")

    @property
    def countdown_str(self) -> str:
        if self.time_until_start > 0:
            total_sec = int(self.time_until_start)
            hours = total_sec // 3600
            mins = (total_sec % 3600) // 60
            secs = total_sec % 60
            if hours > 0:
                return f"{hours:02d}h {mins:02d}m {secs:02d}s"
            return f"{mins:02d}m {secs:02d}s"
        elif self.time_until_start > -(self.end_time - self.start_time):
            elapsed = int(-self.time_until_start)
            return f"In progress ({elapsed // 60}m)"
        else:
            return "Finished"


# Default 10 official LMU Setups repository
DEFAULT_RACE_SETUPS: Dict[str, RaceSetupConfig] = {
    "lmgt3_fixed": RaceSetupConfig(
        setup_id="lmgt3_fixed",
        difficulty="Beginner",
        car_classes="GT3",
        circuit="Fuji (WEC)",
        series_name="LMGT3 Fixed",
        race_type="Daily Races",
        tier_category="Bronze",
        race_length_min=20,
        setup_type="fixed",
        sound_key="lmgt3_fixed",
    ),
    "lmp3_fixed": RaceSetupConfig(
        setup_id="lmp3_fixed",
        difficulty="Beginner",
        car_classes="LMP3",
        circuit="Portimao (WEC)",
        series_name="LMP3 Fixed",
        race_type="Daily Races",
        tier_category="Bronze",
        race_length_min=20,
        setup_type="fixed",
        sound_key="lmp3_fixed",
    ),
    "lmgte_fixed": RaceSetupConfig(
        setup_id="lmgte_fixed",
        difficulty="Beginner",
        car_classes="GTE",
        circuit="Bahrain (WEC)",
        series_name="LMGTE Fixed",
        race_type="Daily Races",
        tier_category="Bronze",
        race_length_min=20,
        setup_type="fixed",
        sound_key="lmgte_fixed",
    ),
    "elms_sprint_trophy": RaceSetupConfig(
        setup_id="elms_sprint_trophy",
        difficulty="Intermediate",
        car_classes="LMP2 (ELMS), LMP3, GT3",
        circuit="Silverstone (ELMS)",
        series_name="ELMS Sprint Trophy",
        race_type="Daily Races",
        tier_category="Silver",
        race_length_min=30,
        setup_type="open",
        sound_key="elms_sprint_trophy",
    ),
    "lmgt3_sprint_cup": RaceSetupConfig(
        setup_id="lmgt3_sprint_cup",
        difficulty="Intermediate",
        car_classes="GT3",
        circuit="Barcelona (ELMS)",
        series_name="LMGT3 Sprint Cup",
        race_type="Daily Races",
        tier_category="Silver",
        race_length_min=30,
        setup_type="open",
        sound_key="lmgt3_sprint_cup",
    ),
    "prototype_classic": RaceSetupConfig(
        setup_id="prototype_classic",
        difficulty="Intermediate",
        car_classes="LMP2, GTE",
        circuit="Spa-Francorchamps (ELMS)",
        series_name="Prototype Classic",
        race_type="Daily Races",
        tier_category="Silver",
        race_length_min=30,
        setup_type="open",
        sound_key="prototype_classic",
    ),
    "one_stint_sprint": RaceSetupConfig(
        setup_id="one_stint_sprint",
        difficulty="Advanced",
        car_classes="HYP, GT3",
        circuit="Le Mans (WEC)",
        series_name="One Stint Sprint",
        race_type="Daily Races",
        tier_category="Gold",
        race_length_min=40,
        setup_type="open",
        sound_key="one_stint_sprint",
    ),
    "elms_super_60": RaceSetupConfig(
        setup_id="elms_super_60",
        difficulty="Advanced",
        car_classes="LMP2 (ELMS), LMP3, GT3",
        circuit="Spa-Francorchamps (Endurance)",
        series_name="ELMS Super 60",
        race_type="Daily Races",
        tier_category="Gold",
        race_length_min=60,
        setup_type="open",
        sound_key="elms_super_60",
    ),
    "wec_xperience": RaceSetupConfig(
        setup_id="wec_xperience",
        difficulty="Advanced",
        car_classes="HYP, LMP2, GT3",
        circuit="Daytona (RC)",
        series_name="WEC-Xperience",
        race_type="Daily Races",
        tier_category="Gold",
        race_length_min=60,
        setup_type="open",
        sound_key="wec_xperience",
    ),
    "wec_weekly": RaceSetupConfig(
        setup_id="wec_weekly",
        difficulty="Weekly",
        car_classes="HYP, GT3",
        circuit="Portimao (ELMS)",
        series_name="WEC Weekly",
        race_type="Weekly Races",
        tier_category="Weekly",
        race_length_min=90,
        setup_type="open",
        sound_key="wec_weekly",
    ),
}

DEFAULT_RACE_TIERS = DEFAULT_RACE_SETUPS


class LMUScheduleClient:
    """API client to fetch official Le Mans Ultimate race schedule."""

    @staticmethod
    def fetch_remote_schedule(timeout: int = 8) -> Optional[List[JSONScheduleSeries]]:
        """Performs HTTPS request to api.lmuschedule.com."""
        try:
            req = urllib.request.Request(API_URL, headers=API_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    body = data.get("body", []) if isinstance(data, dict) else data
                    if isinstance(body, list) and len(body) > 0:
                        return body
        except Exception as e:
            logger.warning(f"[LMUScheduleClient] Fetch error from {API_URL}: {e}")
        return None

    @staticmethod
    def load_cached_schedule(cache_file: Path = DEFAULT_CACHE_PATH) -> List[JSONScheduleSeries]:
        """Loads schedule data cached on disk."""
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"[LMUScheduleClient] Error loading cache {cache_file}: {e}")
        return []

    @staticmethod
    def save_cached_schedule(data: List[JSONScheduleSeries], cache_file: Path = DEFAULT_CACHE_PATH) -> None:
        """Saves schedule data to local cache."""
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"[LMUScheduleClient] Error saving cache {cache_file}: {e}")


class LMUScheduleManager:
    """
    Central schedule and notification manager for each SETUP <Level><Classes><Circuit>.
    Allows globally enabling/disabling a Setup (which applies to all its recurring slots).
    """

    def __init__(
        self,
        config_file: Path = DEFAULT_SCHEDULE_CONFIG_PATH,
        cache_file: Path = DEFAULT_CACHE_PATH,
        auto_fetch: bool = True
    ):
        self.config_file = config_file
        self.cache_file = cache_file
        self.master_enabled: bool = True
        self.audio_enabled: bool = True
        self.desktop_notifications_enabled: bool = True
        self.setups: Dict[str, RaceSetupConfig] = {}
        self.notification_history: List[NotificationLogEntry] = []
        self._fired_alerts: Set[Tuple[str, str, int, str]] = set()  # (setup_id, series_name, slot_ts, alert_type)
        self._raw_series_data: List[JSONScheduleSeries] = []
        self.last_sync_time: float = 0.0
        self.api_status: str = "Initializing..."

        # Initialize configurations
        self.load_config()

        # Initial local cache loading
        cached = LMUScheduleClient.load_cached_schedule(self.cache_file)
        if cached:
            self._raw_series_data = cached
            self._sync_setups_from_raw()
            self.api_status = f"Connected ({len(cached)} Setups loaded)"

        if auto_fetch:
            self.refresh_api_async()

    # Backward compatible alias
    @property
    def races(self) -> Dict[str, RaceSetupConfig]:
        return self.setups

    @races.setter
    def races(self, val: Dict[str, RaceSetupConfig]):
        self.setups = val

    def _sync_setups_from_raw(self) -> None:
        """Dynamically synchronizes Setups <Level><Classes><Circuit> from API."""
        for item in self._raw_series_data:
            s_name = item.get("series", "")
            diff = item.get("difficulty", "Beginner")
            race_type = item.get("raceType", "Daily Races")
            circuit = item.get("circuit", "")
            car_classes = ", ".join(item.get("carClasses", []))
            setup_type = item.get("setup", "fixed")
            race_len = item.get("raceLength", 20)

            # Setup identification
            s_id = clean_series_key(s_name) if s_name else make_setup_key(diff, car_classes, circuit)
            tier_cat = "Bronze" if diff == "Beginner" else ("Silver" if diff == "Intermediate" else ("Weekly" if race_type == "Weekly Races" else "Gold"))

            if s_id in self.setups:
                # Update metadata
                self.setups[s_id].circuit = circuit
                self.setups[s_id].car_classes = car_classes
                self.setups[s_id].difficulty = diff if race_type != "Weekly Races" else "Weekly"
                self.setups[s_id].race_length_min = race_len
                self.setups[s_id].setup_type = setup_type
                self.setups[s_id].series_name = s_name
            else:
                # Add new Setup unchecked by default
                self.setups[s_id] = RaceSetupConfig(
                    setup_id=s_id,
                    difficulty=diff if race_type != "Weekly Races" else "Weekly",
                    car_classes=car_classes,
                    circuit=circuit,
                    series_name=s_name,
                    race_type=race_type,
                    tier_category=tier_cat,
                    race_length_min=race_len,
                    setup_type=setup_type,
                    enabled=False,
                    notify_15m=False,
                    notify_10m=False,
                    notify_5m=False,
                    notify_1m=False,
                    notify_reg_open=False,
                    notify_start=False,
                    sound_key=s_id,
                )

    def sync_api(self) -> bool:
        """Synchronously updates data from API. Returns True on success."""
        try:
            data = LMUScheduleClient.fetch_remote_schedule()
            if data:
                self._raw_series_data = data
                self._sync_setups_from_raw()
                self.last_sync_time = time.time()
                self.api_status = f"Live ({len(data)} active Setups)"
                LMUScheduleClient.save_cached_schedule(data, self.cache_file)
                self.save_config()
                logger.info(f"[LMUScheduleManager] Refreshed {len(data)} race setups from API.")
                return True
            else:
                if not self._raw_series_data:
                    self.api_status = "Offline (Local Cache)"
                return False
        except Exception as e:
            logger.warning(f"[LMUScheduleManager] Error in sync_api: {e}")
            return False

    def refresh_api_async(
        self,
        callback: Optional[Callable[[bool], None]] = None,
        on_done: Optional[Callable[[bool], None]] = None
    ) -> None:
        """Updates API data in the background without blocking the application."""
        cb = callback or on_done

        def _worker():
            ok = self.sync_api()
            if cb:
                cb(ok)

        threading.Thread(target=_worker, daemon=True, name="LMUScheduleFetchThread").start()

    def load_config(self) -> None:
        """Loads user Setups configuration."""
        self.setups = {k: RaceSetupConfig.from_dict(v.to_dict()) for k, v in DEFAULT_RACE_SETUPS.items()}

        if not self.config_file.exists():
            self.save_config()
            return

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.master_enabled = data.get("master_enabled", True)
                self.audio_enabled = data.get("audio_enabled", True)
                self.desktop_notifications_enabled = data.get("desktop_notifications_enabled", True)

                # Loads setups or backward compatible "races"
                setups_data = data.get("setups", data.get("races", {}))
                for s_id, s_conf in setups_data.items():
                    if s_id in self.setups:
                        self.setups[s_id] = RaceSetupConfig.from_dict(s_conf)
                    else:
                        self.setups[s_id] = RaceSetupConfig.from_dict(s_conf)
        except Exception as e:
            logger.warning(f"[LMUScheduleManager] Error loading config {self.config_file}: {e}")

    def save_config(self) -> None:
        """Saves current Setups configuration."""
        try:
            data = {
                "master_enabled": self.master_enabled,
                "audio_enabled": self.audio_enabled,
                "desktop_notifications_enabled": self.desktop_notifications_enabled,
                "setups": {k: v.to_dict() for k, v in self.setups.items()},
                "races": {k: v.to_dict() for k, v in self.setups.items()},  # alias
            }
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.warning(f"[LMUScheduleManager] Error saving config {self.config_file}: {e}")

    def enable_all_races(self, enabled: bool = True) -> None:
        """Enables or disables all Setups with a single click."""
        for cfg in self.setups.values():
            cfg.enabled = enabled
        self.save_config()

    def disable_all_setups_and_reminders(self) -> None:
        """Disables and unchecks absolutely all Setups and reminders."""
        for cfg in self.setups.values():
            cfg.enabled = False
            cfg.notify_15m = False
            cfg.notify_10m = False
            cfg.notify_5m = False
            cfg.notify_1m = False
            cfg.notify_reg_open = False
            cfg.notify_start = False
        self.save_config()

    def enable_all_quick(self, notify_minutes: int = 5) -> None:
        """Enables all Setups with a quick reminder (e.g. 5 min)."""
        for cfg in self.setups.values():
            cfg.enabled = True
            cfg.notify_15m = (notify_minutes == 15)
            cfg.notify_10m = (notify_minutes == 10)
            cfg.notify_5m = (notify_minutes == 5)
            cfg.notify_1m = (notify_minutes == 1)
            cfg.notify_reg_open = False
            cfg.notify_start = False
        self.save_config()

    def get_all_real_events(self, now: Optional[float] = None) -> List[RaceEvent]:
        """Transforms all race sessions from API into RaceEvent objects."""
        current_time = now if now is not None else time.time()
        events: List[RaceEvent] = []

        for item in self._raw_series_data:
            s_name = item.get("series", "LMU Race")
            diff = item.get("difficulty", "Beginner")
            circuit = item.get("circuit", "Unknown Track")
            car_classes = ", ".join(item.get("carClasses", []))
            setup_type = item.get("setup", "fixed")
            race_len = item.get("raceLength", 20)
            reg_lead_sec = 15 * 60

            s_id = clean_series_key(s_name) if s_name else make_setup_key(diff, car_classes, circuit)
            cfg = self.setups.get(s_id)
            tier_cat = cfg.tier_category if cfg else "Bronze"

            times = item.get("times", [])
            for t_str in times:
                try:
                    dt = datetime.datetime.fromisoformat(t_str.replace("Z", "+00:00"))
                    start_ts = dt.timestamp()
                    end_ts = start_ts + (race_len * 60)
                    reg_open_ts = start_ts - reg_lead_sec

                    # Keep races ending after current_time
                    if end_ts >= current_time:
                        time_to_start = start_ts - current_time
                        time_to_reg = reg_open_ts - current_time

                        if current_time < reg_open_ts:
                            status = "UPCOMING"
                        elif reg_open_ts <= current_time < start_ts:
                            status = "REGISTRATION_OPEN"
                        elif start_ts <= current_time < end_ts:
                            status = "IN_PROGRESS"
                        else:
                            status = "FINISHED"

                        events.append(
                            RaceEvent(
                                setup_id=s_id,
                                series_name=s_name,
                                difficulty=diff,
                                car_classes=car_classes,
                                track_name=circuit,
                                tier_category=tier_cat,
                                start_time=start_ts,
                                end_time=end_ts,
                                reg_open_time=reg_open_ts,
                                setup_type=setup_type,
                                race_length_min=race_len,
                                status=status,
                                time_until_start=time_to_start,
                                time_until_reg=time_to_reg,
                            )
                        )
                except Exception:
                    continue

        events.sort(key=lambda e: e.start_time)
        return events

    def get_next_event(self, setup_id: str, now: Optional[float] = None) -> Optional[RaceEvent]:
        """Returns the next session for a specific Setup."""
        current_time = now if now is not None else time.time()
        events = self.get_all_real_events(now=current_time)

        for ev in events:
            if ev.setup_id == setup_id and ev.end_time >= current_time:
                return ev

        # Fallback if API is offline
        cfg = self.setups.get(setup_id)
        if cfg:
            fallback_ts = (int(current_time // 1800) + 1) * 1800
            return RaceEvent(
                setup_id=setup_id,
                series_name=cfg.series_name or cfg.display_title,
                difficulty=cfg.difficulty,
                car_classes=cfg.car_classes,
                track_name=cfg.circuit or "Bahrain (WEC)",
                tier_category=cfg.tier_category,
                start_time=fallback_ts,
                end_time=fallback_ts + (cfg.race_length_min * 60),
                reg_open_time=fallback_ts - 900,
                setup_type=cfg.setup_type,
                race_length_min=cfg.race_length_min,
                status="UPCOMING",
                time_until_start=fallback_ts - current_time,
                time_until_reg=fallback_ts - 900 - current_time,
            )
        return None

    def get_upcoming_events(self, horizon_hours: float = 6.0, now: Optional[float] = None) -> List[RaceEvent]:
        """Returns upcoming races sorted chronologically."""
        current_time = now if now is not None else time.time()
        max_ts = current_time + (horizon_hours * 3600)
        events = self.get_all_real_events(now=current_time)
        return [e for e in events if e.start_time <= max_ts]

    def update(self, now: Optional[float] = None) -> List[TriggeredAlertDict]:
        """
        Checks all upcoming races for enabled Setups and triggers alerts in the FIFO queue.
        """
        if not self.master_enabled:
            return []

        current_time = now if now is not None else time.time()

        triggered_alerts = []

        # Clean up alerts older than 4 hours
        self._fired_alerts = {
            alert_tuple
            for alert_tuple in self._fired_alerts
            if len(alert_tuple) >= 3 and (isinstance(alert_tuple[2], (int, float)) and alert_tuple[2] > (current_time - 14400))
        }

        # Retrieve all events upcoming within the next 25 minutes
        upcoming_events = self.get_upcoming_events(horizon_hours=0.45, now=current_time)

        for event in upcoming_events:
            cfg = self.setups.get(event.setup_id)
            if not cfg or not cfg.enabled:
                continue

            slot_key = int(event.start_time)
            t_rem = event.time_until_start

            # Alert triggering rules based on Setup checkboxes
            alert_rules = [
                # T-15 minutes
                (
                    "15m",
                    cfg.notify_15m and (14.5 * 60 <= t_rem <= 15.5 * 60),
                    [cfg.sound_key, "fifteen_minutes"],
                    f"Starting in 15 minutes ({cfg.display_title})",
                ),
                # T-10 minutes
                (
                    "10m",
                    cfg.notify_10m and (9.5 * 60 <= t_rem <= 10.5 * 60),
                    [cfg.sound_key, "ten_minutes"],
                    f"Starting in 10 minutes ({cfg.display_title})",
                ),
                # T-5 minutes
                (
                    "5m",
                    cfg.notify_5m and (4.5 * 60 <= t_rem <= 5.5 * 60),
                    [cfg.sound_key, "five_minutes"],
                    f"Starting in 5 minutes ({cfg.display_title})",
                ),
                # T-1 minute
                (
                    "1m",
                    cfg.notify_1m and (0.5 * 60 <= t_rem <= 1.5 * 60),
                    [cfg.sound_key, "one_minute"],
                    f"Starting in 1 minute ({cfg.display_title})",
                ),
                # Registration open
                (
                    "reg_open",
                    cfg.notify_reg_open and (-15.0 <= event.time_until_reg <= 15.0),
                    [cfg.sound_key, "registration_open"],
                    f"Registration open for {cfg.display_title}!",
                ),
                # Race start
                (
                    "start",
                    cfg.notify_start and (-10.0 <= t_rem <= 10.0),
                    [cfg.sound_key, "race_starting"],
                    f"Race starting now for {cfg.display_title}!",
                ),
            ]

            for alert_type, should_fire, sound_sequence, text_msg in alert_rules:
                alert_id = (event.setup_id, event.series_name, slot_key, alert_type)
                if should_fire and alert_id not in self._fired_alerts:
                    self._fired_alerts.add(alert_id)
                    self._trigger_alert(cfg, event, alert_type, sound_sequence, text_msg)
                    triggered_alerts.append({
                        "setup_id": event.setup_id,
                        "race_id": event.setup_id,
                        "race_name": event.series_name,
                        "display_title": cfg.display_title,
                        "alert_type": alert_type,
                        "message": text_msg,
                        "time": current_time,
                    })

        return triggered_alerts

    # Backward compatible alias
    check_notifications = update

    def _trigger_alert(
        self,
        cfg: RaceSetupConfig,
        event: RaceEvent,
        alert_type: str,
        sound_sequence: List[str],
        text_msg: str
    ) -> None:
        """Adds alert to FIFO audio queue and displays desktop notification."""
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        log_entry = {
            "time_str": time_str,
            "setup_name": cfg.display_title,
            "race_name": event.series_name,
            "tier": cfg.tier_category,
            "alert_type": alert_type,
            "message": text_msg,
            "track": event.track_name,
        }
        self.notification_history.insert(0, log_entry)
        if len(self.notification_history) > 50:
            self.notification_history = self.notification_history[:50]

        logger.info(f"[LMUScheduleManager] ALERT: [{cfg.display_title}] {text_msg} (Audio: {sound_sequence})")
        print(f"[LMU SCHEDULE] 🏁 Setup Alert: [{cfg.display_title}] {text_msg}", flush=True)

        if self.audio_enabled:
            AudioAnnouncer.play_sequence(sound_sequence, interrupt=False)

        if self.desktop_notifications_enabled:
            self._send_desktop_notification(
                title=f"SimPad LMU: {cfg.display_title}",
                body=f"{text_msg}\nSeries: {event.series_name} ({event.setup_type.upper()} setup)",
            )

    def _send_desktop_notification(self, title: str, body: str) -> None:
        """Sends native desktop notification."""
        if sys.platform.startswith("linux") and shutil.which("notify-send"):
            try:
                subprocess.Popen(
                    ["notify-send", "-a", "SimPad LMU", "-i", "speedometer", title, body],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass

    def test_announcement(self, setup_id: str, alert_type: str = "main") -> None:
        """Plays a test sound announcement for the Setup via the FIFO queue."""
        cfg = self.setups.get(setup_id)
        if not cfg:
            return

        if alert_type == "main":
            seq = [cfg.sound_key]
        elif alert_type == "15m":
            seq = [cfg.sound_key, "fifteen_minutes"]
        elif alert_type == "5m":
            seq = [cfg.sound_key, "five_minutes"]
        elif alert_type == "reg_open":
            seq = [cfg.sound_key, "registration_open"]
        elif alert_type == "start":
            seq = [cfg.sound_key, "race_starting"]
        else:
            seq = [cfg.sound_key]

        AudioAnnouncer.play_sequence(seq, interrupt=False)
