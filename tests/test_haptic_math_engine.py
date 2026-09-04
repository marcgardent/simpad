"""
Unit tests for SimPad Haptics Math Engine and Waveform Synthesis.
"""

import pytest
import math
from simpad_qt.core.haptics.math_engine import (
    clamp,
    lerp,
    normalize_signal,
    invert_signal,
    apply_response_curve,
    generate_waveform,
    WaveformShape,
)


def test_clamp():
    assert clamp(0.5, 0.0, 1.0) == 0.5
    assert clamp(-0.5, 0.0, 1.0) == 0.0
    assert clamp(1.5, 0.0, 1.0) == 1.0
    assert clamp(5.0, 2.0, 4.0) == 4.0


def test_lerp():
    assert lerp(10.0, 20.0, 0.0) == 10.0
    assert lerp(10.0, 20.0, 1.0) == 20.0
    assert lerp(10.0, 20.0, 0.5) == 15.0


def test_normalize_signal():
    assert normalize_signal(50.0, 0.0, 100.0) == 0.5
    assert normalize_signal(-10.0, 0.0, 100.0) == 0.0
    assert normalize_signal(150.0, 0.0, 100.0) == 1.0
    assert normalize_signal(150.0, 0.0, 100.0, clamp_output=False) == 1.5


def test_invert_signal():
    assert invert_signal(0.2, max_val=1.0) == pytest.approx(0.8)
    assert invert_signal(1.0, max_val=1.0) == 0.0
    assert invert_signal(0.0, max_val=1.0) == 1.0


def test_apply_response_curve_threshold():
    # Value below cutoff should produce 0.0
    assert apply_response_curve(0.05, gamma=1.0, gain=1.0, min_cutoff=0.10) == 0.0
    # Value at cutoff should produce 0.0
    assert apply_response_curve(0.10, gamma=1.0, gain=1.0, min_cutoff=0.10) == 0.0
    # Value above cutoff should scale linearly when gamma=1.0
    assert apply_response_curve(0.55, gamma=1.0, gain=1.0, min_cutoff=0.10) == pytest.approx(0.5, abs=0.01)


def test_apply_response_curve_gamma_and_gain():
    # Linear gamma=1.0, gain=1.8 (Marc Profile ABS)
    res_half = apply_response_curve(0.5, gamma=1.0, gain=1.8, min_cutoff=0.0)
    assert res_half == pytest.approx(0.9)

    # Clamping to 1.0
    res_full = apply_response_curve(1.0, gamma=1.0, gain=1.8, min_cutoff=0.0)
    assert res_full == 1.0

    # Gamma = 0.7 (boosts lower inputs)
    res_gamma_boost = apply_response_curve(0.5, gamma=0.7, gain=1.0, min_cutoff=0.0)
    assert res_gamma_boost > 0.5  # 0.5^0.7 approx 0.615
    assert res_gamma_boost == pytest.approx(0.5 ** 0.7, abs=1e-3)


def test_generate_waveform_constant():
    assert generate_waveform(WaveformShape.CONSTANT, time_s=0.0, amplitude=0.8) == 0.8
    assert generate_waveform(WaveformShape.CONSTANT, time_s=1.234, amplitude=0.8) == 0.8
    assert generate_waveform(WaveformShape.CONSTANT, time_s=0.0, amplitude=0.0) == 0.0


def test_generate_waveform_square():
    # 20 Hz -> period is 0.05s. duty = 0.5 -> active for 0.025s
    freq = 20.0
    duty = 0.5
    # time at 0.01s (inside duty window)
    vibe_active = generate_waveform(WaveformShape.SQUARE, time_s=0.01, frequency_hz=freq, duty_cycle=duty, amplitude=1.0)
    assert vibe_active == 1.0

    # time at 0.035s (outside duty window)
    vibe_inactive = generate_waveform(WaveformShape.SQUARE, time_s=0.035, frequency_hz=freq, duty_cycle=duty, amplitude=1.0)
    assert vibe_inactive == 0.0


def test_generate_waveform_sine_smooth():
    # 144 Hz (Marc Profile ABS/TC) with duty = 1.0
    freq = 144.0
    # Phase = 0 -> mod = 0.5 * (1 + sin(-pi/2)) = 0.0
    vibe_start = generate_waveform(WaveformShape.SINE, time_s=0.0, frequency_hz=freq, duty_cycle=1.0, amplitude=1.0)
    assert vibe_start == pytest.approx(0.0, abs=1e-3)

    # Phase = 0.5 (peak) -> mod = 0.5 * (1 + sin(pi/2)) = 1.0
    period = 1.0 / freq
    vibe_peak = generate_waveform(WaveformShape.SINE, time_s=period * 0.5, frequency_hz=freq, duty_cycle=1.0, amplitude=1.0)
    assert vibe_peak == pytest.approx(1.0, abs=1e-3)


def test_generate_waveform_sawtooth():
    freq = 20.0
    period = 1.0 / freq
    # At 25% phase, amplitude = 0.25
    vibe_25 = generate_waveform(WaveformShape.SAWTOOTH, time_s=period * 0.25, frequency_hz=freq, duty_cycle=1.0, amplitude=1.0)
    assert vibe_25 == pytest.approx(0.25, abs=1e-3)

    # At 75% phase, amplitude = 0.75
    vibe_75 = generate_waveform(WaveformShape.SAWTOOTH, time_s=period * 0.75, frequency_hz=freq, duty_cycle=1.0, amplitude=1.0)
    assert vibe_75 == pytest.approx(0.75, abs=1e-3)
