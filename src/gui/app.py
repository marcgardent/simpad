"""
SimPad — Main GUI Application Window.
Orchestrates views, profile manager, telemetry processing and haptics loop.
"""

import sys
import time
import math
import threading
from collections import deque
from pathlib import Path
from typing import Dict, Any, Optional
from tkinter import messagebox

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import customtkinter as ctk

from src.profiles.manager import ProfileManager, Profile, PRESET_NAMES
from src.gui.dialogs import InputModalDialog
from src.gui.charts import MonitorChart, EffectCurveChart, MiniEffectChart
from src.gui.views.profile_bar import ProfileBar
from src.gui.views.dashboard import DashboardTab
from src.gui.views.monitor import MonitorTab
from src.gui.views.effect_tuning import EffectTuningTab
from src.telemetry.lmu_parser import TelemetryData

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

HISTORY = 150

EFFECTS = [
    {
        "id": "lock",
        "label": "ABS / Braking",
        "desc": "Wheel lock — longitudinal slip on front wheels",
        "color": "#00d2ff",
        "defaults": {
            "threshold": 0.15,
            "low_gain": 0.3,
            "low_gamma": 1.0,
            "high_gain": 1.0,
            "high_gamma": 1.5,
        },
    },
    {
        "id": "oversteer",
        "label": "Oversteer",
        "desc": "Rear axle lateral slip",
        "color": "#e74c3c",
        "defaults": {
            "threshold": 0.12,
            "low_gain": 1.0,
            "low_gamma": 1.2,
            "high_gain": 0.4,
            "high_gamma": 1.0,
        },
    },
    {
        "id": "understeer",
        "label": "Understeer",
        "desc": "Front axle lateral slip",
        "color": "#a569bd",
        "defaults": {
            "threshold": 0.10,
            "low_gain": 0.5,
            "low_gamma": 1.5,
            "high_gain": 0.8,
            "high_gamma": 1.0,
        },
    },
    {
        "id": "spin",
        "label": "Traction / Spin",
        "desc": "Rear wheel spin on acceleration (TC)",
        "color": "#ff9900",
        "defaults": {
            "threshold": 0.18,
            "low_gain": 1.0,
            "low_gamma": 1.0,
            "high_gain": 0.2,
            "high_gamma": 2.0,
        },
    },
]


from src.core.math_utils import apply_response_curve

# TODO: [DRY] Replaced local duplicate _apply_curve definition with central apply_response_curve from src.core.math_utils.


# TODO: [SRP] EffectState encapsulates GUI effect tuning state, delegating math response curve evaluations to math_utils.
class EffectState:
    def __init__(self, eid: str, defaults: dict):
        self.eid = eid
        self.enabled = True
        self.threshold = defaults["threshold"]
        self.low_gain = defaults["low_gain"]
        self.low_gamma = defaults["low_gamma"]
        self.high_gain = defaults["high_gain"]
        self.high_gamma = defaults["high_gamma"]

    def low_curve(self, xs):
        return [apply_response_curve(x, self.low_gamma, self.low_gain, self.threshold) for x in xs]

    def high_curve(self, xs):
        return [apply_response_curve(x, self.high_gamma, self.high_gain, self.threshold) for x in xs]

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


class SimPadGUI(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("SimPad Haptic Middleware")
        self.geometry("1200x740")
        self.minsize(960, 620)

        # Infrastructure handles
        self._haptics = None
        self._udp = None
        self._physics = None
        self._ready = False
        self._is_closing = False
        self._telemetry_enabled = True
        self._is_resizing = False
        self._resize_timer = None
        self.bind("<Configure>", self._on_window_resize)

        # Profile manager
        self._pm = ProfileManager()
        self._current_profile_name = "Default"
        self._unsaved = False

        # Effect states
        self._states = {e["id"]: EffectState(e["id"], e["defaults"]) for e in EFFECTS}

        # Telemetry history buffers
        self._t = deque([-(HISTORY - i) * 0.05 for i in range(HISTORY)], maxlen=HISTORY)
        self._d_abs = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._d_tc = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._d_over = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._d_und = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._d_low = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._d_high = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._start_time = time.time()

        # Component references
        self._profile_bar: ProfileBar = None
        self._dash_view: DashboardTab = None
        self._monitor_view: MonitorTab = None
        self._effect_views: Dict[str, EffectTuningTab] = {}

        # Chart references
        self._monitor_chart: Optional[MonitorChart] = None
        self._effect_charts: Dict[str, EffectCurveChart] = {}
        self._mini_charts: Dict[str, MiniEffectChart] = {}

        self._build_ui()
        self._load_profile_into_ui("Default")

        # Deferred initialization chain
        self.after(300, self._load_backends)
        self.after(600, self._poll_status)
        self.after(900, self._load_monitor_chart)
        self.after(1200, self._load_effect_charts)
        self.after(1500, self._load_dashboard_charts)
        self.after(1800, self._tick)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Construction UI ────────────────────────────────────────────────────────
    def _build_ui(self):
        # 1. Top profile bar
        self._profile_bar = ProfileBar(
            parent=self,
            profile_names=self._pm.list_all(),
            current_profile=self._current_profile_name,
            on_select=self._on_profile_selected,
            on_save=self._save_profile,
            on_new=self._new_profile,
            on_rename=self._rename_profile,
            on_copy=self._copy_profile,
            on_delete=self._delete_profile,
        )

        # 2. Main tabs
        self._tabs = ctk.CTkTabview(self)
        self._tabs.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        tab_dash = self._tabs.add("Dashboard")
        tab_monitor = self._tabs.add("Monitor")

        self._dash_view = DashboardTab(
            parent_tab=tab_dash,
            effects_def=EFFECTS,
            on_toggle_effect=self._toggle_effect,
            on_toggle_telemetry=self._toggle_telemetry,
        )
        self._monitor_view = MonitorTab(parent_tab=tab_monitor)

        for e in EFFECTS:
            tab_eff = self._tabs.add(e["label"])
            view = EffectTuningTab(
                parent_tab=tab_eff,
                effect_def=e,
                state=self._states[e["id"]],
                on_toggle=self._toggle_effect,
                on_param_change=self._on_param_change,
            )
            self._effect_views[e["id"]] = view

    # ── Profile Operations ────────────────────────────────────────────────────
    def _on_profile_selected(self, name: str):
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
                self._states[eid].load_dict(profile.effects[eid])
                if eid in self._effect_views:
                    self._effect_views[eid].sync_from_state(self._states[eid])
                if self._physics:
                    self._physics.update_config(self._states[eid].to_physics_config())
                self._redraw_effect_curves(eid)

    def _save_profile(self):
        name = self._current_profile_name
        if name in PRESET_NAMES:
            def _do_save_as(new_name: str):
                if not new_name:
                    return "Profile name cannot be empty."
                effects = {e["id"]: self._states[e["id"]].to_dict() for e in EFFECTS}
                p = Profile(name=new_name, effects=effects)
                if self._pm.save(p):
                    self._current_profile_name = new_name
                    self._profile_bar.refresh(self._pm.list_all(), select=new_name)
                    self._clear_unsaved()
                    return None
                return "Failed to save profile."

            InputModalDialog(
                parent=self,
                title="Save as Custom Profile",
                subtitle=f"'{name}' is a preset and cannot be modified. Enter a name for your custom profile:",
                default_text=f"{name} Custom",
                action_label="💾 Save Profile",
                on_submit=_do_save_as,
            )
            return

        effects = {e["id"]: self._states[e["id"]].to_dict() for e in EFFECTS}
        profile = Profile(name=name, effects=effects)
        if self._pm.save(profile):
            self._profile_bar.refresh(self._pm.list_all(), select=name)
            self._clear_unsaved()

    def _new_profile(self):
        def _do_create(name: str):
            if not name:
                return "Profile name cannot be empty."
            if self._pm.exists(name):
                return f"A profile named '{name}' already exists."
            effects = {e["id"]: self._states[e["id"]].to_dict() for e in EFFECTS}
            profile = Profile(name=name, effects=effects)
            self._pm.save(profile)
            self._current_profile_name = name
            self._profile_bar.refresh(self._pm.list_all(), select=name)
            self._clear_unsaved()
            return None

        InputModalDialog(
            parent=self,
            title="Create New Profile",
            subtitle="Enter a name for your new haptic configuration:",
            default_text="My Custom Profile",
            action_label="✨ Create Profile",
            on_submit=_do_create,
        )

    def _copy_profile(self):
        src = self._current_profile_name
        def _do_copy(name: str):
            if not name:
                return "Profile name cannot be empty."
            if self._pm.exists(name):
                return f"A profile named '{name}' already exists."
            p = self._pm.duplicate(src, name)
            if p:
                self._current_profile_name = name
                self._profile_bar.refresh(self._pm.list_all(), select=name)
                self._clear_unsaved()
                return None
            return "Failed to copy profile."

        InputModalDialog(
            parent=self,
            title="Duplicate Profile",
            subtitle=f"Creating a copy of '{src}'. Enter new profile name:",
            default_text=f"{src} Copy",
            action_label="📋 Copy Profile",
            on_submit=_do_copy,
        )

    def _rename_profile(self):
        src = self._current_profile_name
        if src in PRESET_NAMES:
            messagebox.showwarning("Read-only", "Presets cannot be renamed.", parent=self)
            return

        def _do_rename(new_name: str):
            if not new_name:
                return "Profile name cannot be empty."
            if new_name == src:
                return None
            if self._pm.exists(new_name):
                return f"A profile named '{new_name}' already exists."
            if self._pm.rename(src, new_name):
                self._current_profile_name = new_name
                self._profile_bar.refresh(self._pm.list_all(), select=new_name)
                return None
            return "Failed to rename profile."

        InputModalDialog(
            parent=self,
            title="Rename Profile",
            subtitle=f"Renaming '{src}'. Enter new profile name:",
            default_text=src,
            action_label="✏️ Rename",
            on_submit=_do_rename,
        )

    def _delete_profile(self):
        name = self._current_profile_name
        if name in PRESET_NAMES:
            messagebox.showwarning("Read-only", "Presets cannot be deleted.", parent=self)
            return
        if not messagebox.askyesno("Delete Profile", f"Are you sure you want to delete '{name}'?", parent=self):
            return
        self._pm.delete(name)
        self._profile_bar.refresh(self._pm.list_all(), select="Default")
        self._load_profile_into_ui("Default")
        self._current_profile_name = "Default"
        self._clear_unsaved()

    def _mark_unsaved(self):
        self._unsaved = True
        self._profile_bar.set_unsaved(True)

    def _clear_unsaved(self):
        self._unsaved = False
        self._profile_bar.set_unsaved(False)

    # ── Resize Debouncing ──────────────────────────────────────────────────────
    def _on_window_resize(self, event):
        if event.widget == self:
            self._is_resizing = True
            if self._resize_timer is not None:
                self.after_cancel(self._resize_timer)
            self._resize_timer = self.after(150, self._on_resize_end)

    def _on_resize_end(self):
        self._is_resizing = False
        self._resize_timer = None
        if getattr(self, "_is_closing", False):
            return
        if self._monitor_chart:
            self._monitor_chart.canvas.draw_idle()
        for chart in self._effect_charts.values():
            chart.canvas.draw_idle()
        for mini in self._mini_charts.values():
            mini.canvas.draw_idle()

    # ── Parameters & Toggle Callbacks ──────────────────────────────────────────
    def _toggle_telemetry(self, enabled: bool):
        self._telemetry_enabled = enabled
        if not enabled and self._haptics:
            self._haptics.set_vibration(0, 0, 0, 0)

    def _toggle_effect(self, eid: str, enabled: bool):
        self._states[eid].enabled = enabled
        if self._physics:
            self._physics.update_config(self._states[eid].to_physics_config())
        self._mark_unsaved()

    def _on_param_change(self, eid: str, param: str, val: float):
        setattr(self._states[eid], param, val)
        if self._physics:
            self._physics.update_config(self._states[eid].to_physics_config())
        self._redraw_effect_curves(eid)
        self._mark_unsaved()

    def _redraw_effect_curves(self, eid: str):
        if eid in self._effect_charts:
            self._effect_charts[eid].redraw_curve()
        if eid in self._mini_charts:
            self._mini_charts[eid].redraw_curve()

    # ── Deferred Initialization ────────────────────────────────────────────────
    def _load_backends(self):
        def _init():
            try:
                from src.haptics.windows import WindowsHapticController
                self._haptics = WindowsHapticController()
            except Exception as e:
                print(f"[HAPTICS] {e}", flush=True)
            try:
                from src.telemetry.udp_server import UDPServer
                self._udp = UDPServer(host="0.0.0.0", port=5606)
                self._udp.start()
            except Exception as e:
                print(f"[UDP] {e}", flush=True)
            try:
                from src.physics.effects import PhysicsToHaptic
                self._physics = PhysicsToHaptic()
                for e in EFFECTS:
                    self._physics.update_config(self._states[e["id"]].to_physics_config())
            except Exception as e:
                print(f"[PHYSICS] {e}", flush=True)
            self._ready = True

        threading.Thread(target=_init, daemon=True).start()

    def _load_monitor_chart(self):
        try:
            self._monitor_view.placeholder.destroy()
            self._monitor_chart = MonitorChart(self._monitor_view.chart_frame)
        except Exception as e:
            print(f"[MONITOR CHART] {e}", flush=True)

    def _load_effect_charts(self):
        try:
            for effect in EFFECTS:
                eid = effect["id"]
                view = self._effect_views[eid]
                view.placeholder.destroy()
                chart = EffectCurveChart(view.chart_container, self._states[eid])
                self._effect_charts[eid] = chart
        except Exception as e:
            print(f"[EFFECT CHARTS] {e}", flush=True)

    def _load_dashboard_charts(self):
        try:
            for effect in EFFECTS:
                eid = effect["id"]
                parent = self._dash_view.chart_containers[eid]
                self._dash_view.placeholders[eid].destroy()
                mini = MiniEffectChart(parent, self._states[eid])
                self._mini_charts[eid] = mini
        except Exception as e:
            print(f"[DASH CHARTS] {e}", flush=True)

    # ── Status Polling ─────────────────────────────────────────────────────────
    def _poll_status(self):
        if getattr(self, "_is_closing", False):
            return
        if self._ready:
            if self._udp:
                active, _, count = self._udp.is_receiving_packets()
                self._dash_view.update_udp_status(active, count)
            if self._haptics:
                is_conn = self._haptics.is_connected()
                pad_name = self._haptics.get_gamepad_name() if is_conn else ""
                self._dash_view.update_pad_status(is_conn, pad_name)
        self.after(500, self._poll_status)

    # ── Telemetry Tick (20 Hz) & Stick Test Mode ──────────────────────────────
    def _tick(self):
        if getattr(self, "_is_closing", False):
            return

        if self._ready and self._udp and self._physics and getattr(self, '_telemetry_enabled', True):
            active, _, _ = self._udp.is_receiving_packets()
            if active:
                data = self._udp.get_latest_data()
                if data:
                    try:
                        l_low, l_high, r_low, r_high = self._physics.process(data)
                        if self._haptics:
                            self._haptics.set_vibration(l_low, l_high, r_low, r_high)

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

                        # Live telemetry cursors on dashboard mini charts
                        slip_map = {
                            "lock": min(1.0, max(abs(al), abs(ar))),
                            "spin": min(1.0, max(abs(bgl), abs(bgr))),
                            "oversteer": min(1.0, max(abs(crl), abs(crr))),
                            "understeer": min(1.0, max(abs(cll), abs(clr))),
                        }
                        for _eid, _slip in slip_map.items():
                            s = self._states[_eid]
                            _lo = _apply_curve(_slip, s.low_gamma, s.low_gain, s.threshold)
                            _hi = _apply_curve(_slip, s.high_gamma, s.high_gain, s.threshold)
                            if _eid in self._mini_charts:
                                self._mini_charts[_eid].update_cursor(_slip, _lo, _hi, skip_draw=self._is_resizing)
                    except Exception as e:
                        print(f"[TICK] {e}", flush=True)

        if self._monitor_chart:
            self._monitor_chart.update(
                list(self._t),
                list(self._d_abs),
                list(self._d_tc),
                list(self._d_over),
                list(self._d_und),
                list(self._d_low),
                list(self._d_high),
                skip_draw=self._is_resizing,
            )

        self._update_test_cursors()
        self.after(50, self._tick)

    def _update_test_cursors(self):
        """Reads stick position and A-button state, updates effect tab cursors and sends test haptics."""
        if not self._haptics or not self._haptics.is_connected():
            return

        try:
            raw = self._haptics.get_left_stick_x()
        except Exception:
            raw = 0.0
        if abs(raw) < 0.10:
            raw = 0.0
        input_val = (raw + 1.0) / 2.0

        try:
            btn_held = self._haptics.get_south_button()
        except Exception:
            btn_held = False

        current_tab = self._tabs.get()
        label_to_eid = {e["label"]: e["id"] for e in EFFECTS}
        active_eid = label_to_eid.get(current_tab)

        for eid, view in self._effect_views.items():
            state = self._states[eid]
            out_low = _apply_curve(input_val, state.low_gamma, state.low_gain, state.threshold)
            out_high = _apply_curve(input_val, state.high_gamma, state.high_gain, state.threshold)

            is_firing = btn_held and (eid == active_eid)
            view.update_readout(input_val, out_low, out_high, is_firing)

            if eid in self._effect_charts:
                self._effect_charts[eid].update_cursor(input_val, out_low, out_high, skip_draw=self._is_resizing)
            if eid in self._mini_charts:
                self._mini_charts[eid].update_cursor(input_val, out_low, out_high, skip_draw=self._is_resizing)

        if btn_held and active_eid:
            s = self._states[active_eid]
            v_low = _apply_curve(input_val, s.low_gamma, s.low_gain, s.threshold)
            v_high = _apply_curve(input_val, s.high_gamma, s.high_gain, s.threshold)
            self._haptics.set_vibration(v_low, v_high, v_low, v_high)
        elif not btn_held:
            self._haptics.set_vibration(0, 0, 0, 0)

    # ── Shutdown ───────────────────────────────────────────────────────────────
    def _on_close(self):
        self._is_closing = True
        if self._unsaved:
            if messagebox.askyesno(
                "Unsaved changes",
                "You have unsaved changes.\nSave before closing?",
                parent=self,
            ):
                self._save_profile()
        if self._haptics:
            self._haptics.close()
        if self._udp:
            self._udp.stop()
        self.destroy()


if __name__ == "__main__":
    app = SimPadGUI()
    app.mainloop()
