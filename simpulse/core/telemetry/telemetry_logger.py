"""
SimPulse Real-Time Telemetry Diagnostic Logger.
Logs raw UDP telemetry inputs, calculated wheel slip/lock values, and ECU aids in real-time.
Outputs structured tabular traces to 'telemetry_live.log' for deep diagnostics and debugging.
"""

import time
import os
from typing import Optional, Self
from .sensors import VehicleSensors


class TelemetryDiagnosticLogger:
    """
    High-fidelity logger to capture and audit raw vs calculated metrics.
    Logs wheel velocities, slip, lock, raw vs filtered pedals, and ECU signals.
    """

    _instance: Optional[Self] = None

    def __init__(self, log_path: str = "telemetry_live.log", sample_interval_sec: float = 0.10):
        self.log_path = log_path
        self.sample_interval_sec = sample_interval_sec
        self._last_log_time = 0.0
        self._log_file = None
        self._line_count = 0
        self.enabled = True

        # Open file in append mode with line buffering
        try:
            self._log_file = open(self.log_path, "a", encoding="utf-8", buffering=1)
            if os.path.getsize(self.log_path) < 100:
                header = (
                    "=" * 120 + "\n"
                    "SIMPULSE TELEMETRY DIAGNOSTIC TRACE LOG\n"
                    "Format: [TIME] SPEED | GEAR | THROTTLE (Raw/Filt/TC) | BRAKE (Raw/Filt/ABS) | "
                    "WHEELS (FL, FR, RL, RR: Lock%, Slip%, PatchVel, GroundVel) | SYNTH_SIGNALS\n"
                    "=" * 120 + "\n"
                )
                self._log_file.write(header)
                self._log_file.flush()
        except Exception as e:
            print(f"[TelemetryDiagnosticLogger] Error opening file: {e}")

    @classmethod
    def get_instance(cls) -> Self:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def log_sample(
        self,
        sensors: VehicleSensors,
        raw_lpv: tuple = (0.0, 0.0, 0.0, 0.0),
        raw_lgv: tuple = (0.0, 0.0, 0.0, 0.0),
    ) -> None:
        if not self.enabled or self._log_file is None:
            return

        now = time.time()
        # Log if interval elapsed OR on high-dynamic event (brake/throttle stomp, significant lock/spin)
        is_dynamic_event = (
            sensors.unfiltered_brake > 0.20
            or sensors.unfiltered_throttle > 0.20
            or sensors.lock_intensity > 0.10
            or sensors.spin_intensity > 0.10
            or sensors.ecu_abs_active > 0.05
            or sensors.ecu_tc_active > 0.05
        )

        if (now - self._last_log_time < self.sample_interval_sec) and not is_dynamic_event:
            return

        # Throttle rate limit on dynamic events to at least 20ms
        if now - self._last_log_time < 0.02:
            return

        self._last_log_time = now
        self._line_count += 1

        # Format metrics
        speed_kmh = sensors.vehicle_speed * 3.6
        thr_raw = sensors.unfiltered_throttle * 100.0
        thr_filt = (sensors.filtered_throttle if sensors.filtered_throttle is not None else sensors.unfiltered_throttle) * 100.0
        brk_raw = sensors.unfiltered_brake * 100.0
        brk_filt = (sensors.filtered_brake if sensors.filtered_brake is not None else sensors.unfiltered_brake) * 100.0

        tc_ecu = sensors.ecu_tc_active * 100.0
        abs_ecu = sensors.ecu_abs_active * 100.0

        # Wheels FL, FR, RL, RR
        fl_lock = sensors.front_left_lock * 100.0
        fl_slip = max(sensors.front_left_spin, sensors.front_left_lat_slip) * 100.0
        fr_lock = sensors.front_right_lock * 100.0
        fr_slip = max(sensors.front_right_spin, sensors.front_right_lat_slip) * 100.0
        rl_lock = sensors.rear_left_lock * 100.0
        rl_slip = max(sensors.rear_left_spin, sensors.rear_left_lat_slip) * 100.0
        rr_lock = sensors.rear_right_lock * 100.0
        rr_slip = max(sensors.rear_right_spin, sensors.rear_right_lat_slip) * 100.0

        lpv_fl, lpv_fr, lpv_rl, lpv_rr = (raw_lpv + (0.0, 0.0, 0.0, 0.0))[:4]
        lgv_fl, lgv_fr, lgv_rl, lgv_rr = (raw_lgv + (0.0, 0.0, 0.0, 0.0))[:4]

        t_stamp = time.strftime("%H:%M:%S", time.localtime(now)) + f".{int((now % 1) * 1000):03d}"

        abs_gauge = sensors.ecu_abs_active * 100.0
        tc_gauge = max(sensors.ecu_tc_active, sensors.spin_intensity) * 100.0

        line = (
            f"[{t_stamp}] V={speed_kmh:5.1f}km/h G={sensors.gear:1d} | "
            f"THROTTLE: Raw={thr_raw:3.0f}% Filt={thr_filt:3.0f}% (TC_ECU={tc_ecu:3.0f}%, TC_Gauge={tc_gauge:3.0f}%) | "
            f"BRAKE: Raw={brk_raw:3.0f}% Filt={brk_filt:3.0f}% (ABS_ECU={abs_ecu:3.0f}%, ABS_Gauge={abs_gauge:3.0f}%) | "
            f"FL: Lk={fl_lock:3.0f}% Sl={fl_slip:3.0f}% (pv={lpv_fl:4.1f} gv={lgv_fl:4.1f}) | "
            f"FR: Lk={fr_lock:3.0f}% Sl={fr_slip:3.0f}% (pv={lpv_fr:4.1f} gv={lgv_fr:4.1f}) | "
            f"RL: Lk={rl_lock:3.0f}% Sl={rl_slip:3.0f}% (pv={lpv_rl:4.1f} gv={lgv_rl:4.1f}) | "
            f"RR: Lk={rr_lock:3.0f}% Sl={rr_slip:3.0f}% (pv={lpv_rr:4.1f} gv={lgv_rr:4.1f}) | "
            f"SYNTH: LockMax={sensors.lock_intensity*100:3.0f}% SpinMax={sensors.spin_intensity*100:3.0f}% "
            f"[ECU_Flags: abs={sensors.ecu_abs_active_raw}, tc={sensors.ecu_tc_active_raw}, abs_lvl={sensors.ecu_abs_level}]\n"
        )

        try:
            self._log_file.write(line)
            self._log_file.flush()
        except Exception:
            pass

    def close(self):
        if self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None
