"""
SimPulse Haptics Subplugin — Lateral Slip (Oversteer & Understeer).
Provides progressive rumble on cornering grip loss, rear-end drift, and front-end scrub.
"""

from __future__ import annotations
from typing import List
from simpulse.core.params import RoleParam, FloatRangeParam, ChoiceParam
from ..models import HapticMotorOutput
from ..math_engine import apply_response_curve, generate_waveform, WaveformShape
from ..telemetry_math import calc_oversteer_slip, calc_understeer_scrub
from .base import BaseHapticSubplugin
from simpulse.core.telemetry.sensors import VehicleSensors


class SlipHapticSubplugin(BaseHapticSubplugin):
    """
    Lateral Slip Haptic Feedback subplugin.
    Translates rear axle oversteer (drift) and front axle understeer (pushing/scrub) into rumble cues.
    """

    def __init__(self):
        super().__init__(
            subplugin_id="slip",
            name="Lateral Slip (Drift & Scrub)",
            description="Tactile feedback on cornering lateral slip (Oversteer drift on right motor, Understeer push on left motor).",
            icon="🏎️",
        )

    def get_declared_params(self) -> List[RoleParam]:
        return [
            FloatRangeParam(
                name="oversteer_gain",
                label="Oversteer Gain",
                description="Amplification for rear axle slide (Oversteer)",
                min_val=0.1,
                max_val=3.0,
                step=0.05,
                unit="x",
                default=1.20,
            ),
            FloatRangeParam(
                name="oversteer_thresh",
                label="Oversteer Threshold",
                description="Minimum rear slip before oversteer vibration triggers",
                min_val=0.01,
                max_val=0.40,
                step=0.01,
                unit="%",
                default=0.10,
            ),
            FloatRangeParam(
                name="understeer_gain",
                label="Understeer Gain",
                description="Amplification for front axle push (Understeer)",
                min_val=0.1,
                max_val=3.0,
                step=0.05,
                unit="x",
                default=1.00,
            ),
            FloatRangeParam(
                name="understeer_thresh",
                label="Understeer Threshold",
                description="Minimum front slip before understeer vibration triggers",
                min_val=0.01,
                max_val=0.40,
                step=0.01,
                unit="%",
                default=0.10,
            ),
            FloatRangeParam(
                name="frequency",
                label="Vibration Frequency",
                description="Modulation frequency in Hertz",
                min_val=10.0,
                max_val=120.0,
                step=1.0,
                unit="Hz",
                default=45.0,
            ),
            ChoiceParam(
                name="shape",
                label="Waveform Shape",
                description="Modulation waveform envelope shape",
                choices=[s.value for s in WaveformShape],
                default=WaveformShape.SAWTOOTH.value,
            ),
        ]

    def evaluate(self, sensors: VehicleSensors, time_s: float) -> HapticMotorOutput:
        o_gain = float(self.get_param("oversteer_gain", 1.20))
        o_thresh = float(self.get_param("oversteer_thresh", 0.10))
        u_gain = float(self.get_param("understeer_gain", 1.00))
        u_thresh = float(self.get_param("understeer_thresh", 0.10))
        freq = float(self.get_param("frequency", 45.0))
        shape = str(self.get_param("shape", WaveformShape.SAWTOOTH.value))

        _, _, over_comb = calc_oversteer_slip(sensors)
        _, _, under_comb = calc_understeer_scrub(sensors)

        curved_over = apply_response_curve(over_comb, gamma=1.0, gain=o_gain, min_cutoff=o_thresh)
        curved_under = apply_response_curve(under_comb, gamma=1.0, gain=u_gain, min_cutoff=u_thresh)

        vibe_over = generate_waveform(shape, time_s, freq, duty_cycle=0.8, amplitude=curved_over)
        vibe_under = generate_waveform(shape, time_s, freq, duty_cycle=0.8, amplitude=curved_under)

        return HapticMotorOutput(
            left_low=vibe_under,
            right_high=vibe_over,
        )
