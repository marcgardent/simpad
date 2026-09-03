"""
SimPad Track Limits & Investigation Diagnostic Logger.
Logs in real-time all incoming track cut steps, lap flags, investigation states, and spotter audio events.
Outputs human-readable structured logs to 'track_limits_debug.log'.
"""

import time
import os
import threading
from pathlib import Path
from typing import Optional, Any


class TrackLimitsLogger:
    """
    Enregistreur temps réel dédié aux enquêtes de limites de piste, drapeaux de tour et annonces vocales.
    Permet de vérifier en direct si le jeu/plugin envoie bien les données de track_limits_steps.
    """

    _instance: Optional["TrackLimitsLogger"] = None
    _lock = threading.Lock()
    default_enabled: bool = True

    def __init__(self, log_path: str = "track_limits_debug.log", sample_interval_sec: float = 0.50, enabled: Optional[bool] = None):
        self.log_path = log_path
        self.sample_interval_sec = sample_interval_sec
        self._last_log_time = 0.0
        self._last_steps: Optional[int] = None
        self._last_flag: Optional[int] = None
        self._last_state: Optional[str] = None
        self._log_file = None
        self.enabled = TrackLimitsLogger.default_enabled if enabled is None else enabled

        try:
            file_exists = os.path.exists(self.log_path) and os.path.getsize(self.log_path) > 0
            self._log_file = open(self.log_path, "a", encoding="utf-8", buffering=1)
            if not file_exists:
                header = (
                    "=" * 130 + "\n"
                    "SIMPAD TRACK LIMITS & INVESTIGATION DIAGNOSTIC LOG\n"
                    "Format: [TIME] SOURCE | LAP# | SECT | LAP_FLAG | TL_STEPS | STATE | DIRTY_LOCK | SPEED | THR% | BRK% | EVENT / AUDIO\n"
                    "=" * 130 + "\n"
                )
                self._log_file.write(header)
                self._log_file.flush()
        except Exception as e:
            print(f"[TrackLimitsLogger] Erreur ouverture log {self.log_path}: {e}")

    @classmethod
    def get_instance(cls) -> "TrackLimitsLogger":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def log_telemetry_event(
        self,
        source: str,
        lap_num: int = 0,
        sector: int = 1,
        lap_flag: int = 2,
        track_limits_steps: int = 0,
        track_cut_state: str = "green",
        is_lap_dirty: bool = False,
        speed_kmh: float = 0.0,
        throttle_pct: float = 0.0,
        brake_pct: float = 0.0,
        event_note: str = "",
    ) -> None:
        """Enregistre un échantillon de limite de piste / investigation."""
        if not self.enabled or self._log_file is None:
            return

        now = time.time()
        has_changed = (
            track_limits_steps != self._last_steps
            or lap_flag != self._last_flag
            or track_cut_state != self._last_state
            or bool(event_note)
        )

        is_active = (track_limits_steps > 0) or (track_cut_state != "green") or bool(event_note)

        # Log si changement d'état OU si actif (échantillon plus fréquent) OU intervalle régulier
        if not has_changed and not is_active and (now - self._last_log_time < self.sample_interval_sec):
            return

        self._last_log_time = now
        self._last_steps = track_limits_steps
        self._last_flag = lap_flag
        self._last_state = track_cut_state

        time_str = time.strftime("%H:%M:%S", time.localtime(now)) + f".{int((now % 1) * 1000):03d}"
        flag_str = "VALID(2)" if lap_flag == 2 else f"DIRTY({lap_flag})"
        dirty_lock_str = "DIRTY_LOCKED" if is_lap_dirty else "CLEAN"
        state_str = str(track_cut_state).upper()

        line = (
            f"[{time_str}] {source:<20} | Lap {lap_num:<3} | S{sector} | {flag_str:<8} | "
            f"Steps:{track_limits_steps:<3} | State:{state_str:<13} | {dirty_lock_str:<12} | "
            f"{speed_kmh:>5.1f}km/h | T:{throttle_pct:>3.0f}% | B:{brake_pct:>3.0f}% | {event_note}\n"
        )

        try:
            self._log_file.write(line)
            self._log_file.flush()
        except Exception:
            pass

    def set_enabled(self, enabled: bool) -> None:
        """Active ou désactive la journalisation des limites de piste."""
        self.enabled = enabled
        TrackLimitsLogger.default_enabled = enabled

    def log_spotter_action(self, phrase_key: str, interrupt: bool, context_info: str = "") -> None:
        """Enregistre le déclenchement vocal du spotter."""
        if not self.enabled or self._log_file is None:
            return

        now = time.time()
        time_str = time.strftime("%H:%M:%S", time.localtime(now)) + f".{int((now % 1) * 1000):03d}"
        line = f"[{time_str}] >>> SPOTTER AUDIO EMITTED: phrase='{phrase_key}' (interrupt={interrupt}) | {context_info}\n"
        try:
            if self._log_file:
                self._log_file.write(line)
                self._log_file.flush()
        except Exception:
            pass
