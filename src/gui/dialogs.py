"""
SimPad GUI — Dialogs module.
Single Responsibility: Reusable custom modal dialogs.
"""

import customtkinter as ctk
from typing import Callable, Optional


class InputModalDialog:
    """Displays a sleek, dark-themed modal overlay inside a parent CustomTkinter container."""

    def __init__(
        self,
        parent: ctk.CTk,
        title: str,
        subtitle: str,
        default_text: str,
        action_label: str,
        on_submit: Callable[[str], Optional[str]],
    ):
        self.parent = parent
        self.on_submit = on_submit

        # Dimmed background overlay
        self.overlay = ctk.CTkFrame(parent, fg_color="#0a0a0c", corner_radius=0)
        self.overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

        # Centered modal card
        self.card = ctk.CTkFrame(
            self.overlay,
            fg_color="#18181c",
            corner_radius=16,
            border_width=1,
            border_color="#2e2e38",
        )
        self.card.place(relx=0.5, rely=0.45, anchor="center", width=440, height=260)

        # Header title & subtitle
        ctk.CTkLabel(
            self.card,
            text=title,
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#ffffff",
        ).pack(pady=(22, 2))

        ctk.CTkLabel(
            self.card,
            text=subtitle,
            font=ctk.CTkFont(size=12),
            text_color="#888899",
        ).pack(pady=(0, 14))

        # Input field
        self.entry_var = ctk.StringVar(value=default_text)
        self.entry = ctk.CTkEntry(
            self.card,
            textvariable=self.entry_var,
            width=350,
            height=42,
            font=ctk.CTkFont(size=13),
            fg_color="#101014",
            border_color="#3b3b4d",
            corner_radius=8,
        )
        self.entry.pack(pady=(0, 4))
        self.entry.focus_set()
        self.entry.select_range(0, "end")

        # Error feedback label
        self.lbl_err = ctk.CTkLabel(
            self.card, text="", font=ctk.CTkFont(size=11), text_color="#ff5555"
        )
        self.lbl_err.pack(pady=(0, 10))

        # Key bindings
        self.entry.bind("<Return>", self._handle_submit)
        self.entry.bind("<Escape>", lambda e: self.close())

        # Buttons
        btn_row = ctk.CTkFrame(self.card, fg_color="transparent")
        btn_row.pack(pady=(0, 18))

        ctk.CTkButton(
            btn_row,
            text="Cancel",
            command=self.close,
            width=110,
            height=36,
            fg_color="#282832",
            hover_color="#383845",
            text_color="#cccccc",
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            btn_row,
            text=action_label,
            command=self._handle_submit,
            width=150,
            height=36,
            fg_color="#1f538d",
            hover_color="#2968b2",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="left", padx=8)

    def _handle_submit(self, event=None):
        val = self.entry_var.get().strip()
        err = self.on_submit(val)
        if err:
            self.lbl_err.configure(text=f"⚠️  {err}")
        else:
            self.close()

    def close(self):
        self.overlay.destroy()
