"""
SimPulse Qt6 Mock Telemetry Generator.
Generates realistic racing telemetry waveforms, sectors, and live deltas for offline testing and visualization.
"""

import math
import time
from typing import Optional
from PySide6.QtCore import QObject, QTimer, Signal
from simpulse.core.telemetry import VehicleSensors


class MockTelemetryGenerator(QObject):
    """
    Generates realistic 60 FPS vehicle telemetry simulating a GT3/Hypercar lap.
    Emits VehicleSensors at regular intervals with coordinated physics, timing, and deltas.
    """

    frame_ready = Signal(object)  # VehicleSensors

    def __init__(self, fps: int = 60, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.fps = fps
        self._timer = QTimer(self)
        self._timer.setInterval(int(1000 / fps))
        self._timer.timeout.connect(self._step)

        self._t: float = 0.0
        self._running = False
        self._lap_count = 1
        self._lap_dist = 0.0
        self._track_len = 4500.0  # 4.5 km track
        self._freeze_until = 0.0
        self._last_completed_time = 89.742

    def start(self) -> None:
        self._running = True
        self._t = 0.0
        self._lap_dist = 0.0
        self._timer.start()

    def stop(self) -> None:
        self._running = False
        self._timer.stop()

    @property
    def is_running(self) -> bool:
        return self._running

    def _step(self) -> None:
        dt = 1.0 / self.fps
        self._t += dt

        # Simulate a 30s cyclic track section (straight -> heavy braking -> hairpin -> acceleration)
        cycle = self._t % 30.0

        sensors = VehicleSensors()
        sensors.in_realtime = True
        sensors.engine_max_rpm = 8500.0

        if cycle < 10.0:
            # 1. Straight line acceleration (0-10s)
            progress = cycle / 10.0
            sensors.vehicle_speed = 30.0 + progress * 55.0  # 108 to 306 km/h
            sensors.unfiltered_throttle = 1.0
            sensors.unfiltered_brake = 0.0

            # Dynamic gear and RPM based on speed
            spd_kmh = sensors.vehicle_speed * 3.6
            if spd_kmh < 130:
                sensors.gear = 3
                sensors.engine_rpm = 5000 + (spd_kmh - 100) * 80
            elif spd_kmh < 180:
                sensors.gear = 4
                sensors.engine_rpm = 5200 + (spd_kmh - 130) * 60
            elif spd_kmh < 240:
                sensors.gear = 5
                sensors.engine_rpm = 5500 + (spd_kmh - 180) * 45
            else:
                sensors.gear = 6
                sensors.engine_rpm = 6000 + (spd_kmh - 240) * 35

            # Brief TC slip when accelerating hard
            if cycle < 2.0:
                sensors.rear_left_spin = 0.15 * math.sin(cycle * 10) ** 2
                sensors.rear_right_spin = 0.15 * math.sin(cycle * 10) ** 2
                sensors.ecu_tc_active_raw = True

        elif cycle < 16.0:
            # 2. Heavy braking zone (10-16s)
            brk_prog = (cycle - 10.0) / 6.0
            sensors.vehicle_speed = max(18.0, 85.0 - brk_prog * 67.0)  # 306 down to 65 km/h
            sensors.unfiltered_throttle = 0.0
            sensors.unfiltered_brake = max(0.0, 0.95 - brk_prog * 0.4)

            spd_kmh = sensors.vehicle_speed * 3.6
            if spd_kmh > 200:
                sensors.gear = 5
                sensors.engine_rpm = 6800 - brk_prog * 1000
            elif spd_kmh > 140:
                sensors.gear = 4
                sensors.engine_rpm = 6500 - brk_prog * 1200
            elif spd_kmh > 90:
                sensors.gear = 3
                sensors.engine_rpm = 6200 - brk_prog * 1500
            else:
                sensors.gear = 2
                sensors.engine_rpm = 5000 - brk_prog * 1000

            # ABS activation during initial heavy brake pressure
            if cycle < 13.0:
                abs_pulse = abs(math.sin(cycle * 25))
                sensors.front_left_lock = 0.25 * abs_pulse
                sensors.front_right_lock = 0.22 * abs_pulse
                sensors.ecu_abs_active_raw = True

        elif cycle < 22.0:
            # 3. Corner apex / lateral load (16-22s)
            turn_prog = (cycle - 16.0) / 6.0
            sensors.gear = 2
            sensors.vehicle_speed = 20.0 + math.sin(turn_prog * math.pi) * 8.0
            sensors.engine_rpm = 4500.0 + turn_prog * 1500.0
            sensors.unfiltered_throttle = 0.4 + turn_prog * 0.4
            sensors.unfiltered_brake = 0.0

            # Lateral slip
            lat_factor = math.sin(turn_prog * math.pi)
            sensors.front_left_lat_slip = 0.4 * lat_factor
            sensors.rear_left_lat_slip = 0.35 * lat_factor
            sensors.front_right_lat_slip = 0.1
            sensors.rear_right_lat_slip = 0.1
            sensors.front_left_grip = max(0.5, 1.0 - 0.5 * lat_factor)

        else:
            # 4. Corner exit & upshifts (22-30s)
            exit_prog = (cycle - 22.0) / 8.0
            sensors.vehicle_speed = 28.0 + exit_prog * 40.0
            sensors.unfiltered_throttle = 1.0
            sensors.unfiltered_brake = 0.0
            spd_kmh = sensors.vehicle_speed * 3.6
            if spd_kmh < 130:
                sensors.gear = 3
                sensors.engine_rpm = 5000 + (spd_kmh - 100) * 80
            else:
                sensors.gear = 4
                sensors.engine_rpm = 5200 + (spd_kmh - 130) * 60

        # Advance track distance
        self._lap_dist += sensors.vehicle_speed * dt
        if self._lap_dist >= self._track_len:
            self._lap_dist -= self._track_len
            self._lap_count += 1
            self._freeze_until = time.time() + 4.0
            self._last_completed_time = 89.500 + 0.5 * math.sin(self._t)

        now = time.time()
        is_freeze = now < self._freeze_until

        # Compute current sector based on track distance
        s1_dist = self._track_len * 0.33
        s2_dist = self._track_len * 0.66
        if self._lap_dist < s1_dist:
            sensors.current_sector = 1
        elif self._lap_dist < s2_dist:
            sensors.current_sector = 2
        else:
            sensors.current_sector = 3

        # Sector timings & deltas
        sensors.sector1_time = "29.412"
        sensors.sector1_status = "purple"
        sensors.sector1_delta = -0.145

        sensors.sector2_time = "31.850" if sensors.current_sector >= 2 else "--"
        sensors.sector2_status = "green" if sensors.current_sector >= 2 else "default"
        sensors.sector2_delta = -0.082 if sensors.current_sector >= 2 else 0.0

        sensors.sector3_time = "28.480" if sensors.current_sector >= 3 else "--"
        sensors.sector3_status = "green" if sensors.current_sector >= 3 else "default"
        sensors.sector3_delta = -0.057 if sensors.current_sector >= 3 else 0.0

        # Session & timing data
        sensors.fuel_level = max(5.0, 45.2 - (self._t * 0.01))
        sensors.has_delta_reference = True
        sensors.lap_flag = 2
        sensors.delta_time = -0.284 + 0.12 * math.sin(self._t * 0.3)
        sensors.estimated_lap_time = 89.458
        sensors.estimated_lap_time_str = "01:29.458"
        sensors.last_lap_time = self._last_completed_time
        mins = int(self._last_completed_time // 60)
        secs = self._last_completed_time % 60
        sensors.last_lap_time_str = f"{mins:02d}:{secs:06.3f}"
        sensors.last_lap_status = "purple" if self._last_completed_time < 89.6 else "green"
        sensors.is_lap_freeze_active = is_freeze
        sensors.remaining_laps = max(0, 25 - self._lap_count)

        self.frame_ready.emit(sensors)
