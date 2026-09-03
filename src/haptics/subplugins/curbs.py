"""
SimPad Haptics Subplugin — Curbs & Suspension Bumps.
Translates left and right suspension travel / kerb compression into directional rumble.
"""

from __future__ import annotations
from typing import List
from src.engineer.params import RoleParam, FloatRangeParam, ChoiceParam
from src.haptics.models import HapticMotorOutput
from src.haptics.math_engine import apply_response_curve, generate_waveform, WaveformShape
from src.haptics.telemetry_math import calc_wheel_travel_impacts
from src.haptics.subplugins.base import BaseHapticSubplugin
from src.telemetry.sensors import VehicleSensors


class CurbsHapticSubplugin(BaseHapticSubplugin):
    """
    Curbs & Road Bump Haptic Feedback subplugin.
    Applies a 1.5 gain, 0.8 gamma curve and 35 Hz sawtooth scrub on suspension compression.
    """

    def __init__(self, enabled: bool = False):
        super().__init__(
            subplugin_id="curbs",
            name="Curbs & Suspension Bumps",
            description="Directional rumble when riding track kerbs or encountering severe road bumps.",
            icon="🏁",
            enabled=enabled,
            master_gain=1.0,
        )

    def get_declared_params(self) -> List[RoleParam]:
        return [
            FloatRangeParam(
                name="gain",
                label="Effect Gain",
                description="Linear amplification factor for curb vibration",
                min_val=0.1,
                max_val=3.0,
                step=0.05,
                unit="x",
                default=1.50,
            ),
            FloatRangeParam(
                name="gamma",
                label="Response Gamma",
                description="Response curve exponent",
                min_val=0.1,
                max_val=2.0,
                step=0.05,
                default=0.80,
            ),
            FloatRangeParam(
                name="threshold",
                label="Bump Cutoff Threshold",
                description="Minimum suspension travel before curb vibration triggers",
                min_val=0.01,
                max_val=0.30,
                step=0.01,
                unit="%",
                default=0.08,
            ),
            FloatRangeParam(
                name="frequency",
                label="Vibration Frequency",
                description="Frequency of curb impact pulses in Hertz",
                min_val=10.0,
                max_val=100.0,
                step=1.0,
                unit="Hz",
                default=35.0,
            ),
            ChoiceParam(
                name="shape",
                label="Waveform Shape",
                description="Modulation waveform envelope shape",
                choices=[s.value for s in WaveformShape],
                default=WaveformShape.SAWTOOTH.value,
            ),
            FloatRangeParam(
                name="duty",
                label="Duty Cycle",
                description="Active pulse ratio in each period",
                min_val=0.1,
                max_val=1.0,
                step=0.05,
                default=0.40,
            ),
        ]

    def evaluate(self, sensors: VehicleSensors, time_s: float) -> HapticMotorOutput:
        if not self.enabled or self.master_gain <= 0.001:
            return HapticMotorOutput()

        gain = float(self.get_param("gain", 1.50))
        gamma = float(self.get_param("gamma", 0.80))
        thresh = float(self.get_param("threshold", 0.08))
        freq = float(self.get_param("frequency", 35.0))
        shape = str(self.get_param("shape", WaveformShape.SAWTOOTH.value))
        duty = float(self.get_param("duty", 0.40))

        travel_data = calc_wheel_travel_impacts(sensors)
        trv_l = travel_data["travel_left"]
        trv_r = travel_data["travel_right"]

        curved_l = apply_response_curve(trv_l, gamma=gamma, gain=gain, min_cutoff=thresh)
        curved_r = apply_response_curve(trv_r, gamma=gamma, gain=gain, min_cutoff=thresh)

        vibe_l = generate_waveform(shape, time_s, freq, duty, amplitude=curved_l) * self.master_gain
        vibe_r = generate_waveform(shape, time_s, freq, duty, amplitude=curved_r) * self.master_gain

        return HapticMotorOutput(
            left_low=vibe_l,
            right_high=vibe_r,
        )
