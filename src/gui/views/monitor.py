"""
SimPad GUI Views — MonitorTab component.
Single Responsibility: Monitor tab skeleton container for real-time telemetry chart.
"""

import customtkinter as ctk


class MonitorTab:
    """Renders the Monitor tab view containing the live telemetry chart container."""

    def __init__(self, parent_tab: ctk.CTkFrame):
        self.parent = parent_tab

        self.chart_frame = ctk.CTkFrame(self.parent)
        self.chart_frame.pack(fill="both", expand=True, padx=6, pady=6)

        self.placeholder = ctk.CTkLabel(
            self.chart_frame,
            text="⏳  Loading chart…",
            font=ctk.CTkFont(size=14),
            text_color="#666666",
        )
        self.placeholder.pack(expand=True)
