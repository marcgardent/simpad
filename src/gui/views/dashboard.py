"""
SimPad GUI Views — DashboardTab component.
Single Responsibility: Dashboard status bar and 2x2 effect card grid layout.
"""

import customtkinter as ctk
from typing import Dict, Any, Callable, List, Optional


class DashboardTab:
    """Renders the Dashboard tab view containing status cards and 2x2 effect grid."""

    def __init__(
        self,
        parent_tab: ctk.CTkFrame,
        effects_def: List[Dict[str, Any]],
        on_toggle_effect: Callable[[str, bool], None],
        on_toggle_telemetry: Optional[Callable[[bool], None]] = None,
    ):
        self.parent = parent_tab
        self.effects_def = effects_def
        self.on_toggle_effect = on_toggle_effect
        self.on_toggle_telemetry = on_toggle_telemetry

        self.cards: Dict[str, ctk.CTkFrame] = {}
        self.enable_vars: Dict[str, ctk.BooleanVar] = {}
        self.placeholders: Dict[str, ctk.CTkLabel] = {}
        self.chart_containers: Dict[str, ctk.CTkFrame] = {}

        self._build_ui()

    def _build_ui(self):
        # ── Status bar ────────────────────────────────────────────────────────
        stat = ctk.CTkFrame(self.parent, fg_color="#141414", corner_radius=10)
        stat.pack(fill="x", padx=10, pady=(10, 8))

        def _status_badge(parent, default_text):
            f = ctk.CTkFrame(parent, fg_color="#1c1c1c", corner_radius=8)
            f.pack(side="left", padx=8, pady=8)
            dot = ctk.CTkLabel(f, text="●", text_color="#e74c3c", font=ctk.CTkFont(size=16))
            dot.pack(side="left", padx=(10, 4))
            lbl = ctk.CTkLabel(f, text=default_text, font=ctk.CTkFont(size=12))
            lbl.pack(side="left", padx=(0, 12))
            return dot, lbl

        self.dot_udp, self.lbl_udp = _status_badge(stat, "UDP LMU:  Waiting…")
        self.dot_pad, self.lbl_pad = _status_badge(stat, "Controller:  Initializing…")

        # Telemetry listener toggle button
        self.telemetry_enabled = True
        self.btn_telemetry = ctk.CTkButton(
            stat,
            text="📡 Listening: ON",
            command=self._on_click_telemetry,
            height=34,
            width=145,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#1f538d",
            hover_color="#2968b2",
        )
        self.btn_telemetry.pack(side="right", padx=12, pady=8)

        # ── 2×2 effect card grid ──────────────────────────────────────────────
        grid = ctk.CTkFrame(self.parent, fg_color="transparent")
        grid.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        grid.rowconfigure(0, weight=1)
        grid.rowconfigure(1, weight=1)

        positions = [(0, 0), (0, 1), (1, 0), (1, 1)]
        for idx, effect in enumerate(self.effects_def):
            eid   = effect["id"]
            color = effect["color"]
            row, col = positions[idx]

            card = ctk.CTkFrame(grid, fg_color="#161616", corner_radius=12)
            card.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")
            card.rowconfigure(1, weight=1)
            card.columnconfigure(0, weight=1)
            self.cards[eid] = card

            # Card header
            hdr = ctk.CTkFrame(card, fg_color="transparent")
            hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))

            ctk.CTkLabel(
                hdr,
                text=effect["label"],
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=color,
            ).pack(side="left")

            sw_var = ctk.BooleanVar(value=True)
            self.enable_vars[eid] = sw_var
            ctk.CTkSwitch(
                hdr,
                text="",
                variable=sw_var,
                width=46,
                command=lambda e=eid, v=sw_var: self.on_toggle_effect(e, v.get()),
                onvalue=True,
                offvalue=False,
            ).pack(side="right")

            # Chart container
            chart_area = ctk.CTkFrame(card, fg_color="#0d0d0d", corner_radius=8)
            chart_area.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
            ph = ctk.CTkLabel(chart_area, text="⏳", font=ctk.CTkFont(size=18), text_color="#333333")
            ph.pack(expand=True)

            self.placeholders[eid] = ph
            self.chart_containers[eid] = chart_area

    def _on_click_telemetry(self):
        self.telemetry_enabled = not self.telemetry_enabled
        if self.telemetry_enabled:
            self.btn_telemetry.configure(text="📡 Listening: ON", fg_color="#1f538d", hover_color="#2968b2")
        else:
            self.btn_telemetry.configure(text="⏸ Listening: OFF", fg_color="#5d1a1a", hover_color="#7b241c")

        if self.on_toggle_telemetry:
            self.on_toggle_telemetry(self.telemetry_enabled)

    def update_udp_status(self, active: bool, packet_count: int):
        if not self.telemetry_enabled:
            self.dot_udp.configure(text_color="#f39c12")
            self.lbl_udp.configure(text="  UDP LMU:  Paused (OFF)")
            return
        if active:
            self.dot_udp.configure(text_color="#2ecc71")
            self.lbl_udp.configure(text=f"  UDP LMU:  ● Live  ({packet_count} packets)")
        else:
            self.dot_udp.configure(text_color="#e74c3c")
            self.lbl_udp.configure(text="  UDP LMU:  Waiting for packets…")

    def update_pad_status(self, is_connected: bool, pad_name: str):
        if is_connected:
            self.dot_pad.configure(text_color="#2ecc71")
            self.lbl_pad.configure(text=f"  Controller:  ✓ {pad_name}")
        else:
            self.dot_pad.configure(text_color="#e74c3c")
            self.lbl_pad.configure(text="  Controller:  No controller detected")
