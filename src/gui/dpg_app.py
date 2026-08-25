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
from src.haptics import HapticController, HapticBackendFactory
from src.gui.node_editor import NodeEditorTab
from src.gui.dashboards import DashboardManager

HISTORY = 150  # 7.5 seconds at 20 Hz


class SimPadDPGApp:
    def __init__(self):
        self._lmu_installer = LMUPluginManager()
        self._telemetry_enabled = True

        # Dashboard Manager Sub-System
        self._dashboard_mgr = DashboardManager()

        # Backends
        self._haptics: Optional[HapticController] = None
        self._synth: Optional[HapticSynthesizerEngine] = None
        self._udp: Optional[UDPServer] = None
        self._physics: Optional[PhysicsToHaptic] = None

        # Data history
        self._xs_200 = [x / 200.0 for x in range(201)]
        self._t = deque([-(HISTORY - i) * 0.05 for i in range(HISTORY)], maxlen=HISTORY)
        self._d_abs       = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._d_tc        = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._d_over      = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._d_und       = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._d_over_rev  = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._d_under_rev = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._d_rpm       = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._d_travel    = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._d_grip      = deque([1.0] * HISTORY, maxlen=HISTORY)
        self._d_low       = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._d_high      = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._start_time  = time.time()        # Node Editor Sub-Module
        self._node_editor = NodeEditorTab()
        self._is_pinned = False
        self._auto_overlay_active = False
        self._last_lmu_active_time = 0.0

    def run(self):
        viewport_title = "SimPad Haptic Middleware (Studio Console)"

        dpg.create_context()
        dpg.create_viewport(
            title=viewport_title,
            width=1280,
            height=820,
            clear_color=[18, 18, 22, 255],
            always_on_top=False,
            decorated=True,
        )
        dpg.setup_dearpygui()

        self._apply_theme()
        self._setup_key_handlers()
        self._build_gui()

        dpg.show_viewport()
        dpg.set_primary_window("primary_window", True)

        # Initialize backends in background
        threading.Thread(target=self._init_backends, daemon=True).start()

        # Render loop
        while dpg.is_dearpygui_running():
            self._render_tick()
            dpg.render_dearpygui_frame()

        self._on_close()
        dpg.destroy_context()

    def _setup_key_handlers(self):
        with dpg.handler_registry():
            dpg.add_key_release_handler(key=dpg.mvKey_F5, callback=self._toggle_pin)

    def _toggle_pin(self, sender=None, app_data=None, user_data=None):
        self._toggle_monitoring_board()

    # ── Background Backends Init ──────────────────────────────────────────────
    def _init_backends(self):
        try:
            self._haptics = HapticBackendFactory.create_backend()
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

        try:
            installed, status_msg, _ = self._lmu_installer.check_plugin_installed()
            if dpg.does_item_exist("lbl_plugin_status"):
                if installed:
                    dpg.set_value("lbl_plugin_status", "Installed")
                    dpg.configure_item("lbl_plugin_status", color=[46, 204, 113, 255])
                else:
                    dpg.set_value("lbl_plugin_status", "Not Installed")
                    dpg.configure_item("lbl_plugin_status", color=[231, 76, 60, 255])
        except Exception as e:
            print(f"[PLUGIN] Check status error: {e}", flush=True)


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
        dejavu_font = _PROJECT_ROOT / "assets" / "fonts" / "DejaVuSans.ttf"
        if dejavu_font.exists():
            try:
                with dpg.font_registry():
                    main_font = dpg.add_font(str(dejavu_font), 18)
                    dpg.bind_font(main_font)
                    print(f"[Font] Loaded main console font: {dejavu_font} (18px)", flush=True)
            except Exception as e:
                print(f"[Font] Error loading main font {dejavu_font}: {e}", flush=True)
        else:
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
        self._dashboard_mgr.build_all_ui()
        self._dashboard_mgr.set_display_mode("desktop")

    # ── Dashboard Tab Layout ──────────────────────────────────────────────────
    def _build_dashboard_tab(self):
        with dpg.child_window(height=46, border=True):
            with dpg.group(horizontal=True):
                dpg.add_text("Plugin:", color=[180, 180, 180, 255])
                dpg.add_text("Checking...", tag="lbl_plugin_status", color=[243, 156, 18, 255])
                dpg.add_button(label="Install Plugin", tag="btn_install_plugin", width=110, callback=self._cb_install_plugin)

                dpg.add_spacer(width=15)
                dpg.add_text("LMU Window:", color=[180, 180, 180, 255])
                dpg.add_text("Not Running", tag="lbl_lmu_fg_status", color=[231, 76, 60, 255])

                dpg.add_spacer(width=15)
                dpg.add_text("UDP Telemetry:", color=[180, 180, 180, 255])
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
            dpg.add_spacer(height=10)
            dpg.add_text("Activation des Overlays HUD :", color=[255, 200, 0, 255])
            dpg.add_checkbox(
                label="Overlay LMU HUD (Vitesse, Gear, Delta, Secteurs)",
                tag="chk_overlay_lmuHudBoard",
                default_value=True,
                callback=self._cb_toggle_overlay_lmuHudBoard,
            )
            dpg.add_checkbox(
                label="Overlay Telemetry Monitor (Graphes de courbes)",
                tag="chk_overlay_monitoringBoard",
                default_value=False,  # Désactivé par défaut comme demandé
                callback=self._cb_toggle_overlay_monitoringBoard,
            )
            dpg.add_spacer(height=10)
            dpg.add_button(label="Toggle Display Mode (Desktop <-> InGame Overlay)", width=320, callback=self._toggle_monitoring_board)

    def _cb_toggle_overlay_lmuHudBoard(self, sender, app_data):
        self._dashboard_mgr.set_dashboard_enabled("lmuHudBoard", app_data)

    def _cb_toggle_overlay_monitoringBoard(self, sender, app_data):
        self._dashboard_mgr.set_dashboard_enabled("monitoringBoard", app_data)

    def _toggle_monitoring_board(self):
        if self._dashboard_mgr.display_mode == "ingame":
            self._dashboard_mgr.set_display_mode("desktop")
        else:
            self._dashboard_mgr.set_display_mode("ingame")


    # ── Monitor Tab Layout ────────────────────────────────────────────────────
    def _build_monitor_tab(self):
        with dpg.child_window(width=-1, height=-1, border=False):
            dpg.add_text("Live Telemetry Signal Monitor (20 Hz)", color=[0, 210, 255, 255])
            with dpg.plot(no_title=True, height=-1, width=-1, tag="mon_plot"):
                dpg.add_plot_legend()
                dpg.add_plot_axis(dpg.mvXAxis, label="Time (s)", tag="mon_xaxis")
                with dpg.plot_axis(dpg.mvYAxis, label="Intensity [0.0 - 1.0]", tag="mon_yaxis"):
                    dpg.set_axis_limits("mon_yaxis", 0, 1.05)
                    dpg.add_line_series([], [], label="ABS (Braking)", tag="mon_series_abs")
                    dpg.add_line_series([], [], label="Traction (Spin)", tag="mon_series_tc")
                    dpg.add_line_series([], [], label="Oversteer", tag="mon_series_over")
                    dpg.add_line_series([], [], label="Understeer", tag="mon_series_und")
                    dpg.add_line_series([], [], label="Over-Rev (Sur-régime)", tag="mon_series_over_rev")
                    dpg.add_line_series([], [], label="Under-Rev (Sous-régime)", tag="mon_series_under_rev")
                    dpg.add_line_series([], [], label="Engine RPM", tag="mon_series_rpm")
                    dpg.add_line_series([], [], label="Wheel Travel (Curbs)", tag="mon_series_travel")
                    dpg.add_line_series([], [], label="Grip Fraction", tag="mon_series_grip")
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
    def _render_tick(self):
        if not hasattr(self, "_lmu_installer"):
            return

        if hasattr(self, "_dashboard_mgr") and hasattr(self._dashboard_mgr, "_qt_app"):
            try:
                self._dashboard_mgr._qt_app.processEvents()
            except Exception:
                pass

        self._update_status_indicators()
        self._check_lmu_auto_overlay()

        udp_active = bool(self._udp and self._udp.is_receiving(timeout=2.0) and self._telemetry_enabled)
        if udp_active:
            self._was_udp_receiving = True
            data = self._udp.get_latest_data()
            if data:
                self._process_telemetry_frame(data)
            else:
                self._clear_telemetry_frame(clear_synth=True)
        else:
            if getattr(self, "_was_udp_receiving", False):
                self._was_udp_receiving = False
                self._clear_telemetry_frame(clear_synth=True)
            else:
                self._clear_telemetry_frame(clear_synth=False)

    def _clear_telemetry_frame(self, clear_synth: bool = True):
        if clear_synth and self._synth:
            self._synth.update_telemetry(in_realtime=False)
        if hasattr(self, "_node_editor"):
            self._node_editor.evaluate_graph()


    def _check_lmu_auto_overlay(self):
        """
        Délègue la décision d'affichage au DashboardManager pour l'ensemble des overlays HUD enregistrés :
        - 'ingame'  : LMU actif au premier plan ET conduite en piste (is_fg=True, on_track=True).
        - 'pause'   : LMU actif au premier plan MAIS en pause/garage/stands (is_fg=True, on_track=False).
        - 'desktop' : LMU en arrière-plan (Background) ou fermé -> Overlay masqué immédiatement.
        """
        from src.utils.window_utils import is_lmu_foreground

        is_lmu_fg = is_lmu_foreground()
        udp_recv = bool(self._udp and self._udp.is_receiving())
        latest = self._udp.get_latest_data() if self._udp else None
        on_track = bool(latest.in_realtime if (latest and udp_recv) else False)

        if not is_lmu_fg:
            # LMU en arrière-plan ou fermé -> masquer immédiatement l'overlay HUD
            if self._dashboard_mgr.display_mode != "desktop":
                self._dashboard_mgr.set_display_mode("desktop")
        elif udp_recv and on_track:
            # LMU au premier plan ET en train de rouler en piste -> afficher le HUD Qt
            if self._dashboard_mgr.display_mode != "ingame":
                self._dashboard_mgr.set_display_mode("ingame")
        else:
            # LMU au premier plan MAIS en pause / menu / garage -> masquer le HUD Qt
            if self._dashboard_mgr.display_mode != "pause":
                self._dashboard_mgr.set_display_mode("pause")


    def _update_status_indicators(self):
        from src.utils.window_utils import get_lmu_window_status
        lmu_status = get_lmu_window_status()

        if dpg.does_item_exist("lbl_lmu_fg_status"):
            if lmu_status == "foreground":
                dpg.set_value("lbl_lmu_fg_status", "Foreground (Active)")
                dpg.configure_item("lbl_lmu_fg_status", color=[46, 204, 113, 255])
            elif lmu_status == "background":
                dpg.set_value("lbl_lmu_fg_status", "Background")
                dpg.configure_item("lbl_lmu_fg_status", color=[241, 196, 15, 255])
            else:
                dpg.set_value("lbl_lmu_fg_status", "Not Running")
                dpg.configure_item("lbl_lmu_fg_status", color=[231, 76, 60, 255])

        if dpg.does_item_exist("lbl_udp_status"):
            udp_recv = self._udp and self._udp.is_receiving()
            latest = self._udp.get_latest_data() if self._udp else None
            on_track = latest.in_realtime if latest else False
            if udp_recv and on_track:
                status_str = "On Track (InGame)"
                status_col = [46, 204, 113, 255]
            elif udp_recv and not on_track:
                status_str = "In Menu / Pit Standby"
                status_col = [241, 196, 15, 255]
            else:
                status_str = "Waiting..."
                status_col = [231, 76, 60, 255]

            prev_status = getattr(self, "_last_udp_status_str", None)
            if status_str != prev_status:
                self._last_udp_status_str = status_str
                prev_lbl = prev_status if prev_status is not None else "INIT"
                import logging
                logging.getLogger(__name__).info(f"[UDP STATUS GUI] {prev_lbl} -> {status_str}")

            dpg.set_value("lbl_udp_status", status_str)
            dpg.configure_item("lbl_udp_status", color=status_col)

        if dpg.does_item_exist("lbl_pad_status"):
            pad_connected = self._haptics is not None and self._haptics.is_connected()
            if pad_connected:
                pad_name = self._haptics.get_gamepad_name()
                status_str = f"Connected ({pad_name})"
                status_col = [46, 204, 113, 255]
            else:
                status_str = "Disconnected"
                status_col = [231, 76, 60, 255]
            dpg.set_value("lbl_pad_status", status_str)
            dpg.configure_item("lbl_pad_status", color=status_col)

    def _process_telemetry_frame(self, data: TelemetryData):
        sensors = data.to_sensors()
        self._dashboard_mgr.update_telemetry(sensors)
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
                over_rev=sensors.overrev_intensity,
                under_rev=sensors.underrev_intensity,
                rpm=sensors.rpm_ratio,
                gear=sensors.gear,
                travel_val=sensors.travel_intensity,
                travel_l=sensors.travel_left,
                travel_r=sensors.travel_right,
                travel_fl=sensors.front_left_travel,
                travel_fr=sensors.front_right_travel,
                travel_rl=sensors.rear_left_travel,
                travel_rr=sensors.rear_right_travel,
                grip_val=sensors.grip_intensity,
                grip_l=sensors.grip_left,
                grip_r=sensors.grip_right,
                in_realtime=sensors.in_realtime,
            )

        al, ar, bgl, bgr = data.longitudinal_patch_vel
        cll, clr, crl, crr = data.lateral_patch_vel
        now = time.time() - self._start_time

        low_val, high_val = self._node_editor.evaluate_graph()

        if len(self._t) == HISTORY and self._t[0] < 0:
            # Smoothly re-base initial time window to span [now - 7.45s, now]
            self._t = deque([now - (HISTORY - 1 - i) * 0.05 for i in range(HISTORY)], maxlen=HISTORY)
        else:
            self._t.append(now)

        self._d_abs.append(sensors.lock_intensity)
        self._d_tc.append(sensors.spin_intensity)
        self._d_over.append(sensors.oversteer_intensity)
        self._d_und.append(sensors.understeer_intensity)
        self._d_over_rev.append(sensors.overrev_intensity)
        self._d_under_rev.append(sensors.underrev_intensity)
        self._d_rpm.append(sensors.rpm_ratio)
        self._d_travel.append(sensors.travel_intensity)
        self._d_grip.append(sensors.grip_intensity)
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
            dpg.set_value("mon_series_over_rev", [t_list, list(self._d_over_rev)])
            dpg.set_value("mon_series_under_rev", [t_list, list(self._d_under_rev)])
            dpg.set_value("mon_series_rpm", [t_list, list(self._d_rpm)])
            dpg.set_value("mon_series_travel", [t_list, list(self._d_travel)])
            dpg.set_value("mon_series_grip", [t_list, list(self._d_grip)])
            dpg.set_value("mon_series_low", [t_list, list(self._d_low)])
            dpg.set_value("mon_series_high", [t_list, list(self._d_high)])
            if len(t_list) >= 2:
                dpg.set_axis_limits("mon_xaxis", t_list[0], t_list[-1])

        self._dashboard_mgr.update_history_plots(
            t_list,
            self._d_abs,
            self._d_tc,
            self._d_over,
            self._d_und,
            self._d_rpm,
            self._d_travel,
            self._d_low,
            self._d_high,
        )

    # ── Shutdown ───────────────────────────────────────────────────────────────
    def _on_close(self):
        self._dashboard_mgr.set_display_mode("desktop")
        if self._synth:
            self._synth.stop()
        if self._haptics:
            self._haptics.close()
        if self._udp:
            self._udp.stop()


if __name__ == "__main__":
    app = SimPadDPGApp()
    app.run()
