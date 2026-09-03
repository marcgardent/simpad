"""
SimPad Overlay Anomaly & Glitch Diagnostic Logger.
Monitors, detects and logs any instantaneous telemetry drops, gear resets, pedal glitches,
realtime flag toggles, or overlay display state flips.
Outputs to 'hud_overlay_glitch.log' and prints to stdout with [HUD-GLITCH-ALERT].
"""

import time
import os
import threading
from typing import Optional, Dict, Any
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_LOG_FILE = _PROJECT_ROOT / "hud_overlay_glitch.log"


class OverlayAnomalyLogger:
    """
    High-visibility audit and diagnostic logger for HUD / Overlay anomalies.
    """

    _instance: Optional["OverlayAnomalyLogger"] = None
    _lock = threading.Lock()
    default_enabled: bool = True

    def __init__(self, log_path: Path = _LOG_FILE, enabled: Optional[bool] = None):
        self.log_path = log_path
        self._prev_speed: float = 0.0
        self._prev_throttle: float = 0.0
        self._prev_brake: float = 0.0
        self._prev_gear: int = 0
        self._prev_in_realtime: bool = True
        self._prev_display_mode: str = "init"
        self._log_file = None
        self.enabled = OverlayAnomalyLogger.default_enabled if enabled is None else enabled

        try:
            self._log_file = open(self.log_path, "a", encoding="utf-8", buffering=1)
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            self._log_file.write(f"\n{'='*100}\n[{ts}] SIMPAD HUD ANOMALY LOGGER STARTED\n{'='*100}\n")
            self._log_file.flush()
        except Exception as e:
            print(f"[OverlayAnomalyLogger] Error opening log file: {e}", flush=True)

    @classmethod
    def get_instance(cls) -> "OverlayAnomalyLogger":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def set_enabled(self, enabled: bool) -> None:
        """Enables or disables HUD anomaly logging."""
        self.enabled = enabled
        OverlayAnomalyLogger.default_enabled = enabled

    def log_event(self, category: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Logs an abnormal event to log file and console."""
        if not self.enabled:
            return

        ts = time.strftime("%H:%M:%S") + f".{int((time.time() % 1) * 1000):03d}"
        detail_str = ""
        if details:
            detail_str = " | " + ", ".join(f"{k}={v}" for k, v in details.items())

        log_line = f"[{ts}] [HUD-GLITCH-ALERT] [{category}] {message}{detail_str}\n"
        print(log_line, end="", flush=True)

        if self._log_file:
            try:
                self._log_file.write(log_line)
                self._log_file.flush()
            except Exception:
                pass

    def check_telemetry_anomaly(
        self,
        speed_kmh: float,
        throttle_pct: float,
        brake_pct: float,
        gear: int,
        in_realtime: bool,
        source: str = "TelemInfo",
    ) -> None:
        """Detects sudden drops or spikes (fall to zero, sudden pedal jump) across frames."""
        # 1. Sudden speed drop (e.g. 200 km/h -> 0 km/h in 1 frame)
        if self._prev_speed > 30.0 and speed_kmh < 2.0:
            self.log_event(
                "SPEED_DROP_ZERO",
                f"Speed dropped abruptly from {self._prev_speed:.1f} km/h to {speed_kmh:.1f} km/h!",
                {"source": source, "in_realtime": in_realtime, "prev_gear": self._prev_gear, "new_gear": gear}
            )

        # 2. Sudden throttle drop or spike
        if self._prev_throttle > 35.0 and throttle_pct < 1.0 and speed_kmh > 20.0:
            self.log_event(
                "THROTTLE_DROP_ZERO",
                f"Throttle dropped abruptly from {self._prev_throttle:.1f}% to {throttle_pct:.1f}%!",
                {"source": source, "speed_kmh": round(speed_kmh, 1), "gear": gear}
            )
        elif self._prev_throttle < 10.0 and throttle_pct > 95.0:
            self.log_event(
                "THROTTLE_SPIKE_100",
                f"Throttle spiked instantly from {self._prev_throttle:.1f}% to {throttle_pct:.1f}% (100%)!",
                {"source": source, "speed_kmh": round(speed_kmh, 1), "gear": gear}
            )

        # 3. Sudden brake drop or spike
        if self._prev_brake > 35.0 and brake_pct < 1.0 and speed_kmh > 30.0:
            self.log_event(
                "BRAKE_DROP_ZERO",
                f"Brake dropped abruptly from {self._prev_brake:.1f}% to {brake_pct:.1f}%!",
                {"source": source, "speed_kmh": round(speed_kmh, 1), "gear": gear}
            )
        elif self._prev_brake < 10.0 and brake_pct > 95.0:
            self.log_event(
                "BRAKE_SPIKE_100",
                f"Brake spiked instantly from {self._prev_brake:.1f}% to {brake_pct:.1f}% (100%)!",
                {"source": source, "speed_kmh": round(speed_kmh, 1), "gear": gear}
            )

        # 4. Abnormal gear jump (e.g. 4th -> 0 / Neutral while moving)
        if self._prev_gear >= 2 and gear == 0 and speed_kmh > 40.0:
            self.log_event(
                "GEAR_RESET_ZERO",
                f"Gear dropped abruptly from {self._prev_gear} to {gear} (Neutral) at {speed_kmh:.1f} km/h!",
                {"source": source, "in_realtime": in_realtime}
            )

        # 5. in_realtime flag toggle
        if self._prev_in_realtime != in_realtime:
            self.log_event(
                "REALTIME_STATE_CHANGED",
                f"in_realtime flag flipped from {self._prev_in_realtime} to {in_realtime}",
                {"source": source, "speed_kmh": round(speed_kmh, 1), "gear": gear}
            )

        self._prev_speed = speed_kmh
        self._prev_throttle = throttle_pct
        self._prev_brake = brake_pct
        self._prev_gear = gear
        self._prev_in_realtime = in_realtime

    def log_display_mode_change(self, old_mode: str, new_mode: str, reason: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Logs any overlay display mode change (ingame / pause / desktop)."""
        self.log_event(
            "OVERLAY_MODE_CHANGE",
            f"Display mode switched from '{old_mode}' to '{new_mode}' (Reason: {reason})",
            details
        )

    def check_sector_update(
        self,
        current_sector: int,
        raw_sector: Any,
        source: str,
        s1_time: str = "--",
        s2_time: str = "--",
        s3_time: str = "--",
        s1_delta: float = 0.0,
        s2_delta: float = 0.0,
        s3_delta: float = 0.0,
        lap_dist: float = 0.0,
        speed_kmh: float = 0.0,
    ) -> None:
        """Traces each sector transition or abnormal jump in the log."""
        if not hasattr(self, "_prev_sector"):
            self._prev_sector = current_sector

        prev_sec = self._prev_sector

        # Log if sector changed
        if current_sector != prev_sec:
            is_anomaly = (prev_sec, current_sector) not in [(1, 2), (2, 3), (3, 1)]
            category = "SECTOR_GLITCH_JUMP" if is_anomaly else "SECTOR_TRANSITION"
            msg = (
                f"Sector switched from S{prev_sec} to S{current_sector} (raw={raw_sector}) | "
                f"S1='{s1_time}' (d={s1_delta:+.3f}s), S2='{s2_time}' (d={s2_delta:+.3f}s), S3='{s3_time}' (d={s3_delta:+.3f}s)"
            )
            self.log_event(
                category,
                msg,
                {
                    "source": source,
                    "speed_kmh": round(speed_kmh, 1),
                    "lap_dist": round(lap_dist, 1),
                }
            )
            self._prev_sector = current_sector

