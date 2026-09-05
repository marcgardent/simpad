"""
SimPulse Haptics Subplugin — TC & Wheelspin (Marc Profile).
Extracts official ECU Traction Control / rear wheel spin telemetry, applies non-linear response curves,
and synthesizes high-frequency 144 Hz sinusoidal buzz to the High Frequency (Right) XInput motor.
"""

from __future__ import annotations
from typing import List
from simpulse.core.params import RoleParam, FloatRangeParam, ChoiceParam, BoolParam
from ..models import HapticMotorOutput
from ..math_engine import apply_response_curve, generate_waveform, WaveformShape
from ..telemetry_math import calc_tc_wheelspin
from .base import BaseHapticSubplugin
from simpulse.core.telemetry.sensors import VehicleSensors


class MarcTcSubplugin(BaseHapticSubplugin):
    """
    Traction Control & Wheelspin Haptic Feedback subplugin derived from 'Marc Profile'.
    Applies a 1.81 gain, 0.7 gamma curve and 144 Hz sine pulse on wheelspin / TC activation.
    """

    def __init__(self):
        super().__init__(
            subplugin_id="marc_tc",
            name="TC & Wheelspin (Marc Profile)",
            description="High-definition 144 Hz sinusoidal buzz on Traction Control activation and power wheelspin.",
            icon="⚡",
        )

    def get_declared_params(self) -> List[RoleParam]:
        return [
            FloatRangeParam(
                name="gain",
                label="Effect Gain",
                description="Linear amplification factor for TC vibration",
                min_val=0.1,
                max_val=3.0,
                step=0.05,
                unit="x",
                default=1.81,
            ),
            FloatRangeParam(
                name="gamma",
                label="Response Gamma",
                description="Response curve exponent (<1.0 boosts subtle wheelspin, >1.0 makes it progressive)",
                min_val=0.1,
                max_val=2.0,
                step=0.05,
                default=0.70,
            ),
            FloatRangeParam(
                name="threshold",
                label="Cutoff Threshold",
                description="Minimum wheelspin level before vibration triggers",
                min_val=0.0,
                max_val=0.50,
                step=0.01,
                unit="%",
                default=0.0,
            ),
            FloatRangeParam(
                name="frequency",
                label="Waveform Frequency",
                description="Frequency of the vibration pulsation in Hertz",
                min_val=10.0,
                max_val=300.0,
                step=1.0,
                unit="Hz",
                default=144.0,
            ),
            ChoiceParam(
                name="shape",
                label="Waveform Shape",
                description="Modulation waveform envelope shape",
                choices=[s.value for s in WaveformShape],
                default=WaveformShape.SINE.value,
            ),
            FloatRangeParam(
                name="duty",
                label="Duty Cycle",
                description="Active pulse ratio in each period (1.0 = continuous wave)",
                min_val=0.1,
                max_val=1.0,
                step=0.05,
                default=1.0,
            ),
            BoolParam(
                name="prefer_ecu",
                label="Prioritize ECU TC Flag",
                description="Detect native ECU Traction Control active signal from car electronics",
                default=True,
            ),
        ]

    def evaluate(self, sensors: VehicleSensors, time_s: float) -> HapticMotorOutput:
        gain = float(self.get_param("gain", 1.81))
        gamma = float(self.get_param("gamma", 0.70))
        thresh = float(self.get_param("threshold", 0.0))
        freq = float(self.get_param("frequency", 144.0))
        shape = str(self.get_param("shape", WaveformShape.SINE.value))
        duty = float(self.get_param("duty", 1.0))
        prefer_ecu = bool(self.get_param("prefer_ecu", True))

        # 1. Calculate raw telemetry TC signal
        left_raw, right_raw, comb_raw = calc_tc_wheelspin(sensors, prefer_ecu=prefer_ecu)

        # 2. Apply parametric curve
        curved_intensity = apply_response_curve(comb_raw, gamma=gamma, gain=gain, min_cutoff=thresh)

        # 3. Apply time-modulated waveform synthesis
        vibe = generate_waveform(
            shape=shape,
            time_s=time_s,
            frequency_hz=freq,
            duty_cycle=duty,
            amplitude=curved_intensity
        )

        # 4. Route to Right Motor (High Frequency Buzz on XInput)
        return HapticMotorOutput(right_high=vibe)
