"""
SimPad Track Limits & LMU Race Control Diagnostic Event Logger.
Logs in real-time ONLY on state transitions: lap flags, LMU infraction steps, color levels, and spotter decisions.
Outputs structured, human-readable logs to 'track_limits_debug.log'.
"""

import time
import os
import threading
from typing import Optional, Any


class TrackLimitsLogger:
    """
    Real-time event logger dedicated to LMU Race Control, track limits infractions, and voice spotter decisions.
    Strictly event-driven: zero periodic logging, logs ONLY when a state transition occurs.
    Explicitly tracks Race Control color levels (GREEN, YELLOW, ORANGE, RED).
    """

    _instance: Optional["TrackLimitsLogger"] = None
    _lock = threading.Lock()
    _header_written: bool = False
    default_enabled: bool = True

    def __init__(self, log_path: str = "track_limits_debug.log", enabled: Optional[bool] = None):
        self.log_path = log_path
        self._last_flag: Optional[int] = None
        self._last_steps: Optional[int] = None
        self._last_penalties: Optional[int] = None
        self._last_lap: Optional[int] = None
        self._last_sector: Optional[int] = None
        self._last_steps_per_pt: Optional[int] = None
        self._last_steps_per_pen: Optional[int] = None
        self._last_is_on_track: Optional[bool] = None
        self._last_wheels_on_track: Optional[int] = None
        self._log_file = None
        self.enabled = TrackLimitsLogger.default_enabled if enabled is None else enabled

        try:
            file_exists = os.path.exists(self.log_path) and os.path.getsize(self.log_path) > 0
            self._log_file = open(self.log_path, "a", encoding="utf-8", buffering=1)
            if not file_exists and not TrackLimitsLogger._header_written:
                header = (
                    f"{'=' * 170}\n"
                    f"SIMPAD LMU RACE CONTROL & TRACK LIMITS DIAGNOSTIC EVENT LOG\n"
                    f"STRICTLY EVENT-DRIVEN: Logs ONLY on State Transitions, Step Increments, Lap/Sector changes, Flags, and Spotter Decisions\n"
                    f"{'=' * 170}\n"
                    f"{'TIMESTAMP':<13} {'EVENT TRIGGER':<32} {'SOURCE':<20} | {'COLOR':<8} {'RACE CONTROL STATUS':<24} | {'RAW LMU UDP DATA':<60} | {'KM/H, T, B':<18}\n"
                    f"{'-' * 170}\n"
                )
                self._log_file.write(header)
                self._log_file.flush()
                TrackLimitsLogger._header_written = True
        except Exception as e:
            print(f"[TrackLimitsLogger] Error opening log {self.log_path}: {e}")

    @classmethod
    def get_instance(cls) -> "TrackLimitsLogger":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset_log_file(cls, log_path: str = "track_limits_debug.log") -> None:
        """Cleans and re-initializes the log file with a single header."""
        with cls._lock:
            try:
                if cls._instance and cls._instance._log_file:
                    try:
                        cls._instance._log_file.close()
                    except Exception:
                        pass
                    cls._instance._log_file = None
                with open(log_path, "w", encoding="utf-8") as f:
                    header = (
                        f"{'=' * 170}\n"
                        f"SIMPAD LMU RACE CONTROL & TRACK LIMITS DIAGNOSTIC EVENT LOG\n"
                        f"STRICTLY EVENT-DRIVEN: Logs ONLY on State Transitions, Step Increments, Lap/Sector changes, Flags, and Spotter Decisions\n"
                        f"{'=' * 170}\n"
                        f"{'TIMESTAMP':<13} {'EVENT TRIGGER':<32} {'SOURCE':<20} | {'COLOR':<8} {'RACE CONTROL STATUS':<24} | {'RAW LMU UDP DATA':<60} | {'KM/H, T, B':<18}\n"
                        f"{'-' * 170}\n"
                    )
                    f.write(header)
                cls._header_written = True
                if cls._instance:
                    cls._instance._last_flag = None
                    cls._instance._last_steps = None
                    cls._instance._last_penalties = None
                    cls._instance._last_lap = None
                    cls._instance._last_sector = None
                    cls._instance._last_is_on_track = None
                    cls._instance._last_wheels_on_track = None
                    cls._instance._log_file = open(log_path, "a", encoding="utf-8", buffering=1)
            except Exception:
                pass

    def log_telemetry_event(
        self,
        source: str,
        lap_num: int = 0,
        sector: int = 1,
        lap_flag: int = 2,
        track_limits_steps: int = 0,
        steps_per_point: int = 0,
        steps_per_penalty: int = 0,
        num_penalties: int = 0,
        is_lap_invalid: bool = False,
        speed_kmh: float = 0.0,
        throttle_pct: float = 0.0,
        brake_pct: float = 0.0,
        event_note: str = "",
        raw_data_summary: str = "",
    ) -> None:
        """Logs an official LMU Race Control / Track Limits state change event. Suppresses all unchanged periodic frames."""
        if not self.enabled or self._log_file is None:
            return

        now = time.time()
        # Detect what changed
        flag_changed = (self._last_flag is not None and lap_flag != self._last_flag)
        steps_changed = (self._last_steps is not None and track_limits_steps != self._last_steps)
        pen_changed = (self._last_penalties is not None and num_penalties != self._last_penalties)
        lap_changed = (self._last_lap is not None and lap_num != self._last_lap)
        sector_changed = (self._last_sector is not None and sector != self._last_sector)
        rules_changed = (
            (self._last_steps_per_pt is not None and steps_per_point > 0 and steps_per_point != self._last_steps_per_pt)
            or (self._last_steps_per_pen is not None and steps_per_penalty > 0 and steps_per_penalty != self._last_steps_per_pen)
        )
        is_first_init = (self._last_flag is None and self._last_lap is None)

        has_changed = (
            flag_changed
            or steps_changed
            or pen_changed
            or lap_changed
            or sector_changed
            or rules_changed
            or is_first_init
            or bool(event_note)
        )

        # STRICT EVENT FILTER: Never log identical consecutive frames
        if not has_changed:
            return

        # Categorize the change tag
        tags = []
        if is_first_init:
            tags.append("INIT")
        if flag_changed:
            flag_names = {2: "VALID", 1: "INVESTIGATION", 0: "DELETED"}
            f_prev = flag_names.get(self._last_flag, str(self._last_flag))
            f_curr = flag_names.get(lap_flag, str(lap_flag))
            tags.append(f"FLAG:{f_prev}->{f_curr}")
        if steps_changed:
            delta = track_limits_steps - (self._last_steps or 0)
            sign = f"+{delta}" if delta > 0 else str(delta)
            tags.append(f"STEPS:{self._last_steps}->{track_limits_steps} ({sign})")
        if pen_changed:
            tags.append(f"PENALTIES:{self._last_penalties}->{num_penalties}")
        if lap_changed:
            tags.append(f"LAP:{self._last_lap}->{lap_num}")
        if sector_changed:
            tags.append(f"SECTOR:{self._last_sector}->{sector}")
        if rules_changed:
            tags.append(f"RULES:pt={steps_per_point},pen={steps_per_penalty}")
        if event_note:
            tags.append(event_note)

        tag_str = "[" + " | ".join(tags) + "]"

        self._last_flag = lap_flag
        self._last_steps = track_limits_steps
        self._last_penalties = num_penalties
        self._last_lap = lap_num
        self._last_sector = sector
        if steps_per_point > 0:
            self._last_steps_per_pt = steps_per_point
        if steps_per_penalty > 0:
            self._last_steps_per_pen = steps_per_penalty

        time_str = time.strftime("%H:%M:%S", time.localtime(now)) + f".{int((now % 1) * 1000):03d}"

        # 4 LMU Official Race Control Color Levels
        steps_pt = self._last_steps_per_pt or 3
        steps_pen = self._last_steps_per_pen or 12
        current_strikes = track_limits_steps // steps_pt if steps_pt > 0 else 0
        max_strikes = steps_pen // steps_pt if steps_pt > 0 else 0

        if num_penalties > 0:
            color_str = "RED"
            status_str = f"PENALTY ({num_penalties} active)"
        elif lap_flag == 0:
            color_str = "RED"
            status_str = "LAP DELETED"
        elif lap_flag == 1:
            color_str = "YELLOW"
            status_str = "INVESTIGATION (SlowDown)"
        elif current_strikes > 0 and lap_flag == 2:
            color_str = "ORANGE"
            status_str = f"WARNING (Strike {current_strikes}/{max_strikes})"
        elif lap_flag == 2:
            color_str = "GREEN"
            status_str = "VALID" if not is_lap_dirty else "VALID (Invalidated)"
        else:
            color_str = "UNKNOWN"
            status_str = f"FLAG({lap_flag})"

        raw_str = raw_data_summary or f"count_lap_flag={lap_flag} tl_steps={track_limits_steps} pens={num_penalties} sec={sector} lap={lap_num}"

        line = (
            f"[{time_str}] {tag_str:<32} {source:<20} | "
            f"{color_str:<8} {status_str:<24} | "
            f"{raw_str:<60} | "
            f"{speed_kmh:>5.1f}km/h T:{throttle_pct:>3.0f}% B:{brake_pct:>3.0f}%\n"
        )

        try:
            self._log_file.write(line)
            self._log_file.flush()
        except Exception:
            pass

    def log_surface_event(
        self,
        source: str = "TelemInfo(120Hz)",
        is_on_track: bool = True,
        wheels_on_track: int = 4,
        surface_types: tuple = (0, 0, 0, 0),
        terrain_names: tuple = ("", "", "", ""),
        speed_kmh: float = 0.0,
        throttle_pct: float = 0.0,
        brake_pct: float = 0.0,
        lap_num: int = 0,
        sector: int = 1,
        lap_flag: int = 2,
    ) -> None:
        """
        Logs strictly event-driven transitions between ON-TRACK (route) and OFF-TRACK (hors-piste) surfaces.
        Suppresses all identical frames.
        """
        if not self.enabled or self._log_file is None:
            return

        # Only log when wheels_on_track count changes (e.g. 4 -> 0 -> 1 -> 4)
        if self._last_wheels_on_track is not None and wheels_on_track == self._last_wheels_on_track:
            return

        prev_wheels = self._last_wheels_on_track
        self._last_wheels_on_track = wheels_on_track
        self._last_is_on_track = is_on_track

        # On initial startup, don't spam if car is already cleanly on track with 4 wheels
        if prev_wheels is None and wheels_on_track == 4:
            return

        now = time.time()
        time_str = time.strftime("%H:%M:%S", time.localtime(now)) + f".{int((now % 1) * 1000):03d}"

        if wheels_on_track == 0:
            tag_str = f"[OFF_TRACK (0/4 on road)]"
            color_str = "ORANGE"
            status_str = "OFF-ROAD (Grass/Gravel)"
        elif wheels_on_track <= 2:
            tag_str = f"[TRACK_EDGE ({wheels_on_track}/4 on road)]"
            color_str = "YELLOW"
            status_str = "TRACK-EDGE (Kerb/Grass)"
        elif wheels_on_track == 4:
            tag_str = f"[TRACK_REJOIN (4/4 on road)]"
            color_str = "GREEN"
            status_str = "ON-TRACK (Full Road)"
        else:
            tag_str = f"[TRACK_REJOIN ({wheels_on_track}/4 on road)]"
            color_str = "GREEN"
            status_str = "ON-TRACK (Road Rejoin)"

        surface_names_map = {0: "dry_road", 1: "wet_road", 2: "grass", 3: "dirt", 4: "gravel", 5: "kerb", 6: "special"}
        surf_labels = [surface_names_map.get(s, str(s)) for s in surface_types]
        raw_str = f"surfaces={surf_labels} on_track={wheels_on_track}/4 flag={lap_flag} sec={sector} lap={lap_num}"

        line = (
            f"[{time_str}] {tag_str:<32} {source:<20} | "
            f"{color_str:<8} {status_str:<24} | "
            f"{raw_str:<60} | "
            f"{speed_kmh:>5.1f}km/h T:{throttle_pct:>3.0f}% B:{brake_pct:>3.0f}%\n"
        )

        try:
            self._log_file.write(line)
            self._log_file.flush()
        except Exception:
            pass

    def set_enabled(self, enabled: bool) -> None:
        """Enables or disables track limits logging."""
        self.enabled = enabled
        TrackLimitsLogger.default_enabled = enabled

    def log_spotter_action(self, phrase_key: str, interrupt: bool, context_info: str = "") -> None:
        """Logs spotter audio voice triggering."""
        if not self.enabled or self._log_file is None:
            return

        now = time.time()
        time_str = time.strftime("%H:%M:%S", time.localtime(now)) + f".{int((now % 1) * 1000):03d}"
        line = f"[{time_str}] >>> SPOTTER AUDIO EMITTED : phrase='{phrase_key}' (interrupt={interrupt}) | {context_info}\n"
        try:
            if self._log_file:
                self._log_file.write(line)
                self._log_file.flush()
        except Exception:
            pass

    def log_spotter_decision(self, action: str, reason: str, details: str = "") -> None:
        """Logs a spotter evaluation decision (e.g. suppressed alert, green status, debounce wait)."""
        if not self.enabled or self._log_file is None:
            return

        now = time.time()
        time_str = time.strftime("%H:%M:%S", time.localtime(now)) + f".{int((now % 1) * 1000):03d}"
        line = f"[{time_str}] --- SPOTTER DECISION      : {action:<22} | Reason: {reason} | {details}\n"
        try:
            if self._log_file:
                self._log_file.write(line)
                self._log_file.flush()
        except Exception:
            pass


