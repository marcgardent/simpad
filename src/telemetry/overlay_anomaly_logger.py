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
    Système d'audit et de journalisation haute-visibilité des anomalies HUD / Overlay.
    """

    _instance: Optional["OverlayAnomalyLogger"] = None
    _lock = threading.Lock()

    def __init__(self, log_path: Path = _LOG_FILE):
        self.log_path = log_path
        self._prev_speed: float = 0.0
        self._prev_throttle: float = 0.0
        self._prev_brake: float = 0.0
        self._prev_gear: int = 0
        self._prev_in_realtime: bool = True
        self._prev_display_mode: str = "init"
        self._log_file = None

        try:
            self._log_file = open(self.log_path, "a", encoding="utf-8", buffering=1)
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            self._log_file.write(f"\n{'='*100}\n[{ts}] SIMPAD HUD ANOMALY LOGGER STARTED\n{'='*100}\n")
            self._log_file.flush()
        except Exception as e:
            print(f"[OverlayAnomalyLogger] Erreur ouverture fichier de log: {e}", flush=True)

    @classmethod
    def get_instance(cls) -> "OverlayAnomalyLogger":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def log_event(self, category: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Enregistre un événement anormal dans le fichier de log et sur la console."""
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
        """Détecte les ruptures brutales (chute à zéro, saut de vitesse/pédale) d'une trame à l'autre."""
        # 1. Chute brutale de vitesse (ex: 200 km/h -> 0 km/h en 1 trame)
        if self._prev_speed > 30.0 and speed_kmh < 2.0:
            self.log_event(
                "SPEED_DROP_ZERO",
                f"Vitesse écroulée brutalement de {self._prev_speed:.1f} km/h à {speed_kmh:.1f} km/h !",
                {"source": source, "in_realtime": in_realtime, "prev_gear": self._prev_gear, "new_gear": gear}
            )

        # 2. Chute ou pic brutal de l'accélérateur
        if self._prev_throttle > 35.0 and throttle_pct < 1.0 and speed_kmh > 20.0:
            self.log_event(
                "THROTTLE_DROP_ZERO",
                f"Accélérateur écroulé brutalement de {self._prev_throttle:.1f}% à {throttle_pct:.1f}% !",
                {"source": source, "speed_kmh": round(speed_kmh, 1), "gear": gear}
            )
        elif self._prev_throttle < 10.0 and throttle_pct > 95.0:
            self.log_event(
                "THROTTLE_SPIKE_100",
                f"Accélérateur bondi instantanément de {self._prev_throttle:.1f}% à {throttle_pct:.1f}% (100%) !",
                {"source": source, "speed_kmh": round(speed_kmh, 1), "gear": gear}
            )

        # 3. Chute ou pic brutal du frein
        if self._prev_brake > 35.0 and brake_pct < 1.0 and speed_kmh > 30.0:
            self.log_event(
                "BRAKE_DROP_ZERO",
                f"Frein écroulé brutalement de {self._prev_brake:.1f}% à {brake_pct:.1f}% !",
                {"source": source, "speed_kmh": round(speed_kmh, 1), "gear": gear}
            )
        elif self._prev_brake < 10.0 and brake_pct > 95.0:
            self.log_event(
                "BRAKE_SPIKE_100",
                f"Frein bondi instantanément de {self._prev_brake:.1f}% à {brake_pct:.1f}% (100%) !",
                {"source": source, "speed_kmh": round(speed_kmh, 1), "gear": gear}
            )

        # 4. Saut anormal du rapport de boîte (ex: 4ème -> 0 / Neutre en roulant sans débrayer)
        if self._prev_gear >= 2 and gear == 0 and speed_kmh > 40.0:
            self.log_event(
                "GEAR_RESET_ZERO",
                f"Rapport de boîte tombé brutalement de {self._prev_gear} à {gear} (Neutre) à {speed_kmh:.1f} km/h !",
                {"source": source, "in_realtime": in_realtime}
            )

        # 5. Bascule du drapeau in_realtime
        if self._prev_in_realtime != in_realtime:
            self.log_event(
                "REALTIME_STATE_CHANGED",
                f"Drapeau in_realtime basculé de {self._prev_in_realtime} à {in_realtime}",
                {"source": source, "speed_kmh": round(speed_kmh, 1), "gear": gear}
            )

        self._prev_speed = speed_kmh
        self._prev_throttle = throttle_pct
        self._prev_brake = brake_pct
        self._prev_gear = gear
        self._prev_in_realtime = in_realtime

    def log_display_mode_change(self, old_mode: str, new_mode: str, reason: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Enregistre tout changement de mode d'affichage de l'overlay (ingame / pause / desktop)."""
        self.log_event(
            "OVERLAY_MODE_CHANGE",
            f"Mode d'affichage basculé de '{old_mode}' vers '{new_mode}' (Raison: {reason})",
            details
        )
