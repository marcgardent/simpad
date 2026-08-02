"""
SimPad GUI Views — ProfileBar component.
Single Responsibility: Profile selection dropdown and action buttons header.
"""

import customtkinter as ctk
from typing import Callable, List


class ProfileBar(ctk.CTkFrame):
    """Persistent top bar for profile selection and management."""

    def __init__(
        self,
        parent: ctk.CTk,
        profile_names: List[str],
        current_profile: str,
        on_select: Callable[[str], None],
        on_save: Callable[[], None],
        on_new: Callable[[], None],
        on_rename: Callable[[], None],
        on_copy: Callable[[], None],
        on_delete: Callable[[], None],
    ):
        super().__init__(parent, fg_color="#141414", corner_radius=0, height=52)
        self.pack(fill="x", padx=0, pady=0)
        self.pack_propagate(False)

        # Label
        ctk.CTkLabel(
            self,
            text="Profile:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#aaaaaa",
        ).pack(side="left", padx=(14, 6), pady=14)

        # OptionMenu Dropdown
        self.profile_var = ctk.StringVar(value=current_profile)
        self.profile_menu = ctk.CTkOptionMenu(
            self,
            variable=self.profile_var,
            values=profile_names,
            width=200,
            command=on_select,
            font=ctk.CTkFont(size=12),
        )
        self.profile_menu.pack(side="left", padx=(0, 8), pady=10)

        # Unsaved indicator
        self.lbl_unsaved = ctk.CTkLabel(
            self, text="●", text_color="#f39c12", font=ctk.CTkFont(size=16)
        )
        self.lbl_unsaved.pack(side="left", padx=(0, 12))
        self.lbl_unsaved.configure(text=" ")

        # Buttons
        btn_cfg = dict(height=32, width=90, font=ctk.CTkFont(size=11))
        ctk.CTkButton(self, text="💾  Save", command=on_save, **btn_cfg).pack(
            side="left", padx=4, pady=10
        )
        ctk.CTkButton(self, text="➕  New", command=on_new, **btn_cfg).pack(
            side="left", padx=4, pady=10
        )
        ctk.CTkButton(self, text="✏️  Rename", command=on_rename, **btn_cfg).pack(
            side="left", padx=4, pady=10
        )
        ctk.CTkButton(self, text="📋  Copy", command=on_copy, **btn_cfg).pack(
            side="left", padx=4, pady=10
        )
        ctk.CTkButton(
            self,
            text="🗑  Delete",
            command=on_delete,
            fg_color="#5d1a1a",
            hover_color="#7b241c",
            **btn_cfg,
        ).pack(side="left", padx=4, pady=10)

    def refresh(self, names: List[str], select: str = None):
        self.profile_menu.configure(values=names)
        if select and select in names:
            self.profile_var.set(select)

    def set_unsaved(self, unsaved: bool):
        self.lbl_unsaved.configure(text="●" if unsaved else " ")
