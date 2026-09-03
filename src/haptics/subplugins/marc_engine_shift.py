"""
SimPad Haptics Subplugin — Engine Shift & Rev Limiter (Marc Profile).
Monitors engine RPM regime, producing a distinctive Sawtooth buzz on over-rev (redline / upshift point)
and smooth sine rumble on under-rev (low RPM / downshift indicator).
"""

from __future__ import annotations
from typing import List
from src.engineer.params import RoleParam, FloatRangeParam, ChoiceParam, BoolParam
from src.haptics.models import HapticMotorOutput
from src.haptics.math_engine import apply_response_curve, generate_waveform, WaveformShape
from src.haptics.telemetry_math import calc_engine_rev_state
from src.haptics.subplugins.base import BaseHapticSubplugin
from src.telemetry.sensors import VehicleSensors


class MarcEngineShiftSubplugin(BaseHapticSubplugin):
    """
    Engine Shift & Rev Limiter Haptic Feedback subplugin derived from 'Marc Profile'.
    Provides haptic cues for ideal upshifts (20 Hz Sawtooth on over-rev) and downshifts (20 Hz Sine on under-rev).
    """

    def __init__(self, enabled: bool = True):
        super().__init__(
            subplugin_id="marc_engine_shift",
            name="Engine Shift & Rev Limiter (Marc Profile)",
            description="Tactile shift cues and rev-limiter alerts (Sawtooth pulse on redline upshift, Sine on downshift).",
            icon="🔄",
            enabled=enabled,
            master_gain=1.0,
        )

    def get_declared_params(self) -> List[RoleParam]:
        return [
            FloatRangeParam(
                name="overrev_gain",
                label="Over-Rev / Upshift Gain",
                description="Vibration intensity for rev-limiter & upshift warning",
                min_val=0.1,
                max_val=2.0,
                step=0.05,
                unit="x",
                default=1.00,
            ),
            FloatRangeParam(
                name="overrev_gamma",
                label="Over-Rev Gamma Curve",
                description="Exponent curve for over-rev response (0.25 in Marc Profile for instant punch)",
                min_val=0.1,
                max_val=2.0,
                step=0.05,
                default=0.25,
            ),
            FloatRangeParam(
                name="overrev_freq",
                label="Over-Rev Frequency",
                description="Frequency of the over-rev warning pulse in Hertz",
                min_val=5.0,
                max_val=100.0,
                step=1.0,
                unit="Hz",
                default=20.0,
            ),
            ChoiceParam(
                name="overrev_shape",
                label="Over-Rev Waveform",
                description="Waveform shape for upshift cue",
                choices=[s.value for s in WaveformShape],
                default=WaveformShape.SAWTOOTH.value,
            ),
            FloatRangeParam(
                name="underrev_gain",
                label="Under-Rev / Downshift Gain",
                description="Vibration intensity for low RPM & downshift indicator",
                min_val=0.0,
                max_val=2.0,
                step=0.05,
                unit="x",
                default=1.00,
            ),
            FloatRangeParam(
                name="underrev_gamma",
                label="Under-Rev Gamma Curve",
                description="Exponent curve for under-rev response",
                min_val=0.1,
                max_val=2.0,
                step=0.05,
                default=0.25,
            ),
            FloatRangeParam(
                name="underrev_freq",
                label="Under-Rev Frequency",
                description="Frequency of the under-rev vibration in Hertz",
                min_val=5.0,
                max_val=100.0,
                step=1.0,
                unit="Hz",
                default=20.0,
            ),
            ChoiceParam(
                name="underrev_shape",
                label="Under-Rev Waveform",
                description="Waveform shape for downshift cue",
                choices=[s.value for s in WaveformShape],
                default=WaveformShape.SINE.value,
            ),
            FloatRangeParam(
                name="upshift_rpm_pct",
                label="Upshift RPM Threshold",
                description="RPM percentage of redline where upshift vibration begins",
                min_val=0.80,
                max_val=0.99,
                step=0.01,
                unit="%",
                default=0.90,
            ),
            FloatRangeParam(
                name="downshift_rpm_pct",
                label="Downshift RPM Threshold",
                description="RPM percentage below which downshift vibration begins",
                min_val=0.20,
                max_val=0.60,
                step=0.01,
                unit="%",
                default=0.45,
            ),
        ]

    def evaluate(self, sensors: VehicleSensors, time_s: float) -> HapticMotorOutput:
        if not self.enabled or self.master_gain <= 0.001:
            return HapticMotorOutput()

        # Extract parameters
        o_gain = float(self.get_param("overrev_gain", 1.00))
        o_gamma = float(self.get_param("overrev_gamma", 0.25))
        o_freq = float(self.get_param("overrev_freq", 20.0))
        o_shape = str(self.get_param("overrev_shape", WaveformShape.SAWTOOTH.value))

        u_gain = float(self.get_param("underrev_gain", 1.00))
        u_gamma = float(self.get_param("underrev_gamma", 0.25))
        u_freq = float(self.get_param("underrev_freq", 20.0))
        u_shape = str(self.get_param("underrev_shape", WaveformShape.SINE.value))

        up_pct = float(self.get_param("upshift_rpm_pct", 0.90))
        down_pct = float(self.get_param("downshift_rpm_pct", 0.45))

        # Calculate telemetry engine state
        rev_data = calc_engine_rev_state(sensors, upshift_rpm_pct=up_pct, downshift_rpm_pct=down_pct)
        raw_over = rev_data["over_rev"]
        raw_under = rev_data["under_rev"]

        # Over-rev computation -> High-frequency motor
        curved_over = apply_response_curve(raw_over, gamma=o_gamma, gain=o_gain, min_cutoff=0.0)
        vibe_over = generate_waveform(
            shape=o_shape,
            time_s=time_s,
            frequency_hz=o_freq,
            duty_cycle=1.0,
            amplitude=curved_over
        ) * self.master_gain

        # Under-rev computation -> Low-frequency motor
        curved_under = apply_response_curve(raw_under, gamma=u_gamma, gain=u_gain, min_cutoff=0.0)
        vibe_under = generate_waveform(
            shape=u_shape,
            time_s=time_s,
            frequency_hz=u_freq,
            duty_cycle=1.0,
            amplitude=curved_under
        ) * self.master_gain

        return HapticMotorOutput(
            left_low=vibe_under,
            right_high=vibe_over,
        )
