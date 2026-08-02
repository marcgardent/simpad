"""
SimPad GUI Views — EffectTuningTab component.
Single Responsibility: Layout and slider controls for per-effect tuning tab.
"""

import customtkinter as ctk
from typing import Dict, Any, Callable


class EffectTuningTab:
    """Renders a single effect calibration & tuning tab view."""

    def __init__(
        self,
        parent_tab: ctk.CTkFrame,
        effect_def: Dict[str, Any],
        state,
        on_toggle: Callable[[str, bool], None],
        on_param_change: Callable[[str, str, float], None],
    ):
        self.parent = parent_tab
        self.effect = effect_def
        self.eid = effect_def["id"]
        self.state = state
        self.on_toggle = on_toggle
        self.on_param_change = on_param_change

        self.slider_updaters: Dict[str, Callable[[float], None]] = {}
        self.chart_container: ctk.CTkFrame = None
        self.placeholder: ctk.CTkLabel = None

        self._build_ui()

    def _build_ui(self):
        p = self.parent
        color = self.effect["color"]

        # Header
        hdr = ctk.CTkFrame(p, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(16, 2))

        ctk.CTkLabel(
            hdr,
            text=self.effect["label"],
            font=ctk.CTkFont(size=19, weight="bold"),
            text_color=color,
        ).pack(side="left")

        sw_var = ctk.BooleanVar(value=True)
        self.enable_var = sw_var
        ctk.CTkSwitch(
            hdr,
            text="Enabled",
            variable=sw_var,
            font=ctk.CTkFont(size=13),
            command=lambda v=sw_var: self.on_toggle(self.eid, v.get()),
            onvalue=True,
            offvalue=False,
        ).pack(side="right", padx=10)

        ctk.CTkLabel(
            p,
            text=self.effect["desc"],
            font=ctk.CTkFont(size=11),
            text_color="#777777",
        ).pack(anchor="w", padx=22, pady=(0, 10))

        # Body: Sliders | Chart
        body = ctk.CTkFrame(p, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=4)
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # Sliders panel
        sliders_frame = ctk.CTkFrame(body, fg_color="#191919", corner_radius=10, width=330)
        sliders_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        sliders_frame.pack_propagate(False)

        def _slider_row(label: str, param_name: str, lo: float, hi: float, default: float, label_color: str = "#cccccc"):
            row = ctk.CTkFrame(sliders_frame, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=5)
            ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=11), text_color=label_color, width=90, anchor="w").pack(side="left")
            val_var = ctk.StringVar(value=f"{default:.2f}")
            ctk.CTkLabel(row, textvariable=val_var, font=ctk.CTkFont(size=11, weight="bold"), width=38).pack(side="left")

            def _cb(v, vv=val_var, pname=param_name):
                val = float(v)
                vv.set(f"{val:.2f}")
                self.on_param_change(self.eid, pname, val)

            sl = ctk.CTkSlider(row, from_=lo, to=hi, number_of_steps=60, command=_cb)
            sl.set(default)
            sl.pack(side="left", fill="x", expand=True, padx=(6, 0))

            def _update_ui(v: float, s=sl, vv=val_var):
                s.set(v)
                vv.set(f"{v:.2f}")

            self.slider_updaters[param_name] = _update_ui

        ctk.CTkLabel(sliders_frame, text="Trigger Threshold", font=ctk.CTkFont(size=11, weight="bold"), text_color="#888888").pack(anchor="w", padx=16, pady=(14, 0))
        _slider_row("Threshold", "threshold", 0.01, 0.50, self.state.threshold)

        ctk.CTkLabel(sliders_frame, text="Low Freq  —  Rumble Motor", font=ctk.CTkFont(size=11, weight="bold"), text_color="#ff3366").pack(anchor="w", padx=16, pady=(12, 0))
        _slider_row("Gain", "low_gain", 0.0, 2.0, self.state.low_gain, "#ff3366")
        _slider_row("Gamma", "low_gamma", 0.2, 3.0, self.state.low_gamma, "#ff3366")

        ctk.CTkLabel(sliders_frame, text="High Freq  —  Buzz Motor", font=ctk.CTkFont(size=11, weight="bold"), text_color="#00ff88").pack(anchor="w", padx=16, pady=(12, 0))
        _slider_row("Gain", "high_gain", 0.0, 2.0, self.state.high_gain, "#00ff88")
        _slider_row("Gamma", "high_gamma", 0.2, 3.0, self.state.high_gamma, "#00ff88")

        # Readout row
        ctk.CTkLabel(
            sliders_frame,
            text="Left stick ←/→  —  move cursor on the curve\nHold  Ⓐ  (A / Cross)  —  send vibration",
            font=ctk.CTkFont(size=10),
            text_color="#555555",
            justify="left",
        ).pack(anchor="w", padx=16, pady=(12, 6))

        readout_row = ctk.CTkFrame(sliders_frame, fg_color="transparent")
        readout_row.pack(fill="x", padx=16, pady=(0, 12))
        self.lbl_input = ctk.CTkLabel(readout_row, text="Input: —", font=ctk.CTkFont(size=10), text_color="#888888")
        self.lbl_input.pack(side="left", padx=(0, 10))
        self.lbl_out_low = ctk.CTkLabel(readout_row, text="Low: —", font=ctk.CTkFont(size=10), text_color="#ff3366")
        self.lbl_out_low.pack(side="left", padx=(0, 10))
        self.lbl_out_high = ctk.CTkLabel(readout_row, text="High: —", font=ctk.CTkFont(size=10), text_color="#00ff88")
        self.lbl_out_high.pack(side="left")

        # Chart container
        chart_outer = ctk.CTkFrame(body, fg_color="#111111", corner_radius=10)
        chart_outer.grid(row=0, column=1, sticky="nsew")
        ph = ctk.CTkLabel(chart_outer, text="⏳  Loading curve…", font=ctk.CTkFont(size=13), text_color="#555555")
        ph.pack(expand=True)

        self.placeholder = ph
        self.chart_container = chart_outer

    def sync_from_state(self, state):
        self.state = state
        self.enable_var.set(state.enabled)
        for param, updater in self.slider_updaters.items():
            if hasattr(state, param):
                updater(getattr(state, param))

    def update_readout(self, input_val: float, out_low: float, out_high: float, is_firing: bool):
        fire_str = "  ●" if is_firing else ""
        self.lbl_input.configure(text=f"Input: {input_val:.2f}{fire_str}")
        self.lbl_out_low.configure(text=f"Low:   {out_low:.2f}")
        self.lbl_out_high.configure(text=f"High:  {out_high:.2f}")
