"""
SimPulse Runtime Logger Application.

Single place that turns the ``config.json -> "loggers"`` booleans into real
gates on every file-writing diagnostic logger in the program.

Before this module existed the config keys were dead: each logger opened its own
``.log`` output and defaulted to *on*, so the UI/JSON toggles had no effect.
Some loggers (sector_eval, sector_paint) had no key at all to bind to. This
module is invoked once at app bootstrap (right after ConfigManager() loads),
so the configuration is authoritative from the very first telemetry packet.
"""

from __future__ import annotations
import logging

from simpulse.core.config import LoggerSettings

logger = logging.getLogger("simpulse.runtime_loggers")

# Keys of LoggerSettings that currently gate a concrete file-writing logger.
_RUNTIME_BINDINGS = (
    "telemetry",       # TelemetryDiagnosticLogger  -> telemetry_live.log
    "track_limits",    # TrackLimitsLogger           -> track_limits_debug.log
    "overlay_anomaly", # OverlayAnomalyLogger        -> hud_overlay_glitch.log
    "delta_debug",     # delta_engine.*              -> delta_debug.log
    "sector_eval",     # sector_colors._audit        -> sector_eval.log
    "sector_paint",    # sector_paint_recorder.record-> sector_paint.log
    "hud_smoothing",   # hud_smoothing_logger.record_*-> hud_smoothing.log
)


def set_single_logger_enabled(key: str, enabled: bool) -> None:
    """Toggle one file logger by its config.json ``loggers`` key."""
    if key == "telemetry":
        from simpulse.core.telemetry.telemetry_logger import TelemetryDiagnosticLogger
        TelemetryDiagnosticLogger.get_instance().set_enabled(enabled)
    elif key == "track_limits":
        from simpulse.core.telemetry.track_limits_logger import TrackLimitsLogger
        TrackLimitsLogger.get_instance().set_enabled(enabled)
    elif key == "overlay_anomaly":
        from simpulse.core.telemetry.overlay_anomaly_logger import OverlayAnomalyLogger
        OverlayAnomalyLogger.get_instance().set_enabled(enabled)
    elif key == "delta_debug":
        from simpulse.core.telemetry import delta_engine
        delta_engine.set_delta_debug_enabled(enabled)
    elif key == "sector_eval":
        from simpulse.core.telemetry.sector_colors import set_sector_eval_enabled
        set_sector_eval_enabled(enabled)
    elif key == "sector_paint":
        # Pure module (no Qt import at module scope); safe to load early.
        from simpulse.builtin_plugins.official_cockpit_hud.widgets.sector_paint_recorder import (
            set_sector_paint_enabled,
        )
        set_sector_paint_enabled(enabled)
    elif key == "hud_smoothing":
        # Pure module (no Qt import at module scope); safe to load early.
        from simpulse.builtin_plugins.official_cockpit_hud.widgets.hud_smoothing_logger import (
            set_hud_smoothing_enabled,
        )
        set_hud_smoothing_enabled(enabled)
    else:
        raise KeyError(f"no runtime logger registered for key '{key}'")


def apply_logger_settings(settings: LoggerSettings) -> None:
    """Apply every ``loggers`` key that gates a concrete file logger.

    Keys describing future/intent-only domains (engineer, schedule, haptics,
    gui, utils ...) are tolerated silently — they have no file logger to bind
    yet and keep their config presence for forward compatibility.
    """
    for key in _RUNTIME_BINDINGS:
        enabled = bool(getattr(settings, key, False))
        try:
            set_single_logger_enabled(key, enabled)
        except Exception as e:  # never let boot logging break startup
            logger.error("failed to apply logger key '%s': %s", key, e)
    logger.debug("applied runtime logger settings: %s",
                 {k: bool(getattr(settings, k, False)) for k in _RUNTIME_BINDINGS})
