"""
Unit tests for SimPad Haptics Subplugins and Marc Profile Decomposition.
"""

import pytest
from simpad_qt.core.telemetry.sensors import VehicleSensors
from simpad_qt.builtin_plugins.haptic_feedback.models import HapticMotorOutput
from simpad_qt.builtin_plugins.haptic_feedback.subplugins.base import HapticHostSlot
from simpad_qt.builtin_plugins.haptic_feedback.subplugins.marc_abs import MarcAbsSubplugin
from simpad_qt.builtin_plugins.haptic_feedback.subplugins.marc_tc import MarcTcSubplugin
from simpad_qt.builtin_plugins.haptic_feedback.subplugins.marc_engine_shift import MarcEngineShiftSubplugin
from simpad_qt.builtin_plugins.haptic_feedback.subplugins.curbs import CurbsHapticSubplugin
from simpad_qt.builtin_plugins.haptic_feedback.subplugins.slip import SlipHapticSubplugin
from simpad_qt.builtin_plugins.haptic_feedback.subplugins.grip import TireGripHapticSubplugin
from simpad_qt.builtin_plugins.haptic_feedback.manager import HapticSubpluginManager
from simpad_qt.builtin_plugins.haptic_feedback.math_engine import WaveformShape


def test_haptic_motor_output_xinput_mapping():
    # Left Low Rumble -> XInput Low
    # Right High Buzz -> XInput High
    out = HapticMotorOutput(left_low=0.7, left_high=0.0, right_low=0.2, right_high=0.85)
    low, high = out.to_xinput()
    assert low == 0.7
    assert high == 0.85


def test_haptic_motor_output_combine():
    out1 = HapticMotorOutput(left_low=0.4, right_high=0.2)
    out2 = HapticMotorOutput(left_low=0.6, right_high=0.8)

    comb_max = out1.combine_max(out2)
    assert comb_max.left_low == 0.6
    assert comb_max.right_high == 0.8

    comb_sum = out1.combine_sum(out2)
    assert comb_sum.left_low == 1.0
    assert comb_sum.right_high == 1.0


def test_marc_abs_subplugin():
    sub = MarcAbsSubplugin()
    # Test parameters defaults matching Marc Profile
    assert sub.get_param("gain") == 1.80
    assert sub.get_param("gamma") == 0.70
    assert sub.get_param("frequency") == 144.0

    # Test with vehicle with ECU ABS active
    sensors = VehicleSensors(
        vehicle_speed=20.0,
        in_realtime=True,
        ecu_abs_active_raw=True,
    )

    # Time at sine peak for 144 Hz (period / 2 = 1 / (144 * 2))
    t_peak = 1.0 / (144.0 * 2.0)
    res = sub.evaluate(sensors, time_s=t_peak)

    # Should vibrate on left_low (low freq rumble on XInput)
    assert res.left_low > 0.5
    assert res.right_high == 0.0

    # Test slot hosting (enabled/disabled and gain)
    slot = HapticHostSlot(subplugin=sub, enabled=True, master_gain=1.0)
    slot_res = slot.evaluate(sensors, time_s=t_peak)
    assert slot_res.left_low > 0.5

    slot.enabled = False
    assert slot.evaluate(sensors, time_s=t_peak).is_silent()


def test_marc_tc_subplugin():
    sub = MarcTcSubplugin()
    assert sub.get_param("gain") == 1.81
    assert sub.get_param("gamma") == 0.70
    assert sub.get_param("frequency") == 144.0

    # Test with vehicle with ECU TC active
    sensors = VehicleSensors(
        vehicle_speed=20.0,
        in_realtime=True,
        gear=2,
        ecu_tc_active_raw=True,
    )

    t_peak = 1.0 / (144.0 * 2.0)
    res = sub.evaluate(sensors, time_s=t_peak)

    # Should vibrate on right_high (high freq buzz on XInput)
    assert res.right_high > 0.5
    assert res.left_low == 0.0


def test_marc_engine_shift_subplugin():
    sub = MarcEngineShiftSubplugin()

    # 1. Test Over-Rev at Redline (gear 3, 98% RPM)
    sensors_over = VehicleSensors(
        vehicle_speed=40.0,
        in_realtime=True,
        gear=3,
        engine_rpm=7400.0,
        engine_max_rpm=7500.0,
    )
    res_over = sub.evaluate(sensors_over, time_s=0.025)
    # Over-rev routes to right_high (buzz)
    assert res_over.right_high > 0.2
    assert res_over.left_low == 0.0

    # 2. Test Under-Rev at low RPM (gear 3, 30% RPM)
    sensors_under = VehicleSensors(
        vehicle_speed=15.0,
        in_realtime=True,
        gear=3,
        engine_rpm=2200.0,
        engine_max_rpm=7500.0,
    )
    t_peak = 1.0 / (20.0 * 2.0)
    res_under = sub.evaluate(sensors_under, time_s=t_peak)
    # Under-rev routes to left_low (rumble)
    assert res_under.left_low > 0.2
    assert res_under.right_high == 0.0

    # 3. Test in Neutral (gear 0) -> should be silent
    sensors_neutral = VehicleSensors(
        vehicle_speed=0.0,
        in_realtime=True,
        gear=0,
        engine_rpm=7400.0,
        engine_max_rpm=7500.0,
    )
    res_neut = sub.evaluate(sensors_neutral, time_s=0.025)
    assert res_neut.is_silent()


def test_curbs_and_slip_subplugins():
    curbs = CurbsHapticSubplugin()
    sensors_curb = VehicleSensors(
        vehicle_speed=30.0,
        in_realtime=True,
        front_left_travel=0.25,
        rear_left_travel=0.20,
    )
    res_curb = curbs.evaluate(sensors_curb, time_s=0.01)
    assert res_curb.left_low > 0.1

    slip = SlipHapticSubplugin()
    sensors_slip = VehicleSensors(
        vehicle_speed=30.0,
        in_realtime=True,
        rear_left_lat_slip=0.35,
        rear_right_lat_slip=0.30,
    )
    res_slip = slip.evaluate(sensors_slip, time_s=0.01)
    # Oversteer routes to right_high
    assert res_slip.right_high > 0.1


def test_haptic_subplugin_manager():
    manager = HapticSubpluginManager()
    subplugins = manager.get_all_subplugins()
    assert len(subplugins) >= 6

    # Verify default states: Marc profile subplugins enabled, others disabled
    assert manager.is_subplugin_enabled("marc_abs") is True
    assert manager.is_subplugin_enabled("marc_tc") is True
    assert manager.is_subplugin_enabled("marc_engine_shift") is True
    assert manager.is_subplugin_enabled("curbs") is False

    # Toggle subplugin
    manager.set_subplugin_enabled("curbs", True)
    assert manager.is_subplugin_enabled("curbs") is True

    # Test simultaneous ABS + TC evaluation (Marc Profile)
    sensors = VehicleSensors(
        vehicle_speed=25.0,
        in_realtime=True,
        gear=2,
        ecu_abs_active_raw=True,
        ecu_tc_active_raw=True,
    )
    t_peak = 1.0 / (144.0 * 2.0)
    out = manager.evaluate(sensors, time_s=t_peak)

    # Both low (ABS) and high (TC) should be active
    low, high = out.to_xinput()
    assert low > 0.5
    assert high > 0.5

    # Test serialization & deserialization
    cfg = manager.get_config_dict()
    assert "marc_abs" in cfg["subplugins"]
    assert cfg["subplugins"]["curbs"]["enabled"] is True

    # Modify and reload
    cfg["subplugins"]["marc_abs"]["enabled"] = False
    manager.load_config_dict(cfg)
    assert manager.is_subplugin_enabled("marc_abs") is False
