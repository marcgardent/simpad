"""
SimPad Haptic Middleware — Node Sidebar Control.
Manages the real-time telemetry testing sidebar, interactive manual sliders, action pulses, and output readout bars.
"""

import dearpygui.dearpygui as dpg
from typing import Tuple, Callable, Any, Optional


class NodeSidebarControl:
    """Encapsulates real-time telemetry sidebar controls and live output readout evaluation."""

    def build_sidebar(self, parent_editor: Any):
        """Constructs the interactive right sidebar for real-time telemetry testing."""
        with dpg.child_window(width=320, height=-1, border=True):
            dpg.add_text("Real-Time Synthesizer Control", color=[0, 210, 255, 255])
            dpg.add_text("Manual telemetry input to test haptic synthesis loop.", color=[140, 140, 140, 255])
            dpg.add_separator()
            dpg.add_spacer(height=4)

            dpg.add_text("Sensors Live Control (Left / Right)", color=[243, 156, 18, 255])

            dpg.add_text("Over-Braking", color=[255, 220, 0, 255])
            with dpg.group(horizontal=True):
                dpg.add_slider_float(label="L", tag="test_sensor_abs_l", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=lambda *args: self.on_test_sensor_change(parent_editor._synth_engine))
                dpg.add_slider_float(label="R", tag="test_sensor_abs_r", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=lambda *args: self.on_test_sensor_change(parent_editor._synth_engine))

            dpg.add_spacer(height=2)
            dpg.add_text("Over-Acceleration", color=[255, 220, 0, 255])
            with dpg.group(horizontal=True):
                dpg.add_slider_float(label="L", tag="test_sensor_tc_l", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=lambda *args: self.on_test_sensor_change(parent_editor._synth_engine))
                dpg.add_slider_float(label="R", tag="test_sensor_tc_r", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=lambda *args: self.on_test_sensor_change(parent_editor._synth_engine))

            dpg.add_spacer(height=2)
            dpg.add_text("Oversteer", color=[255, 220, 0, 255])
            with dpg.group(horizontal=True):
                dpg.add_slider_float(label="L", tag="test_sensor_over_l", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=lambda *args: self.on_test_sensor_change(parent_editor._synth_engine))
                dpg.add_slider_float(label="R", tag="test_sensor_over_r", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=lambda *args: self.on_test_sensor_change(parent_editor._synth_engine))

            dpg.add_spacer(height=2)
            dpg.add_text("Understeer", color=[255, 220, 0, 255])
            with dpg.group(horizontal=True):
                dpg.add_slider_float(label="L", tag="test_sensor_und_l", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=lambda *args: self.on_test_sensor_change(parent_editor._synth_engine))
                dpg.add_slider_float(label="R", tag="test_sensor_und_r", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=lambda *args: self.on_test_sensor_change(parent_editor._synth_engine))

            dpg.add_spacer(height=2)
            dpg.add_text("Engine RPM & Regime", color=[255, 100, 100, 255])
            with dpg.group(horizontal=True):
                dpg.add_slider_float(label="Sur", tag="test_sensor_over_rev", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=lambda *args: self.on_test_sensor_change(parent_editor._synth_engine))
                dpg.add_slider_float(label="Sous", tag="test_sensor_under_rev", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=lambda *args: self.on_test_sensor_change(parent_editor._synth_engine))
            with dpg.group(horizontal=True):
                dpg.add_slider_float(label="RPM", tag="test_sensor_rpm", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=lambda *args: self.on_test_sensor_change(parent_editor._synth_engine))
                dpg.add_slider_float(label="Gear", tag="test_sensor_gear", default_value=1.0, min_value=0.0, max_value=8.0, format="%.0f", width=120, callback=lambda *args: self.on_test_sensor_change(parent_editor._synth_engine))

            dpg.add_spacer(height=2)
            dpg.add_text("Wheel Travel / Curbs", color=[100, 255, 150, 255])
            with dpg.group(horizontal=True):
                dpg.add_slider_float(label="L", tag="test_sensor_travel_l", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=lambda *args: self.on_test_sensor_change(parent_editor._synth_engine))
                dpg.add_slider_float(label="R", tag="test_sensor_travel_r", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=lambda *args: self.on_test_sensor_change(parent_editor._synth_engine))

            dpg.add_spacer(height=2)
            dpg.add_text("Grip Fraction", color=[0, 255, 180, 255])
            with dpg.group(horizontal=True):
                dpg.add_slider_float(label="L", tag="test_sensor_grip_l", default_value=1.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=lambda *args: self.on_test_sensor_change(parent_editor._synth_engine))
                dpg.add_slider_float(label="R", tag="test_sensor_grip_r", default_value=1.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=lambda *args: self.on_test_sensor_change(parent_editor._synth_engine))

            dpg.add_spacer(height=10)
            dpg.add_separator()
            dpg.add_spacer(height=4)
            dpg.add_text("Quick Action Pulse", color=[180, 180, 180, 255])
            with dpg.group(horizontal=True):
                dpg.add_button(label="Braking L", width=65, callback=lambda *args: self.trigger_sensor_pulse(parent_editor._synth_engine, "test_sensor_abs_l"))
                dpg.add_button(label="Braking R", width=65, callback=lambda *args: self.trigger_sensor_pulse(parent_editor._synth_engine, "test_sensor_abs_r"))
                dpg.add_button(label="Accel L", width=65, callback=lambda *args: self.trigger_sensor_pulse(parent_editor._synth_engine, "test_sensor_tc_l"))
                dpg.add_button(label="Accel R", width=65, callback=lambda *args: self.trigger_sensor_pulse(parent_editor._synth_engine, "test_sensor_tc_r"))
            with dpg.group(horizontal=True):
                dpg.add_button(label="Oversteer L", width=65, callback=lambda *args: self.trigger_sensor_pulse(parent_editor._synth_engine, "test_sensor_over_l"))
                dpg.add_button(label="Oversteer R", width=65, callback=lambda *args: self.trigger_sensor_pulse(parent_editor._synth_engine, "test_sensor_over_r"))
                dpg.add_button(label="Under L", width=65, callback=lambda *args: self.trigger_sensor_pulse(parent_editor._synth_engine, "test_sensor_und_l"))
                dpg.add_button(label="Under R", width=65, callback=lambda *args: self.trigger_sensor_pulse(parent_editor._synth_engine, "test_sensor_und_r"))
            with dpg.group(horizontal=True):
                dpg.add_button(label="Sur-régime", width=65, callback=lambda *args: self.trigger_sensor_pulse(parent_editor._synth_engine, "test_sensor_over_rev"))
                dpg.add_button(label="Sous-régime", width=65, callback=lambda *args: self.trigger_sensor_pulse(parent_editor._synth_engine, "test_sensor_under_rev"))
                dpg.add_button(label="Curb Left", width=65, callback=lambda *args: self.trigger_sensor_pulse(parent_editor._synth_engine, "test_sensor_travel_l"))
                dpg.add_button(label="Curb Right", width=65, callback=lambda *args: self.trigger_sensor_pulse(parent_editor._synth_engine, "test_sensor_travel_r"))

            dpg.add_spacer(height=10)
            dpg.add_separator()
            dpg.add_spacer(height=4)
            dpg.add_text("Output Readout (Vibration)", color=[46, 204, 113, 255])
            dpg.add_text("Low Freq Rumble (Left): 0%", tag="lbl_node_out_low", color=[255, 51, 102, 255])
            dpg.add_progress_bar(tag="bar_node_out_low", default_value=0.0, width=280)
            dpg.add_spacer(height=4)
            dpg.add_text("High Freq Buzz (Right): 0%", tag="lbl_node_out_high", color=[0, 255, 136, 255])
            dpg.add_progress_bar(tag="bar_node_out_high", default_value=0.0, width=280)

            dpg.add_spacer(height=12)
            dpg.add_button(label="Reset All Sensors to 0", width=280, callback=lambda *args: self.reset_test_sensors(parent_editor._synth_engine))

    def trigger_sensor_pulse(self, synth_engine: Any, tag_name: str):
        """Triggers a 100% telemetry impulse on a specific sensor channel."""
        if dpg.does_item_exist(tag_name):
            dpg.set_value(tag_name, 1.0)
        self.on_test_sensor_change(synth_engine)

    def reset_test_sensors(self, synth_engine: Any):
        """Resets all live test sensor sliders to zero (or 1.0 for grip)."""
        for tag in [
            "test_sensor_abs_l", "test_sensor_abs_r",
            "test_sensor_tc_l", "test_sensor_tc_r",
            "test_sensor_over_l", "test_sensor_over_r",
            "test_sensor_und_l", "test_sensor_und_r",
            "test_sensor_over_rev", "test_sensor_under_rev",
            "test_sensor_rpm", "test_sensor_gear",
            "test_sensor_travel_l", "test_sensor_travel_r",
            "test_sensor_grip_l", "test_sensor_grip_r"
        ]:
            if dpg.does_item_exist(tag):
                default_val = 1.0 if tag in ["test_sensor_grip_l", "test_sensor_grip_r"] else 0.0
                dpg.set_value(tag, default_val)
        self.on_test_sensor_change(synth_engine)

    def on_test_sensor_change(self, synth_engine: Any):
        """Dispatches live slider values to the high-frequency synthesizer engine."""
        if synth_engine:
            abs_l = dpg.get_value("test_sensor_abs_l") if dpg.does_item_exist("test_sensor_abs_l") else 0.0
            abs_r = dpg.get_value("test_sensor_abs_r") if dpg.does_item_exist("test_sensor_abs_r") else 0.0
            abs_val = max(abs_l, abs_r)

            tc_l = dpg.get_value("test_sensor_tc_l") if dpg.does_item_exist("test_sensor_tc_l") else 0.0
            tc_r = dpg.get_value("test_sensor_tc_r") if dpg.does_item_exist("test_sensor_tc_r") else 0.0
            tc_val = max(tc_l, tc_r)

            over_l = dpg.get_value("test_sensor_over_l") if dpg.does_item_exist("test_sensor_over_l") else 0.0
            over_r = dpg.get_value("test_sensor_over_r") if dpg.does_item_exist("test_sensor_over_r") else 0.0
            over_val = max(over_l, over_r)

            und_l = dpg.get_value("test_sensor_und_l") if dpg.does_item_exist("test_sensor_und_l") else 0.0
            und_r = dpg.get_value("test_sensor_und_r") if dpg.does_item_exist("test_sensor_und_r") else 0.0
            und_val = max(und_l, und_r)

            over_rev = dpg.get_value("test_sensor_over_rev") if dpg.does_item_exist("test_sensor_over_rev") else 0.0
            under_rev = dpg.get_value("test_sensor_under_rev") if dpg.does_item_exist("test_sensor_under_rev") else 0.0
            rpm_slider = dpg.get_value("test_sensor_rpm") if dpg.does_item_exist("test_sensor_rpm") else 0.0
            rpm_val = max(rpm_slider, over_rev, under_rev)
            gear_val = dpg.get_value("test_sensor_gear") if dpg.does_item_exist("test_sensor_gear") else 1.0

            travel_l = dpg.get_value("test_sensor_travel_l") if dpg.does_item_exist("test_sensor_travel_l") else 0.0
            travel_r = dpg.get_value("test_sensor_travel_r") if dpg.does_item_exist("test_sensor_travel_r") else 0.0
            travel_val = max(travel_l, travel_r)

            grip_l = dpg.get_value("test_sensor_grip_l") if dpg.does_item_exist("test_sensor_grip_l") else 1.0
            grip_r = dpg.get_value("test_sensor_grip_r") if dpg.does_item_exist("test_sensor_grip_r") else 1.0
            grip_val = min(grip_l, grip_r)

            synth_engine.update_telemetry(
                abs_val=abs_val, abs_l=abs_l, abs_r=abs_r,
                tc_val=tc_val, tc_l=tc_l, tc_r=tc_r,
                over_val=over_val, over_l=over_l, over_r=over_r,
                und_val=und_val, und_l=und_l, und_r=und_r,
                over_rev=over_rev, under_rev=under_rev, rpm=rpm_val, gear=gear_val,
                travel_val=travel_val, travel_l=travel_l, travel_r=travel_r,
                grip_val=grip_val, grip_l=grip_l, grip_r=grip_r
            )

    def evaluate_graph(self, synth_engine: Any, profile_manager: Any, update_preset_ui_cb: Callable[[], None]) -> Tuple[float, float]:
        """Reads current output values from high-frequency synthesizer engine and polls profile directory changes."""
        if profile_manager and profile_manager.check_for_changes():
            displays = profile_manager.list_display_names()
            active_disp = profile_manager.get_display_name(profile_manager._active_profile_name)
            if dpg.does_item_exist("combo_profile_select"):
                dpg.configure_item("combo_profile_select", items=displays, default_value=active_disp)
            update_preset_ui_cb()

        if synth_engine:
            low_val, high_val = synth_engine.get_current_outputs()
        else:
            low_val, high_val = 0.0, 0.0

        if dpg.does_item_exist("lbl_node_out_low"):
            dpg.set_value("lbl_node_out_low", f"Low Freq Rumble (Left): {int(low_val * 100)}%")
            dpg.set_value("bar_node_out_low", low_val)
            dpg.set_value("lbl_node_out_high", f"High Freq Buzz (Right): {int(high_val * 100)}%")
            dpg.set_value("bar_node_out_high", high_val)

        return low_val, high_val
