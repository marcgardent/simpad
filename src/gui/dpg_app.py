"""
SimPad Haptic Middleware — Dear PyGui Application (GPU-Accelerated 60FPS UI).
"""

import sys
import time
import math
import threading
from collections import deque
from pathlib import Path
from typing import Dict, Any, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import dearpygui.dearpygui as dpg

from src.profiles.manager import ProfileManager, Profile, PRESET_NAMES
from src.telemetry.plugin_installer import LMUPluginManager
from src.haptics.pulse_engine import HapticPulseSynthesizer, WaveformShape
from src.telemetry.lmu_parser import TelemetryData
from src.telemetry.udp_server import UDPServer
from src.physics.effects import PhysicsToHaptic
from src.haptics.windows import WindowsHapticController

HISTORY = 150  # 7.5 seconds at 20 Hz

EFFECTS = [
    {
        "id": "lock",
        "label": "ABS / Braking",
        "desc": "Wheel lock — longitudinal slip on front wheels",
        "color": [0, 210, 255, 255],
        "defaults": {"threshold": 0.15, "low_gain": 0.3, "low_gamma": 1.0, "high_gain": 1.0, "high_gamma": 1.5},
    },
    {
        "id": "oversteer",
        "label": "Oversteer",
        "desc": "Rear axle lateral slip",
        "color": [231, 76, 60, 255],
        "defaults": {"threshold": 0.12, "low_gain": 1.0, "low_gamma": 1.2, "high_gain": 0.4, "high_gamma": 1.0},
    },
    {
        "id": "understeer",
        "label": "Understeer",
        "desc": "Front axle lateral slip",
        "color": [165, 105, 189, 255],
        "defaults": {"threshold": 0.10, "low_gain": 0.5, "low_gamma": 1.5, "high_gain": 0.8, "high_gamma": 1.0},
    },
    {
        "id": "spin",
        "label": "Traction / Spin",
        "desc": "Rear wheel spin on acceleration (TC)",
        "color": [255, 153, 0, 255],
        "defaults": {"threshold": 0.18, "low_gain": 1.0, "low_gamma": 1.0, "high_gain": 0.2, "high_gamma": 2.0},
    },
]


def _apply_curve(x: float, gamma: float, gain: float, threshold: float) -> float:
    if x < threshold:
        return 0.0
    norm = (x - threshold) / max(0.001, 1.0 - threshold)
    return min(1.0, max(0.0, math.pow(max(0.0, min(1.0, norm)), gamma) * gain))


class EffectState:
    def __init__(self, eid: str, defaults: dict):
        self.eid = eid
        self.enabled = True
        self.threshold = defaults["threshold"]
        self.low_gain = defaults["low_gain"]
        self.low_gamma = defaults["low_gamma"]
        self.high_gain = defaults["high_gain"]
        self.high_gamma = defaults["high_gamma"]

    def low_curve(self, xs: List[float]) -> List[float]:
        return [_apply_curve(x, self.low_gamma, self.low_gain, self.threshold) for x in xs]

    def high_curve(self, xs: List[float]) -> List[float]:
        return [_apply_curve(x, self.high_gamma, self.high_gain, self.threshold) for x in xs]

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "threshold": self.threshold,
            "low_gain": self.low_gain,
            "low_gamma": self.low_gamma,
            "high_gain": self.high_gain,
            "high_gamma": self.high_gamma,
        }

    def load_dict(self, d: dict):
        self.enabled = d.get("enabled", True)
        self.threshold = d.get("threshold", self.threshold)
        self.low_gain = d.get("low_gain", self.low_gain)
        self.low_gamma = d.get("low_gamma", self.low_gamma)
        self.high_gain = d.get("high_gain", self.high_gain)
        self.high_gamma = d.get("high_gamma", self.high_gamma)

    def to_physics_config(self) -> dict:
        p = self.eid
        return {
            f"{p}_threshold": self.threshold,
            f"{p}_low_gain": self.low_gain if self.enabled else 0.0,
            f"{p}_low_gamma": self.low_gamma,
            f"{p}_high_gain": self.high_gain if self.enabled else 0.0,
            f"{p}_high_gamma": self.high_gamma,
        }


class SimPadDPGApp:
    def __init__(self):
        self._pm = ProfileManager()
        self._current_profile_name = "Default"
        self._unsaved = False
        self._telemetry_enabled = True
        self._haptic_mode_1000hz = True
        self._manual_test_active = False
        self._manual_test_eid = None
        self._manual_test_until = 0.0

        self._states = {e["id"]: EffectState(e["id"], e["defaults"]) for e in EFFECTS}

        # Backends
        self._haptics: Optional[WindowsHapticController] = None
        self._udp: Optional[UDPServer] = None
        self._physics: Optional[PhysicsToHaptic] = None

        # Data history
        self._xs_200 = [x / 200.0 for x in range(201)]
        self._t = deque([-(HISTORY - i) * 0.05 for i in range(HISTORY)], maxlen=HISTORY)
        self._d_abs  = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._d_tc   = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._d_over = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._d_und  = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._d_low  = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._d_high = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._start_time = time.time()

        # DPG Tags dictionary
        self.tags = {}

    def run(self):
        dpg.create_context()
        dpg.create_viewport(title="SimPad Haptic Middleware (60 FPS)", width=1200, height=760)
        dpg.setup_dearpygui()

        self._apply_theme()
        self._build_gui()

        dpg.show_viewport()

        # Initialize backends in background
        threading.Thread(target=self._init_backends, daemon=True).start()

        # Render loop
        while dpg.is_dearpygui_running():
            self._render_tick()
            dpg.render_dearpygui_frame()

        self._on_close()
        dpg.destroy_context()

    # ── Background Backends Init ──────────────────────────────────────────────
    def _init_backends(self):
        try:
            self._haptics = WindowsHapticController()
            self._synth = HapticPulseSynthesizer(self._haptics)
            self._synth.start()
        except Exception as e:
            print(f"[HAPTICS] Init error: {e}", flush=True)

        try:
            self._udp = UDPServer(host="0.0.0.0", port=5000)
            self._udp.start()

        except Exception as e:
            print(f"[UDP] Init error: {e}", flush=True)

        try:
            self._physics = PhysicsToHaptic()
            for e in EFFECTS:
                self._physics.update_config(self._states[e["id"]].to_physics_config())
        except Exception as e:
            print(f"[PHYSICS] Init error: {e}", flush=True)

    # ── Styling ───────────────────────────────────────────────────────────────
    def _apply_theme(self):
        with dpg.theme() as global_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, [18, 18, 22, 255])
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, [24, 24, 28, 255])
                dpg.add_theme_color(dpg.mvThemeCol_Header, [35, 35, 45, 255])
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, [45, 45, 60, 255])
                dpg.add_theme_color(dpg.mvThemeCol_Button, [31, 83, 141, 255])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, [41, 104, 178, 255])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, [51, 125, 215, 255])
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg, [28, 28, 35, 255])
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, [38, 38, 48, 255])
                dpg.add_theme_color(dpg.mvThemeCol_Tab, [25, 25, 32, 255])
                dpg.add_theme_color(dpg.mvThemeCol_TabHovered, [40, 40, 55, 255])
                dpg.add_theme_color(dpg.mvThemeCol_TabActive, [31, 83, 141, 255])
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 5)
                dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 8)
                dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 6)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 8, 6)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 8, 5)

        dpg.bind_theme(global_theme)
        self._load_fonts()

    def _load_fonts(self):
        local_font = _PROJECT_ROOT / "assets" / "fonts" / "segoeui.ttf"
        font_candidates = [
            local_font,
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
        with dpg.font_registry():
            for fpath in font_candidates:
                p = Path(fpath)
                if p.exists():
                    try:
                        font = dpg.add_font(str(p), 18)
                        dpg.bind_font(font)
                        print(f"[Font] Loaded standalone font: {p} (18px)", flush=True)
                        return
                    except Exception as e:
                        print(f"[Font] Error loading {p}: {e}", flush=True)
        dpg.set_global_font_scale(1.25)



    # ── GUI Layout ────────────────────────────────────────────────────────────
    def _build_gui(self):
        with dpg.window(tag="primary_window"):
            # 1. Profile Top Bar
            self._build_profile_bar()

            dpg.add_spacer(height=4)

            # 2. Main Tab Bar
            with dpg.tab_bar(tag="main_tab_bar"):
                # Tab 1: Dashboard
                with dpg.tab(label="Dashboard", tag="tab_dashboard"):
                    self._build_dashboard_tab()

                # Tab 2: Monitor
                with dpg.tab(label="Monitor", tag="tab_monitor"):
                    self._build_monitor_tab()

                # Tabs 3..6: Effect Tuning
                for e in EFFECTS:
                    with dpg.tab(label=e["label"], tag=f"tab_{e['id']}"):
                        self._build_effect_tuning_tab(e)

        dpg.set_primary_window("primary_window", True)

    # ── Profile Bar Layout ───────────────────────────────────────────────────
    def _build_profile_bar(self):
        with dpg.group(horizontal=True):
            dpg.add_text("Profile:", color=[170, 170, 170, 255])
            dpg.add_combo(
                items=self._pm.list_all(),
                default_value=self._current_profile_name,
                tag="combo_profile",
                width=180,
                callback=self._cb_profile_selected,
            )

            dpg.add_text(" ", tag="lbl_unsaved_indicator", color=[243, 156, 18, 255])

            dpg.add_button(label="Save", width=70, callback=self._cb_save_profile)
            dpg.add_button(label="New", width=70, callback=self._cb_new_profile)
            dpg.add_button(label="Rename", width=70, callback=self._cb_rename_profile)
            dpg.add_button(label="Copy", width=70, callback=self._cb_copy_profile)
            dpg.add_button(label="Delete", width=70, callback=self._cb_delete_profile)

    # ── Dashboard Tab Layout ──────────────────────────────────────────────────
    def _build_dashboard_tab(self):
        # Status Bar
        with dpg.child_window(height=46, border=True):
            with dpg.group(horizontal=True):
                dpg.add_text("Plugin:", color=[180, 180, 180, 255])
                dpg.add_text("Checking...", tag="lbl_plugin_status", color=[243, 156, 18, 255])
                dpg.add_button(label="Install Plugin", tag="btn_install_plugin", width=110, callback=self._cb_install_plugin)

                dpg.add_spacer(width=15)
                dpg.add_text("UDP Telemetry (Port 5000):", color=[180, 180, 180, 255])
                dpg.add_text("Waiting...", tag="lbl_udp_status", color=[231, 76, 60, 255])

                dpg.add_spacer(width=15)
                dpg.add_text("Controller:", color=[180, 180, 180, 255])
                dpg.add_text("Initializing...", tag="lbl_pad_status", color=[231, 76, 60, 255])

                dpg.add_spacer(width=15)
                dpg.add_combo(
                    items=["50 Hz Smooth", "1000 Hz Raw Pulse"],
                    default_value="1000 Hz Raw Pulse",
                    tag="combo_haptic_mode",
                    width=130,
                    callback=self._cb_toggle_haptic_mode,
                )

                dpg.add_spacer(width=15)
                dpg.add_button(
                    label="Listening: ON",
                    tag="btn_telemetry_toggle",
                    width=120,
                    callback=self._cb_toggle_telemetry,
                )

        dpg.add_spacer(height=6)

        # 2x2 Effect Card Grid
        with dpg.table(header_row=False, resizable=True, policy=dpg.mvTable_SizingStretchProp):
            dpg.add_table_column()
            dpg.add_table_column()

            positions = [("lock", "oversteer"), ("understeer", "spin")]
            for pair in positions:
                with dpg.table_row():
                    for eid in pair:
                        effect = next(ef for ef in EFFECTS if ef["id"] == eid)
                        with dpg.child_window(height=260, border=True):
                            with dpg.group(horizontal=True):
                                dpg.add_text(effect["label"], color=effect["color"])
                                dpg.add_spacer(width=20)
                                dpg.add_checkbox(
                                    label="Enabled",
                                    default_value=True,
                                    tag=f"dash_enable_{eid}",
                                    callback=lambda s, a, u: self._cb_toggle_effect(u, a),
                                    user_data=eid,
                                )

                            # Mini response curve plot
                            with dpg.plot(no_title=True, height=200, width=-1):
                                dpg.add_plot_axis(dpg.mvXAxis, no_tick_labels=True, tag=f"dash_xaxis_{eid}")
                                dpg.set_axis_limits(f"dash_xaxis_{eid}", 0, 1)

                                with dpg.plot_axis(dpg.mvYAxis, no_tick_labels=True, tag=f"dash_yaxis_{eid}"):
                                    dpg.set_axis_limits(f"dash_yaxis_{eid}", 0, 1.05)
                                    state = self._states[eid]

                                    dpg.add_line_series(
                                        self._xs_200, state.low_curve(self._xs_200),
                                        label="Low", tag=f"dash_series_low_{eid}"
                                    )
                                    dpg.add_line_series(
                                        self._xs_200, state.high_curve(self._xs_200),
                                        label="High", tag=f"dash_series_high_{eid}"
                                    )

                                    # Telemetry live cursor
                                    dpg.add_line_series(
                                        [-1, -1], [0, 1],
                                        tag=f"dash_cursor_{eid}"
                                    )

    # ── Monitor Tab Layout ────────────────────────────────────────────────────
    def _build_monitor_tab(self):
        with dpg.plot(label="LMU Telemetry vs Controller Vibration Signal", height=600, width=-1):
            dpg.add_plot_legend()
            dpg.add_plot_axis(dpg.mvXAxis, label="Time (s)", tag="mon_xaxis")
            with dpg.plot_axis(dpg.mvYAxis, label="Intensity", tag="mon_yaxis"):
                dpg.set_axis_limits("mon_yaxis", -0.05, 1.15)
                dpg.add_line_series([], [], label="ABS / Braking", tag="mon_series_abs")
                dpg.add_line_series([], [], label="Traction / Spin", tag="mon_series_tc")
                dpg.add_line_series([], [], label="Oversteer", tag="mon_series_over")
                dpg.add_line_series([], [], label="Understeer", tag="mon_series_und")
                dpg.add_line_series([], [], label="Out: Low Freq", tag="mon_series_low")
                dpg.add_line_series([], [], label="Out: High Freq", tag="mon_series_high")

    # ── Effect Tuning Tab Layout ──────────────────────────────────────────────
    def _build_effect_tuning_tab(self, effect: dict):
        eid = effect["id"]
        state = self._states[eid]

        with dpg.group(horizontal=True):
            # Left Panel: Sliders & Test Info
            with dpg.child_window(width=340, height=600, border=True):
                dpg.add_text(effect["label"], color=effect["color"])
                dpg.add_text(effect["desc"], color=[130, 130, 130, 255])
                dpg.add_separator()

                dpg.add_checkbox(
                    label="Enable Effect",
                    default_value=state.enabled,
                    tag=f"tune_enable_{eid}",
                    callback=lambda s, a, u: self._cb_toggle_effect(u, a),
                    user_data=eid,
                )
                dpg.add_spacer(height=6)

                dpg.add_text("Trigger Threshold", color=[180, 180, 180, 255])
                dpg.add_slider_float(
                    default_value=state.threshold, min_value=0.01, max_value=0.50,
                    format="%.2f", tag=f"tune_thresh_{eid}", width=220,
                    callback=lambda s, a, u: self._cb_param_changed(u, "threshold", a),
                    user_data=eid,
                )

                dpg.add_spacer(height=10)
                dpg.add_text("Low Freq  —  Rumble Motor", color=[255, 51, 102, 255])
                dpg.add_slider_float(
                    label="Gain", default_value=state.low_gain, min_value=0.0, max_value=2.0,
                    format="%.2f", tag=f"tune_low_gain_{eid}", width=220,
                    callback=lambda s, a, u: self._cb_param_changed(u, "low_gain", a),
                    user_data=eid,
                )
                dpg.add_slider_float(
                    label="Gamma", default_value=state.low_gamma, min_value=0.2, max_value=3.0,
                    format="%.2f", tag=f"tune_low_gamma_{eid}", width=220,
                    callback=lambda s, a, u: self._cb_param_changed(u, "low_gamma", a),
                    user_data=eid,
                )

                dpg.add_spacer(height=10)
                dpg.add_text("High Freq  —  Buzz Motor", color=[0, 255, 136, 255])
                dpg.add_slider_float(
                    label="Gain", default_value=state.high_gain, min_value=0.0, max_value=2.0,
                    format="%.2f", tag=f"tune_high_gain_{eid}", width=220,
                    callback=lambda s, a, u: self._cb_param_changed(u, "high_gain", a),
                    user_data=eid,
                )
                dpg.add_slider_float(
                    label="Gamma", default_value=state.high_gamma, min_value=0.2, max_value=3.0,
                    format="%.2f", tag=f"tune_high_gamma_{eid}", width=220,
                    callback=lambda s, a, u: self._cb_param_changed(u, "high_gamma", a),
                    user_data=eid,
                )

                dpg.add_spacer(height=10)
                dpg.add_text("1000 Hz Pulse Waveform Shaping", color=[255, 170, 0, 255])
                dpg.add_combo(
                    label="Shape",
                    items=["Square (Pulsed)", "Sawtooth (Scrub)", "Sine (Smooth)", "Burst (Impact)"],
                    default_value="Square (Pulsed)",
                    tag=f"tune_shape_{eid}",
                    width=170,
                    callback=lambda s, a, u: self._cb_pulse_param_changed(u, "shape", a),
                    user_data=eid,
                )
                dpg.add_slider_float(
                    label="Pulse ON (ms)",
                    default_value=10.0, min_value=1.0, max_value=100.0,
                    format="%.1f ms", tag=f"tune_pulse_on_{eid}", width=170,
                    callback=lambda s, a, u: self._cb_pulse_param_changed(u, "pulse_on_ms", a),
                    user_data=eid,
                )
                dpg.add_slider_float(
                    label="Pulse OFF (ms)",
                    default_value=20.0, min_value=1.0, max_value=100.0,
                    format="%.1f ms", tag=f"tune_pulse_off_{eid}", width=170,
                    callback=lambda s, a, u: self._cb_pulse_param_changed(u, "pulse_off_ms", a),
                    user_data=eid,
                )

                dpg.add_spacer(height=16)
                dpg.add_separator()
                dpg.add_text("Controller / UI Test:", color=[180, 180, 180, 255])
                dpg.add_button(
                    label="FIRE VIBRATION TEST",
                    tag=f"btn_test_fire_{eid}",
                    width=220, height=32,
                    callback=lambda s, a, u: self._cb_manual_fire_test(u),
                    user_data=eid,
                )
                dpg.add_text("Left Stick <-/-> = move cursor | Hold (A) / Click button = Test", color=[120, 120, 120, 255])
                dpg.add_text("Input: 0.00", tag=f"tune_readout_{eid}", color=[0, 210, 255, 255])

            # Right Panel: Full Detailed Curve Plot
            with dpg.child_window(height=600, border=True):
                with dpg.plot(label=f"Response Curve — {effect['label']}", height=560, width=-1):
                    dpg.add_plot_legend()
                    dpg.add_plot_axis(dpg.mvXAxis, label="Raw Slip Input", tag=f"tune_xaxis_{eid}")
                    dpg.set_axis_limits(f"tune_xaxis_{eid}", 0, 1)

                    with dpg.plot_axis(dpg.mvYAxis, label="Motor Output", tag=f"tune_yaxis_{eid}"):
                        dpg.set_axis_limits(f"tune_yaxis_{eid}", 0, 1.05)

                        dpg.add_line_series(
                            self._xs_200, state.low_curve(self._xs_200),
                            label="Low Freq (Rumble)", tag=f"tune_series_low_{eid}"
                        )
                        dpg.add_line_series(
                            self._xs_200, state.high_curve(self._xs_200),
                            label="High Freq (Buzz)", tag=f"tune_series_high_{eid}"
                        )

                        # Threshold line
                        dpg.add_line_series(
                            [state.threshold, state.threshold], [0, 1],
                            label="Threshold", tag=f"tune_series_thresh_{eid}"
                        )

                        # Live stick/telemetry cursor line
                        dpg.add_line_series(
                            [-1, -1], [0, 1],
                            label="Cursor", tag=f"tune_cursor_{eid}"
                        )

    # ── Callbacks ─────────────────────────────────────────────────────────────
    def _cb_profile_selected(self, sender, app_data):
        name = app_data
        self._load_profile_into_ui(name)
        self._current_profile_name = name
        self._clear_unsaved()

    def _load_profile_into_ui(self, name: str):
        profile = self._pm.get(name)
        if profile is None:
            return
        for e in EFFECTS:
            eid = e["id"]
            if eid in profile.effects:
                state = self._states[eid]
                state.load_dict(profile.effects[eid])

                # Update DPG controls
                dpg.set_value(f"tune_enable_{eid}", state.enabled)
                dpg.set_value(f"dash_enable_{eid}", state.enabled)
                dpg.set_value(f"tune_thresh_{eid}", state.threshold)
                dpg.set_value(f"tune_low_gain_{eid}", state.low_gain)
                dpg.set_value(f"tune_low_gamma_{eid}", state.low_gamma)
                dpg.set_value(f"tune_high_gain_{eid}", state.high_gain)
                dpg.set_value(f"tune_high_gamma_{eid}", state.high_gamma)

                if self._physics:
                    self._physics.update_config(state.to_physics_config())
                self._update_plot_curves(eid)

    def _cb_manual_fire_test(self, eid: str):
        current_eid = getattr(self, "_manual_test_eid", None)
        is_active = getattr(self, "_manual_test_active", False)

        if is_active and current_eid == eid:
            self._manual_test_active = False
            self._manual_test_eid = None
            dpg.configure_item(f"btn_test_fire_{eid}", label="FIRE VIBRATION TEST")
            print(f"[TEST UI] Manual Fire STOPPED for '{eid}'", flush=True)
        else:
            # Turn off previous active button label if any
            if current_eid:
                try:
                    dpg.configure_item(f"btn_test_fire_{current_eid}", label="FIRE VIBRATION TEST")
                except Exception:
                    pass

            self._manual_test_active = True
            self._manual_test_eid = eid
            dpg.configure_item(f"btn_test_fire_{eid}", label="⏹ STOP VIBRATION TEST")
            print(f"[TEST UI] Manual Fire STARTED for '{eid}'", flush=True)

    def _cb_toggle_effect(self, eid: str, enabled: bool):
        state = self._states[eid]
        state.enabled = enabled
        dpg.set_value(f"tune_enable_{eid}", enabled)
        dpg.set_value(f"dash_enable_{eid}", enabled)
        if self._physics:
            self._physics.update_config(state.to_physics_config())
        self._mark_unsaved()

    def _cb_pulse_param_changed(self, effect_id: str, param: str, val):
        if hasattr(self, "_synth") and self._synth:
            if param == "shape":
                shape_map = {
                    "Square (Pulsed)": WaveformShape.SQUARE,
                    "Sawtooth (Scrub)": WaveformShape.SAWTOOTH,
                    "Sine (Smooth)": WaveformShape.SINE,
                    "Burst (Impact)": WaveformShape.BURST,
                }
                val = shape_map.get(val, WaveformShape.SQUARE)
            self._synth.update_effect_params(effect_id, **{param: val})
            self._mark_unsaved()

    def _cb_param_changed(self, eid: str, param: str, value: float):
        state = self._states[eid]
        setattr(state, param, value)
        if self._physics:
            self._physics.update_config(state.to_physics_config())
        if hasattr(self, "_synth") and self._synth:
            self._synth.update_effect_params(
                eid,
                gain=max(state.low_gain, state.high_gain),
                gamma=state.high_gamma,
                cutoff=state.threshold,
            )
        self._update_plot_curves(eid)
        self._mark_unsaved()

    def _update_plot_curves(self, eid: str):
        state = self._states[eid]
        lows = state.low_curve(self._xs_200)
        highs = state.high_curve(self._xs_200)

        # Update detailed plot
        dpg.set_value(f"tune_series_low_{eid}", [self._xs_200, lows])
        dpg.set_value(f"tune_series_high_{eid}", [self._xs_200, highs])
        dpg.set_value(f"tune_series_thresh_{eid}", [[state.threshold, state.threshold], [0, 1]])

        # Update dashboard mini plot
        dpg.set_value(f"dash_series_low_{eid}", [self._xs_200, lows])
        dpg.set_value(f"dash_series_high_{eid}", [self._xs_200, highs])

    def _cb_install_plugin(self):
        success, msg = LMUPluginManager.install_plugin(_PROJECT_ROOT)
        with dpg.window(label="Plugin Installation Result", modal=True, show=True, width=420, height=150, tag="modal_install_res"):
            dpg.add_text(msg, color=[46, 204, 113, 255] if success else [231, 76, 60, 255])
            dpg.add_spacer(height=14)
            dpg.add_button(label="OK", width=100, callback=lambda: dpg.delete_item("modal_install_res"))

    def _cb_toggle_haptic_mode(self, sender, app_data):
        self._haptic_mode_1000hz = (app_data == "1000 Hz Raw Pulse")
        print(f"[Haptics] Switched Haptic Mode -> {'1000 Hz Raw Pulse' if self._haptic_mode_1000hz else '50 Hz Smooth DirectDrive'}", flush=True)

    def _cb_toggle_telemetry(self):
        self._telemetry_enabled = not self._telemetry_enabled
        if self._telemetry_enabled:
            dpg.configure_item("btn_telemetry_toggle", label="Listening: ON")
        else:
            dpg.configure_item("btn_telemetry_toggle", label="Listening: OFF")
            if self._haptics:
                self._haptics.set_vibration(0, 0, 0, 0)

    # ── Profile Dialog Modals (DPG Hardware-Accelerated) ─────────────────────
    def _cb_save_profile(self):
        name = self._current_profile_name
        if name in PRESET_NAMES:
            self._show_modal_input("Save as Custom Profile", f"'{name}' is a preset. Enter name:", f"{name} Custom", self._do_save_as)
            return
        effects = {e["id"]: self._states[e["id"]].to_dict() for e in EFFECTS}
        profile = Profile(name=name, effects=effects)
        if self._pm.save(profile):
            self._refresh_profile_combo(name)
            self._clear_unsaved()

    def _do_save_as(self, new_name: str):
        effects = {e["id"]: self._states[e["id"]].to_dict() for e in EFFECTS}
        p = Profile(name=new_name, effects=effects)
        if self._pm.save(p):
            self._current_profile_name = new_name
            self._refresh_profile_combo(new_name)
            self._clear_unsaved()

    def _cb_new_profile(self):
        self._show_modal_input("Create New Profile", "Enter profile name:", "My Custom Profile", self._do_create_profile)

    def _do_create_profile(self, name: str):
        if self._pm.exists(name):
            return
        effects = {e["id"]: self._states[e["id"]].to_dict() for e in EFFECTS}
        profile = Profile(name=name, effects=effects)
        self._pm.save(profile)
        self._current_profile_name = name
        self._refresh_profile_combo(name)
        self._clear_unsaved()

    def _cb_copy_profile(self):
        src = self._current_profile_name
        self._show_modal_input("Duplicate Profile", f"Copy of '{src}'. Enter name:", f"{src} Copy", lambda n: self._do_copy_profile(src, n))

    def _do_copy_profile(self, src: str, name: str):
        p = self._pm.duplicate(src, name)
        if p:
            self._current_profile_name = name
            self._refresh_profile_combo(name)
            self._clear_unsaved()

    def _cb_rename_profile(self):
        src = self._current_profile_name
        if src in PRESET_NAMES:
            return
        self._show_modal_input("Rename Profile", f"Renaming '{src}'. Enter new name:", src, lambda n: self._do_rename_profile(src, n))

    def _do_rename_profile(self, src: str, new_name: str):
        if self._pm.rename(src, new_name):
            self._current_profile_name = new_name
            self._refresh_profile_combo(new_name)

    def _cb_delete_profile(self):
        name = self._current_profile_name
        if name in PRESET_NAMES:
            return
        self._pm.delete(name)
        self._current_profile_name = "Default"
        self._refresh_profile_combo("Default")
        self._load_profile_into_ui("Default")
        self._clear_unsaved()

    def _refresh_profile_combo(self, select: str):
        all_profiles = self._pm.list_all()
        dpg.configure_item("combo_profile", items=all_profiles, default_value=select)

    def _show_modal_input(self, title: str, label: str, default_val: str, on_confirm):
        with dpg.window(label=title, modal=True, show=True, width=380, height=160, tag="modal_input_win"):
            dpg.add_text(label)
            dpg.add_input_text(default_value=default_val, tag="modal_input_field", width=340)
            dpg.add_spacer(height=10)

            with dpg.group(horizontal=True):
                def _confirm():
                    val = dpg.get_value("modal_input_field").strip()
                    if val:
                        on_confirm(val)
                    dpg.delete_item("modal_input_win")

                dpg.add_button(label="Confirm", width=120, callback=_confirm)
                dpg.add_button(label="Cancel", width=100, callback=lambda: dpg.delete_item("modal_input_win"))

    def _mark_unsaved(self):
        self._unsaved = True
        dpg.set_value("lbl_unsaved_indicator", "[Modified]")

    def _clear_unsaved(self):
        self._unsaved = False
        dpg.set_value("lbl_unsaved_indicator", " ")

    # ── 60 FPS Render Tick Loop ───────────────────────────────────────────────
    def _render_tick(self):
        # 1. Update Status Badges
        installed, p_msg, _ = LMUPluginManager.check_plugin_installed(_PROJECT_ROOT)
        if installed:
            dpg.configure_item("lbl_plugin_status", default_value="[OK] Active", color=[46, 204, 113, 255])
        else:
            dpg.configure_item("lbl_plugin_status", default_value="⚠️ Missing", color=[243, 156, 18, 255])
        if self._udp:
            active, _, count = self._udp.is_receiving_packets()
            if not self._telemetry_enabled:
                dpg.configure_item("lbl_udp_status", default_value="Paused (OFF)", color=[243, 156, 18, 255])
            elif active:
                dpg.configure_item("lbl_udp_status", default_value=f"Live ({count} frames)", color=[46, 204, 113, 255])
            else:
                dpg.configure_item("lbl_udp_status", default_value="Waiting...", color=[231, 76, 60, 255])

        if self._haptics:
            is_conn = self._haptics.is_connected()
            if is_conn:
                pad_name = self._haptics.get_gamepad_name()
                dpg.configure_item("lbl_pad_status", default_value=f"[OK] {pad_name}", color=[46, 204, 113, 255])
            else:
                dpg.configure_item("lbl_pad_status", default_value="Disconnected", color=[231, 76, 60, 255])

        # 2. Check Controller Input & Test Mode (Stick & Button A)
        has_pad = self._haptics and self._haptics.is_connected()
        raw_stick = 0.0
        btn_held = False

        if has_pad:
            try:
                raw_stick = self._haptics.get_left_stick_x()
            except Exception:
                raw_stick = 0.0
            try:
                btn_held = self._haptics.get_south_button()
            except Exception:
                btn_held = False

        if abs(raw_stick) < 0.10:
            raw_stick = 0.0
        input_val = (raw_stick + 1.0) / 2.0

        # Update cursor line & readout for each effect tab
        active_effect_id = None
        test_low, test_high = 0.0, 0.0

        active_tab_val = dpg.get_value("main_tab_bar")

        for e in EFFECTS:
            eid = e["id"]
            state = self._states[eid]
            o_low = _apply_curve(input_val, state.low_gamma, state.low_gain, state.threshold)
            o_high = _apply_curve(input_val, state.high_gamma, state.high_gain, state.threshold)

            # Move cursor line on detailed tuning plot
            dpg.set_value(f"tune_cursor_{eid}", [[input_val, input_val], [0, 1]])

            if active_tab_val == f"tab_{eid}":
                active_effect_id = eid
                test_low, test_high = o_low, o_high
                if not has_pad:
                    status_text = " (No Controller)"
                elif btn_held:
                    status_text = "  ● FIRE"
                else:
                    status_text = ""

                dpg.set_value(
                    f"tune_readout_{eid}",
                    f"Input: {input_val:.2f} | Low: {o_low:.2f} | High: {o_high:.2f}{status_text}"
                )

        # 3. Unified Single-Thread Haptic Routing (Synthesizer is EXCLUSIVE controller writer)
        game_active = (self._udp and self._telemetry_enabled and self._udp.is_receiving_packets()[0])

        is_manual_fire = getattr(self, "_manual_test_active", False)
        manual_eid = getattr(self, "_manual_test_eid", None)

        effective_test_eid = manual_eid if is_manual_fire else active_effect_id
        is_testing = (btn_held and has_pad) or is_manual_fire

        if is_testing and effective_test_eid:
            test_val = max(0.75, input_val) if is_manual_fire else (input_val if input_val > 0.05 else 0.75)

            lock_test  = test_val if effective_test_eid == "lock" else 0.0
            spin_test  = test_val if effective_test_eid == "spin" else 0.0
            over_test  = test_val if effective_test_eid == "oversteer" else 0.0
            und_test   = test_val if effective_test_eid == "understeer" else 0.0

            if hasattr(self, "_synth") and self._synth:
                self._synth.update_telemetry(lock_test, spin_test, over_test, und_test)

        elif game_active and self._physics:
            # LIVE TELEMETRY MODE
            data = self._udp.get_latest_data()
            if data:
                sensors = data.to_sensors()
                abs_val = sensors.lock_intensity
                tc_val  = sensors.spin_intensity
                over_val = sensors.oversteer_intensity
                und_val  = sensors.understeer_intensity

                if hasattr(self, "_synth") and self._synth:
                    self._synth.update_telemetry(abs_val, tc_val, over_val, und_val)

                l_low, l_high, r_low, r_high = self._physics.process(data)
                al, ar, bgl, bgr = data.longitudinal_patch_vel
                cll, clr, crl, crr = data.lateral_patch_vel
                now = time.time() - self._start_time

                self._t.append(now)
                self._d_abs.append(min(1.0, max(abs(al), abs(ar))))
                self._d_tc.append(min(1.0, max(abs(bgl), abs(bgr))))
                self._d_over.append(min(1.0, max(abs(crl), abs(crr))))
                self._d_und.append(min(1.0, max(abs(cll), abs(clr))))
                self._d_low.append(max(l_low, r_low))
                self._d_high.append(max(l_high, r_high))

                t_list = list(self._t)
                dpg.set_value("mon_series_abs", [t_list, list(self._d_abs)])
                dpg.set_value("mon_series_tc", [t_list, list(self._d_tc)])
                dpg.set_value("mon_series_over", [t_list, list(self._d_over)])
                dpg.set_value("mon_series_und", [t_list, list(self._d_und)])
                dpg.set_value("mon_series_low", [t_list, list(self._d_low)])
                dpg.set_value("mon_series_high", [t_list, list(self._d_high)])
                if t_list:
                    dpg.set_axis_limits("mon_xaxis", t_list[0], t_list[-1])

                slip_map = {
                    "lock": min(1.0, max(abs(al), abs(ar))),
                    "spin": min(1.0, max(abs(bgl), abs(bgr))),
                    "oversteer": min(1.0, max(abs(crl), abs(crr))),
                    "understeer": min(1.0, max(abs(cll), abs(clr))),
                }
                for eid, slip in slip_map.items():
                    dpg.set_value(f"dash_cursor_{eid}", [[slip, slip], [0, 1]])

        else:
            # IDLE: Silence synthesizer
            if hasattr(self, "_synth") and self._synth:
                self._synth.update_telemetry(0.0, 0.0, 0.0, 0.0)


    # ── Shutdown ───────────────────────────────────────────────────────────────
    def _on_close(self):
        if self._haptics:
            self._haptics.close()
        if self._udp:
            self._udp.stop()


if __name__ == "__main__":
    app = SimPadDPGApp()
    app.run()
