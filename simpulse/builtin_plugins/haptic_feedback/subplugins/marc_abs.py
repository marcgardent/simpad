"""
SimPulse Haptics Subplugin — ABS & Wheel Lockup (Marc Profile).
Extracts official ECU ABS / front wheel lockup telemetry, applies non-linear response curves,
and synthesizes high-frequency 144 Hz sinusoidal rumble to the Low Frequency (Left) XInput motor.
"""

from __future__ import annotations
from typing import List
from simpulse.core.params import RoleParam, FloatRangeParam, ChoiceParam, BoolParam
from ..models import HapticMotorOutput
from ..math_engine import apply_response_curve, generate_waveform, WaveformShape
from ..telemetry_math import calc_abs_lockup
from .base import BaseHapticSubplugin
from simpulse.core.telemetry.sensors import VehicleSensors


class MarcAbsSubplugin(BaseHapticSubplugin):
    """
    ABS & Wheel Lockup Haptic Feedback subplugin derived from 'Marc Profile'.
    Applies a 1.8 gain, 0.7 gamma curve and 144 Hz sine pulse on braking lock / ABS activation.
    """

    def __init__(self):
        super().__init__(
            subplugin_id="marc_abs",
            name="ABS & Wheel Lockup (Marc Profile)",
            description="High-definition 144 Hz sinusoidal pulsing on ABS activation and front wheel lockups.",
            icon="🛑",
        )

    def get_declared_params(self) -> List[RoleParam]:
        return [
            FloatRangeParam(
                name="gain",
                label="Effect Gain",
                description="Linear amplification factor for ABS vibration",
                min_val=0.1,
                max_val=3.0,
                step=0.05,
                unit="x",
                default=1.80,
            ),
            FloatRangeParam(
                name="gamma",
                label="Response Gamma",
                description="Response curve exponent (<1.0 boosts subtle lockups, >1.0 makes it progressive)",
                min_val=0.1,
                max_val=2.0,
                step=0.05,
                default=0.70,
            ),
            FloatRangeParam(
                name="threshold",
                label="Cutoff Threshold",
                description="Minimum lockup level before vibration triggers",
                min_val=0.0,
                max_val=0.50,
                step=0.01,
                unit="%",
                default=0.0,
            ),
            FloatRangeParam(
                name="frequency",
                label="Waveform Frequency",
                description="Frequency of the sinusoidal vibration pulsation in Hertz",
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
                label="Prioritize ECU ABS Flag",
                description="Detect native ECU ABS active signal from car electronics",
                default=True,
            ),
        ]

    def evaluate(self, sensors: VehicleSensors, time_s: float) -> HapticMotorOutput:
        gain = float(self.get_param("gain", 1.80))
        gamma = float(self.get_param("gamma", 0.70))
        thresh = float(self.get_param("threshold", 0.0))
        freq = float(self.get_param("frequency", 144.0))
        shape = str(self.get_param("shape", WaveformShape.SINE.value))
        duty = float(self.get_param("duty", 1.0))
        prefer_ecu = bool(self.get_param("prefer_ecu", True))

        # 1. Calculate raw telemetry ABS signal
        left_raw, right_raw, comb_raw = calc_abs_lockup(sensors, prefer_ecu=prefer_ecu)

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

        # 4. Route to Left Motor (Low Frequency Rumble on XInput)
        return HapticMotorOutput(left_low=vibe)
