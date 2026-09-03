import copy
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

DEFAULT_CONFIG_PATH = Path("config.json")

DEFAULT_LOGGER_FLAGS: Dict[str, Any] = {
    "telemetry": True,
    "engineer": True,
    "schedule": True,
    "haptics": True,
    "gui": True,
    "utils": True,
    "track_limits": True,
    "overlay_anomaly": True,
    "delta_debug": True,
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "abs_threshold": 0.15,
    "tc_threshold": 0.20,
    "lateral_slide_threshold": 0.10,
    "udp_host": "127.0.0.1",
    "udp_port": 5606,
    "update_rate_hz": 100,
    "delta_reference_mode": "all_time_best",
    "delta_freeze_duration": 3.5,
    "delta_ema_samples": 0,
    "loggers": DEFAULT_LOGGER_FLAGS.copy(),
}

LOGGER_CATEGORY_MAP: Dict[str, List[str]] = {
    "telemetry": ["src.telemetry", "telemetry"],
    "engineer": ["src.engineer", "engineer"],
    "schedule": ["src.schedule", "schedule"],
    "haptics": ["src.haptics", "haptics"],
    "gui": ["src.gui", "gui"],
    "utils": ["src.utils", "utils"],
    "core": ["src.core", "core"],
    "physics": ["src.physics", "physics"],
}


def _configure_root_logger() -> None:
    """Configure root logger with a clear formatter if it has no handler yet."""
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)


def apply_logger_config(config: Optional[Dict[str, Any]] = None) -> None:
    """
    Dynamically applies enable flags and log levels for loggers
    configured in the config dictionary (key 'loggers').
    """
    _configure_root_logger()

    if config is None:
        config = DEFAULT_CONFIG

    logger_flags = config.get("loggers", {})
    if not isinstance(logger_flags, dict):
        return

    for key, value in logger_flags.items():
        # Handle specific diagnostic loggers
        if key == "track_limits":
            try:
                from src.telemetry.track_limits_logger import TrackLimitsLogger
                TrackLimitsLogger.default_enabled = bool(value)
                if TrackLimitsLogger._instance is not None:
                    TrackLimitsLogger._instance.enabled = bool(value)
            except Exception:
                pass
            continue

        if key == "overlay_anomaly":
            try:
                from src.telemetry.overlay_anomaly_logger import OverlayAnomalyLogger
                OverlayAnomalyLogger.default_enabled = bool(value)
                if OverlayAnomalyLogger._instance is not None:
                    OverlayAnomalyLogger._instance.enabled = bool(value)
            except Exception:
                pass
            continue

        if key == "delta_debug":
            try:
                import src.telemetry.delta_engine as delta_engine
                delta_engine.DELTA_DEBUG_ENABLED = bool(value)
            except Exception:
                pass
            continue

        # Determine level and enabled state for standard loggers
        level = logging.INFO
        disabled = False
        if isinstance(value, bool):
            if value:
                level = logging.INFO
                disabled = False
            else:
                level = logging.CRITICAL + 10
                disabled = True
        elif isinstance(value, str):
            level = getattr(logging, value.upper(), logging.INFO)
            disabled = False
        elif isinstance(value, int):
            level = value
            disabled = False

        # Resolve logger names
        target_prefixes = LOGGER_CATEGORY_MAP.get(key, [key])
        for prefix in target_prefixes:
            target_logger = logging.getLogger(prefix)
            target_logger.setLevel(level)
            target_logger.disabled = disabled

            # Update existing sub-loggers registered in logger manager
            for name, existing_lg in list(logging.Logger.manager.loggerDict.items()):
                if isinstance(existing_lg, logging.Logger) and (name == prefix or name.startswith(prefix + ".")):
                    existing_lg.setLevel(level)
                    existing_lg.disabled = disabled


def setup_logging(config: Optional[Dict[str, Any]] = None) -> None:
    """Initialize and apply logging configuration."""
    apply_logger_config(config)


def get_logger_flags(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return active table of logger flags."""
    if config is None:
        config = load_config()
    return config.get("loggers", DEFAULT_LOGGER_FLAGS.copy())


def set_logger_flag(
    flag_name: str,
    enabled: Union[bool, str, int],
    config: Optional[Dict[str, Any]] = None,
    save: bool = False,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> Dict[str, Any]:
    """Enable or disable a specific logger and apply change immediately."""
    if config is None:
        config = load_config(config_path)

    if "loggers" not in config or not isinstance(config["loggers"], dict):
        config["loggers"] = DEFAULT_LOGGER_FLAGS.copy()

    config["loggers"][flag_name] = enabled
    apply_logger_config(config)

    if save:
        save_config(config, config_path)

    return config


def _deep_merge_dict(base: Dict[str, Any], custom: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merges two dictionaries without overwriting missing keys."""
    merged = copy.deepcopy(base)
    for k, v in custom.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = _deep_merge_dict(merged[k], v)
        else:
            merged[k] = copy.deepcopy(v) if isinstance(v, (dict, list)) else v
    return merged


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """Load configuration from JSON file. Fallback to default values."""
    if not config_path.exists():
        save_config(DEFAULT_CONFIG, config_path)
        apply_logger_config(DEFAULT_CONFIG)
        return copy.deepcopy(DEFAULT_CONFIG)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            merged = _deep_merge_dict(DEFAULT_CONFIG, config)
            apply_logger_config(merged)
            return merged
    except Exception as e:
        print(f"Error reading {config_path}: {e}. Using default values.")
        apply_logger_config(DEFAULT_CONFIG)
        return copy.deepcopy(DEFAULT_CONFIG)


def save_config(config: Dict[str, Any], config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Save configuration to JSON format and apply logger configuration."""
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        apply_logger_config(config)
    except Exception as e:
        print(f"Error saving {config_path}: {e}")

