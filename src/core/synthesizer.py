"""
SimPad Haptic Middleware — Real-time Haptic Synthesizer Engine.
Runs a dedicated high-frequency thread (50 Hz, 200 Hz, 1000 Hz) decoupled from the GUI render loop.
Executes the compiled Python graph function and drives hardware vibration motors in real time.
"""

import time
import threading
from typing import Optional, Callable, Tuple


class HapticSynthesizerEngine:
    """
    High-frequency synthesis engine running a dedicated background thread.
    Supported frequencies: 50 Hz (20ms), 200 Hz (5ms), 1000 Hz (1ms).
    """

    def __init__(self, haptic_controller=None, default_freq_hz: int = 200):
        self._haptic_controller = haptic_controller
        self._freq_hz = default_freq_hz
        self._interval_s = 1.0 / default_freq_hz

        self._compiled_func: Optional[Callable[[dict, float], Tuple[float, float]]] = None
        self._telemetry = {"abs": 0.0, "tc": 0.0, "oversteer": 0.0, "understeer": 0.0}

        self._last_low_out = 0.0
        self._last_high_out = 0.0

        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._start_time = time.time()

    def set_haptic_controller(self, controller):
        with self._lock:
            self._haptic_controller = controller

    def set_frequency(self, freq_hz: int):
        """Sets the synthesizer sample rate in Hz (e.g. 50, 200, 1000)."""
        valid_freq = max(10, min(2000, freq_hz))
        with self._lock:
            self._freq_hz = valid_freq
            self._interval_s = 1.0 / valid_freq

    def get_frequency(self) -> int:
        with self._lock:
            return self._freq_hz

    def set_compiled_func(self, func: Optional[Callable[[dict, float], Tuple[float, float]]]):
        """Hot-reloads the compiled Python evaluation function atomically."""
        with self._lock:
            self._compiled_func = func

    def _assign_channel_triplet(self, key_base: str, val: float, left: Optional[float], right: Optional[float]) -> None:
        """SLAP Helper: Assigns main, left, and right telemetry channel values with fallback."""
        val_f = float(val)
        self._telemetry[key_base] = val_f
        l_key = f"{key_base}_l" if key_base not in ["oversteer", "understeer"] else ("over_l" if key_base == "oversteer" else "und_l")
        r_key = f"{key_base}_r" if key_base not in ["oversteer", "understeer"] else ("over_r" if key_base == "oversteer" else "und_r")
        self._telemetry[l_key] = float(left) if left is not None else val_f
        self._telemetry[r_key] = float(right) if right is not None else val_f

    def update_telemetry(
        self,
        abs_val: float = 0.0, abs_l: Optional[float] = None, abs_r: Optional[float] = None,
        tc_val: float = 0.0, tc_l: Optional[float] = None, tc_r: Optional[float] = None,
        over_val: float = 0.0, over_l: Optional[float] = None, over_r: Optional[float] = None,
        und_val: float = 0.0, und_l: Optional[float] = None, und_r: Optional[float] = None,
        over_rev: float = 0.0, under_rev: float = 0.0, rpm: float = 0.0, gear: float = 0.0,
        travel_val: float = 0.0, travel_l: Optional[float] = None, travel_r: Optional[float] = None,
        travel_fl: Optional[float] = None, travel_fr: Optional[float] = None,
        travel_rl: Optional[float] = None, travel_rr: Optional[float] = None,
        grip_val: float = 1.0, grip_l: Optional[float] = None, grip_r: Optional[float] = None,
        in_realtime: bool = True
    ):
        """Updates live telemetry input values thread-safely for all channels (CCN < 4)."""
        with self._lock:
            if not in_realtime:
                for k in self._telemetry:
                    self._telemetry[k] = 0.0
                self._telemetry["gear"] = float(gear)
                self._telemetry["grip"] = 1.0
                self._telemetry["grip_l"] = 1.0
                self._telemetry["grip_r"] = 1.0
                return

            self._assign_channel_triplet("abs", abs_val, abs_l, abs_r)
            self._assign_channel_triplet("tc", tc_val, tc_l, tc_r)
            self._assign_channel_triplet("oversteer", over_val, over_l, over_r)
            self._assign_channel_triplet("understeer", und_val, und_l, und_r)

            self._telemetry["over_rev"] = float(over_rev)
            self._telemetry["under_rev"] = float(under_rev)
            self._telemetry["rpm"] = float(rpm)
            self._telemetry["gear"] = float(gear)

            self._assign_channel_triplet("travel", travel_val, travel_l, travel_r)
            self._telemetry["travel_fl"] = float(travel_fl) if travel_fl is not None else float(travel_val)
            self._telemetry["travel_fr"] = float(travel_fr) if travel_fr is not None else float(travel_val)
            self._telemetry["travel_rl"] = float(travel_rl) if travel_rl is not None else float(travel_val)
            self._telemetry["travel_rr"] = float(travel_rr) if travel_rr is not None else float(travel_val)

            self._assign_channel_triplet("grip", grip_val, grip_l, grip_r)

    def get_current_outputs(self) -> Tuple[float, float]:
        """Returns the most recent calculated (low_freq_rumble, high_freq_buzz) outputs."""
        with self._lock:
            return self._last_low_out, self._last_high_out

    def start(self):
        """Starts the high-frequency synthesizer background loop thread."""
        if self._running:
            return
        self._running = True
        self._start_time = time.time()
        self._thread = threading.Thread(target=self._synthesis_loop, daemon=True, name="HapticSynthesizerThread")
        self._thread.start()

    def stop(self):
        """Stops the synthesizer thread and silences motors."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        if self._haptic_controller and hasattr(self._haptic_controller, "set_vibration"):
            try:
                self._haptic_controller.set_vibration(left_low=0.0, left_high=0.0, right_low=0.0, right_high=0.0, duration_ms=10)
            except Exception:
                pass

    def _synthesis_loop(self):
        """High-precision real-time synthesis loop running at target sample rate."""
        next_tick = time.perf_counter()

        while self._running:
            now = time.perf_counter()
            t_elapsed = time.time() - self._start_time

            with self._lock:
                func = self._compiled_func
                telemetry = dict(self._telemetry)
                controller = self._haptic_controller
                interval = self._interval_s

            low_out, high_out = 0.0, 0.0

            if func:
                try:
                    low_out, high_out = func(telemetry, t_elapsed)
                except Exception:
                    low_out, high_out = 0.0, 0.0

            with self._lock:
                self._last_low_out = low_out
                self._last_high_out = high_out

            # Hardware vibration update
            if controller and hasattr(controller, "is_connected") and controller.is_connected():
                try:
                    duration = int(max(10, interval * 2000))
                    controller.set_vibration(left_low=low_out, left_high=0.0, right_low=0.0, right_high=high_out, duration_ms=duration)
                except Exception:
                    pass

            # Precise timing control for target frequency
            next_tick += interval
            sleep_time = next_tick - time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                # If we overshot interval, catch up
                next_tick = time.perf_counter()
