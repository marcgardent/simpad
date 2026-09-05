"""
SimPad Haptics Subplugin — Tire Grip Loss Warning.
Monitors the global tire friction envelope and vibrates when overall grip drops below safe traction limits.
"""

from __future__ import annotations
from typing import List
from simpad_qt.core.params import RoleParam, FloatRangeParam, ChoiceParam
from ..models import HapticMotorOutput
from ..math_engine import apply_response_curve, generate_waveform, WaveformShape
from ..telemetry_math import calc_tire_grip_loss
from .base import BaseHapticSubplugin
from simpad_qt.core.telemetry.sensors import VehicleSensors


class TireGripHapticSubplugin(BaseHapticSubplugin):
    """
    Tire Grip Fraction / Loss Warning Haptic Feedback subplugin.
    Activates a distinct tactile buzz whenever tire contact patch grip falls below a configurable threshold.
    """

    def __init__(self):
        super().__init__(
            subplugin_id="grip",
            name="Tire Grip Loss Warning",
            description="Warns when tires exceed their maximum grip coefficient and begin losing traction.",
            icon="🛞",
        )

    def get_declared_params(self) -> List[RoleParam]:
        return [
            FloatRangeParam(
                name="gain",
                label="Effect Gain",
                description="Linear amplification factor for grip loss vibration",
                min_val=0.1,
                max_val=3.0,
                step=0.05,
                unit="x",
                default=1.30,
            ),
            FloatRangeParam(
                name="grip_loss_thresh",
                label="Grip Loss Threshold",
                description="Trigger vibration when grip loss exceeds this ratio (e.g. 0.20 = 20% traction loss)",
                min_val=0.05,
                max_val=0.50,
                step=0.01,
                unit="%",
                default=0.15,
            ),
            FloatRangeParam(
                name="frequency",
                label="Vibration Frequency",
                description="Modulation frequency in Hertz",
                min_val=10.0,
                max_val=150.0,
                step=1.0,
                unit="Hz",
                default=60.0,
            ),
            ChoiceParam(
                name="shape",
                label="Waveform Shape",
                description="Modulation waveform envelope shape",
                choices=[s.value for s in WaveformShape],
                default=WaveformShape.SQUARE.value,
            ),
        ]

    def evaluate(self, sensors: VehicleSensors, time_s: float) -> HapticMotorOutput:
        gain = float(self.get_param("gain", 1.30))
        thresh = float(self.get_param("grip_loss_thresh", 0.15))
        freq = float(self.get_param("frequency", 60.0))
        shape = str(self.get_param("shape", WaveformShape.SQUARE.value))

        grip_data = calc_tire_grip_loss(sensors)
        loss_l = grip_data["grip_loss_left"]
        loss_r = grip_data["grip_loss_right"]

        curved_l = apply_response_curve(loss_l, gamma=1.0, gain=gain, min_cutoff=thresh)
        curved_r = apply_response_curve(loss_r, gamma=1.0, gain=gain, min_cutoff=thresh)

        vibe_l = generate_waveform(shape, time_s, freq, duty_cycle=0.5, amplitude=curved_l)
        vibe_r = generate_waveform(shape, time_s, freq, duty_cycle=0.5, amplitude=curved_r)

        return HapticMotorOutput(
            left_low=vibe_l,
            right_high=vibe_r,
        )
