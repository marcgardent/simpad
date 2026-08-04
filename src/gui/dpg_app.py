"""
SimPad Haptic Middleware — Dear PyGui Application (GPU-Accelerated 60FPS UI).
Integrates real-time UDP telemetry, high-frequency haptic synthesizer engine, and node editor.
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

from src.core.synthesizer import HapticSynthesizerEngine
from src.telemetry.plugin_installer import LMUPluginManager
from src.telemetry.lmu_parser import TelemetryData
from src.telemetry.udp_server import UDPServer
from src.physics.effects import PhysicsToHaptic
from src.haptics.windows import WindowsHapticController
from src.gui.node_editor import NodeEditorTab

HISTORY = 150  # 7.5 seconds at 20 Hz


class SimPadDPGApp:
    def __init__(self):
        self._lmu_installer = LMUPluginManager()
        self._telemetry_enabled = True

        # Backends
        self._haptics: Optional[WindowsHapticController] = None
        self._synth: Optional[HapticSynthesizerEngine] = None
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

        # Node Editor Sub-Module
        self._node_editor = NodeEditorTab()

    def run(self):
        dpg.create_context()
        dpg.create_viewport(title="SimPad Haptic Middleware (Synthesizer Engine)", width=1240, height=780)
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
            self._synth = HapticSynthesizerEngine(self._haptics, default_freq_hz=200)
            self._synth.start()
            self._node_editor.set_synth_engine(self._synth)
            print("[HAPTICS] High-frequency synthesizer engine initialized at 200 Hz.", flush=True)
        except Exception as e:
            print(f"[HAPTICS] Init error: {e}", flush=True)

        try:
            self._udp = UDPServer(host="0.0.0.0", port=5000)
            self._udp.start()
            print("[UDP] Listening on UDP 0.0.0.0:5000", flush=True)
        except Exception as e:
            print(f"[UDP] Init error: {e}", flush=True)

        try:
            self._physics = PhysicsToHaptic()
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
            # Main Tab Bar
            with dpg.tab_bar(tag="main_tab_bar"):
                # Primary Tab: Node Editor (Core Haptic Engine)
                with dpg.tab(label="Node Editor & Synthesizer", tag="tab_node_editor"):
                    self._node_editor.build_tab(self)

                # Secondary Tab: Dashboard & Status
                with dpg.tab(label="Dashboard", tag="tab_dashboard"):
                    self._build_dashboard_tab()

                # Tertiary Tab: Telemetry Monitor
                with dpg.tab(label="Telemetry Monitor", tag="tab_monitor"):
                    self._build_monitor_tab()

        dpg.set_primary_window("primary_window", True)

    # ── Dashboard Tab Layout ──────────────────────────────────────────────────
    def _build_dashboard_tab(self):
        with dpg.child_window(height=46, border=True):
            with dpg.group(horizontal=True):
                dpg.add_text("Plugin:", color=[180, 180, 180, 255])
                dpg.add_text("Checking...", tag="lbl_plugin_status", color=[243, 156, 18, 255])
                dpg.add_button(label="Install Plugin", tag="btn_install_plugin", width=110, callback=self._cb_install_plugin)

                dpg.add_spacer(width=15)
                dpg.add_text("UDP Telemetry (Port 5000):", color=[180, 180, 180, 255])
                dpg.add_text("Waiting...", tag="lbl_udp_status", color=[231, 76, 60, 255])

                dpg.add_spacer(width=15)
                dpg.add_text("XInput Vibration:", color=[180, 180, 180, 255])
                dpg.add_text("Disconnected", tag="lbl_pad_status", color=[231, 76, 60, 255])

        dpg.add_spacer(height=6)

        with dpg.child_window(height=350, border=True):
            dpg.add_text("SimPad Real-Time Haptic Middleware", color=[0, 210, 255, 255])
            dpg.add_text("Node Editor Graph Expression Engine driving high-frequency tactile synthesis.", color=[180, 180, 180, 255])
            dpg.add_separator()
            dpg.add_spacer(height=8)

            dpg.add_text("Engine Status:", color=[255, 200, 0, 255])
            dpg.add_text("• Real-Time Synthesizer Thread: ACTIVE", color=[46, 204, 113, 255])
            dpg.add_text("• Graph Compiler: Python Bytecode JIT", color=[46, 204, 113, 255])
            dpg.add_text("• Telemetry Pipeline: UDP Port 5000", color=[46, 204, 113, 255])

    # ── Monitor Tab Layout ────────────────────────────────────────────────────
    def _build_monitor_tab(self):
        with dpg.child_window(height=520, border=True):
            dpg.add_text("Live Telemetry Signal Monitor (20 Hz)", color=[0, 210, 255, 255])
            with dpg.plot(no_title=True, height=460, width=-1, tag="mon_plot"):
                dpg.add_plot_legend()
                dpg.add_plot_axis(dpg.mvXAxis, label="Time (s)", tag="mon_xaxis")
                with dpg.plot_axis(dpg.mvYAxis, label="Intensity [0.0 - 1.0]", tag="mon_yaxis"):
                    dpg.set_axis_limits("mon_yaxis", 0, 1.05)
                    dpg.add_line_series([], [], label="ABS (Braking)", tag="mon_series_abs")
                    dpg.add_line_series([], [], label="Traction (Spin)", tag="mon_series_tc")
                    dpg.add_line_series([], [], label="Oversteer", tag="mon_series_over")
                    dpg.add_line_series([], [], label="Understeer", tag="mon_series_und")
                    dpg.add_line_series([], [], label="Motor Low (Left)", tag="mon_series_low")
                    dpg.add_line_series([], [], label="Motor High (Right)", tag="mon_series_high")

    def _cb_install_plugin(self):
        res = self._lmu_installer.install_all()
        if dpg.does_item_exist("lbl_plugin_status"):
            if res.get("installed"):
                dpg.set_value("lbl_plugin_status", "Installed")
                dpg.configure_item("lbl_plugin_status", color=[46, 204, 113, 255])
            else:
                dpg.set_value("lbl_plugin_status", "Installation Failed")
                dpg.configure_item("lbl_plugin_status", color=[231, 76, 60, 255])

    # ── Render Loop Tick ──────────────────────────────────────────────────────
    # TODO: [SLAP] Keep _render_tick at a single high level of abstraction: poll status -> process telemetry frame -> refresh plot series.
    # TODO: [SRP] UI rendering tick should delegate data history queue calculations and plot rendering to helper methods.
    def _render_tick(self):
        if not hasattr(self, "_lmu_installer"):
            return

        self._update_status_indicators()

        if self._udp and self._udp.is_receiving() and self._telemetry_enabled:
            data = self._udp.get_latest_data()
            if data:
                self._process_telemetry_frame(data)
        else:
            if hasattr(self, "_node_editor"):
                self._node_editor.evaluate_graph()

    def _update_status_indicators(self):
        if dpg.does_item_exist("lbl_lmu_status"):
            is_inst = self._lmu_installer.is_installed()
            dpg.set_value("lbl_lmu_status", "Installed" if is_inst else "Not Installed")
            dpg.configure_item("lbl_lmu_status", color=[46, 204, 113, 255] if is_inst else [231, 76, 60, 255])

        if dpg.does_item_exist("lbl_udp_status"):
            udp_recv = self._udp and self._udp.is_receiving()
            dpg.set_value("lbl_udp_status", "Active" if udp_recv else "Waiting...")
            dpg.configure_item("lbl_udp_status", color=[46, 204, 113, 255] if udp_recv else [231, 76, 60, 255])

    def _process_telemetry_frame(self, data: TelemetryData):
        sensors = data.to_sensors()
        if self._synth:
            self._synth.update_telemetry(
                abs_val=sensors.lock_intensity,
                abs_l=sensors.lock_left,
                abs_r=sensors.lock_right,
                tc_val=sensors.spin_intensity,
                tc_l=sensors.spin_left,
                tc_r=sensors.spin_right,
                over_val=sensors.oversteer_intensity,
                over_l=sensors.oversteer_left,
                over_r=sensors.oversteer_right,
                und_val=sensors.understeer_intensity,
                und_l=sensors.understeer_left,
                und_r=sensors.understeer_right,
            )

        al, ar, bgl, bgr = data.longitudinal_patch_vel
        cll, clr, crl, crr = data.lateral_patch_vel
        now = time.time() - self._start_time

        low_val, high_val = self._node_editor.evaluate_graph()

        self._t.append(now)
        self._d_abs.append(min(1.0, max(abs(al), abs(ar))))
        self._d_tc.append(min(1.0, max(abs(bgl), abs(bgr))))
        self._d_over.append(min(1.0, max(abs(crl), abs(crr))))
        self._d_und.append(min(1.0, max(abs(cll), abs(clr))))
        self._d_low.append(low_val)
        self._d_high.append(high_val)

        self._refresh_live_plots()

    def _refresh_live_plots(self):
        t_list = list(self._t)
        if dpg.does_item_exist("mon_series_abs"):
            dpg.set_value("mon_series_abs", [t_list, list(self._d_abs)])
            dpg.set_value("mon_series_tc", [t_list, list(self._d_tc)])
            dpg.set_value("mon_series_over", [t_list, list(self._d_over)])
            dpg.set_value("mon_series_und", [t_list, list(self._d_und)])
            dpg.set_value("mon_series_low", [t_list, list(self._d_low)])
            dpg.set_value("mon_series_high", [t_list, list(self._d_high)])
            if t_list:
                dpg.set_axis_limits("mon_xaxis", t_list[0], t_list[-1])

    # ── Shutdown ───────────────────────────────────────────────────────────────
    def _on_close(self):
        if self._synth:
            self._synth.stop()
        if self._haptics:
            self._haptics.close()
        if self._udp:
            self._udp.stop()


if __name__ == "__main__":
    app = SimPadDPGApp()
    app.run()
