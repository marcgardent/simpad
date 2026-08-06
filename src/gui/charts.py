"""
SimPad GUI — Charts module.
Single Responsibility: Matplotlib chart creation, styling, and data rendering.
"""

from typing import Tuple, Dict, Any, List
import customtkinter as ctk


class ChartStyling:
    @staticmethod
    def apply_dark(ax, title: str, xlabel: str, ylabel: str):
        ax.set_facecolor("#0d0d0d")
        ax.tick_params(colors="#aaaaaa", labelsize=8)
        for sp in ax.spines.values():
            sp.set_color("#333333")
        ax.set_ylim(-0.02, 1.15)
        ax.set_xlabel(xlabel, color="#aaaaaa", fontsize=9)
        ax.set_ylabel(ylabel, color="#aaaaaa", fontsize=9)
        ax.set_title(title, color="white", fontsize=10)
        ax.grid(True, color="#1a1a1a", linestyle="--", linewidth=0.7)


class MonitorChart:
    """Manages the main telemetry vs. vibration output real-time chart."""

    def __init__(self, parent_frame: ctk.CTkFrame):
        import matplotlib
        matplotlib.use("TkAgg")
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure

        fig = Figure(figsize=(8, 4), dpi=96, facecolor="#111111")
        fig.subplots_adjust(left=0.08, right=0.98, top=0.90, bottom=0.14)
        self.ax = fig.add_subplot(111)
        ChartStyling.apply_dark(self.ax, "LMU Telemetry vs Controller Vibration Output", "Time (s)", "Intensity")

        c = {
            "abs": "#00d2ff",
            "tc": "#ff9900",
            "over": "#e74c3c",
            "und": "#a569bd",
            "over_rev": "#ff0055",
            "under_rev": "#f1c40f",
            "rpm": "#2ecc71",
            "travel": "#1abc9c",
            "low": "#ff3366",
            "high": "#00ff88",
        }
        self.ln_abs,       = self.ax.plot([], [], color=c["abs"],       lw=1.2, label="ABS / Braking")
        self.ln_tc,        = self.ax.plot([], [], color=c["tc"],        lw=1.2, label="Traction / Spin")
        self.ln_over,      = self.ax.plot([], [], color=c["over"],      lw=1.2, label="Oversteer")
        self.ln_und,       = self.ax.plot([], [], color=c["und"],       lw=1.2, label="Understeer")
        self.ln_over_rev,  = self.ax.plot([], [], color=c["over_rev"],  lw=1.2, label="Over-Rev")
        self.ln_under_rev, = self.ax.plot([], [], color=c["under_rev"], lw=1.2, label="Under-Rev")
        self.ln_rpm,       = self.ax.plot([], [], color=c["rpm"],       lw=1.2, label="Engine RPM")
        self.ln_travel,    = self.ax.plot([], [], color=c["travel"],    lw=1.2, label="Wheel Travel")
        self.ln_low,       = self.ax.plot([], [], color=c["low"],       lw=2.2, ls="--", label="Out: Low freq")
        self.ln_high,      = self.ax.plot([], [], color=c["high"],      lw=2.2, ls="--", label="Out: High freq")

        self.ax.legend(loc="upper right", facecolor="#111111", edgecolor="#444", labelcolor="white", fontsize=8, ncol=2)

        self.canvas = FigureCanvasTkAgg(fig, master=parent_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas.draw_idle()

    def update(
        self,
        t: List[float],
        abs_data, tc_data, over_data, und_data,
        over_rev_data=None, under_rev_data=None, rpm_data=None, travel_data=None,
        low_data=None, high_data=None,
        skip_draw=False
    ):
        self.ln_abs.set_data(t, abs_data)
        self.ln_tc.set_data(t, tc_data)
        self.ln_over.set_data(t, over_data)
        self.ln_und.set_data(t, und_data)
        if over_rev_data is not None: self.ln_over_rev.set_data(t, over_rev_data)
        if under_rev_data is not None: self.ln_under_rev.set_data(t, under_rev_data)
        if rpm_data is not None: self.ln_rpm.set_data(t, rpm_data)
        if travel_data is not None: self.ln_travel.set_data(t, travel_data)
        if low_data is not None: self.ln_low.set_data(t, low_data)
        if high_data is not None: self.ln_high.set_data(t, high_data)
        if t:
            self.ax.set_xlim(t[0], t[-1])
        if not skip_draw:
            self.canvas.draw_idle()


class EffectCurveChart:
    """Manages full detailed response curve preview chart for an effect tuning tab."""

    def __init__(self, parent_frame: ctk.CTkFrame, state):
        import matplotlib
        matplotlib.use("TkAgg")
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure

        self.state = state
        fig = Figure(figsize=(5, 3.6), dpi=96, facecolor="#111111")
        fig.subplots_adjust(left=0.12, right=0.97, top=0.88, bottom=0.14)
        self.ax = fig.add_subplot(111)
        ChartStyling.apply_dark(self.ax, "Response Curve", "Raw slip input", "Motor output")
        self.ax.set_xlim(0, 1)
        self.ax.set_ylim(0, 1.05)

        xs = [x / 200.0 for x in range(201)]
        self.dead_span = self.ax.axvspan(0, state.threshold, alpha=0.12, color="#ffffff")
        self.tl, = self.ax.plot([state.threshold] * 2, [0, 1], color="#ffffff", lw=1, ls=":", alpha=0.4)
        self.th, = self.ax.plot([state.threshold] * 2, [0, 1], color="#ffffff", lw=1, ls=":", alpha=0.4)
        self.ll, = self.ax.plot(xs, state.low_curve(xs), color="#ff3366", lw=2.2, label="Low freq (Rumble)")
        self.lh, = self.ax.plot(xs, state.high_curve(xs), color="#00ff88", lw=2.2, label="High freq (Buzz)")
        self.ax.legend(loc="upper left", facecolor="#111111", edgecolor="#333", labelcolor="white", fontsize=8)

        self.cursor, = self.ax.plot([-1, -1], [0, 1], color="#f39c12", lw=1.5, ls="-", alpha=0.9, zorder=5)
        self.dot_low, = self.ax.plot([], [], "o", color="#ff3366", ms=8, zorder=6)
        self.dot_high, = self.ax.plot([], [], "o", color="#00ff88", ms=8, zorder=6)

        self.canvas = FigureCanvasTkAgg(fig, master=parent_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=4)
        self.canvas.draw_idle()

    def redraw_curve(self):
        xs = [x / 200.0 for x in range(201)]
        thr = self.state.threshold
        self.ll.set_ydata(self.state.low_curve(xs))
        self.lh.set_ydata(self.state.high_curve(xs))
        self.tl.set_xdata([thr, thr])
        self.th.set_xdata([thr, thr])
        self.dead_span.remove()
        self.dead_span = self.ax.axvspan(0, thr, alpha=0.12, color="#ffffff")
        self.canvas.draw_idle()

    def update_cursor(self, input_val: float, out_low: float, out_high: float, skip_draw=False):
        self.cursor.set_xdata([input_val, input_val])
        self.dot_low.set_data([input_val], [out_low])
        self.dot_high.set_data([input_val], [out_high])
        if not skip_draw:
            self.canvas.draw_idle()


class MiniEffectChart:
    """Manages small dashboard 2x2 response curve preview chart."""

    def __init__(self, parent_frame: ctk.CTkFrame, state):
        import matplotlib
        matplotlib.use("TkAgg")
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure

        self.state = state
        fig = Figure(figsize=(3.8, 2.2), dpi=88, facecolor="#0d0d0d")
        fig.subplots_adjust(left=0.10, right=0.97, top=0.92, bottom=0.16)
        self.ax = fig.add_subplot(111)
        self.ax.set_facecolor("#080808")
        self.ax.tick_params(colors="#555555", labelsize=7)
        for sp in self.ax.spines.values():
            sp.set_color("#222222")
        self.ax.set_xlim(0, 1)
        self.ax.set_ylim(0, 1.05)
        self.ax.set_xlabel("Input", color="#555555", fontsize=7)
        self.ax.set_ylabel("Output", color="#555555", fontsize=7)
        self.ax.grid(True, color="#111111", linestyle="--", linewidth=0.5)

        xs = [x / 200.0 for x in range(201)]
        self.dead_span = self.ax.axvspan(0, state.threshold, alpha=0.10, color="#ffffff")
        self.ll, = self.ax.plot(xs, state.low_curve(xs), color="#ff3366", lw=1.8, label="Low")
        self.lh, = self.ax.plot(xs, state.high_curve(xs), color="#00ff88", lw=1.8, label="High")
        self.ax.legend(loc="upper left", facecolor="#0d0d0d", edgecolor="#222", labelcolor="white", fontsize=6, handlelength=1.2)

        self.cursor, = self.ax.plot([-1, -1], [0, 1], color="#f39c12", lw=1.2, ls="-", alpha=0.8, zorder=5)
        self.dot_low, = self.ax.plot([], [], "o", color="#ff3366", ms=6, zorder=6)
        self.dot_high, = self.ax.plot([], [], "o", color="#00ff88", ms=6, zorder=6)

        self.canvas = FigureCanvasTkAgg(fig, master=parent_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=2, pady=2)
        self.canvas.draw_idle()

    def redraw_curve(self):
        xs = [x / 200.0 for x in range(201)]
        self.ll.set_ydata(self.state.low_curve(xs))
        self.lh.set_ydata(self.state.high_curve(xs))
        for coll in self.ax.collections[:]:
            coll.remove()
        self.dead_span = self.ax.axvspan(0, self.state.threshold, alpha=0.10, color="#ffffff")
        self.canvas.draw_idle()

    def update_cursor(self, input_val: float, out_low: float, out_high: float, skip_draw=False):
        self.cursor.set_xdata([input_val, input_val])
        self.dot_low.set_data([input_val], [out_low])
        self.dot_high.set_data([input_val], [out_high])
        if not skip_draw:
            self.canvas.draw_idle()
