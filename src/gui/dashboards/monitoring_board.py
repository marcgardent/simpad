"""
monitoringBoard — Dedicated Native Windows OS HUD Overlay Dashboard.
Creates a native, frameless, Always-On-Top, semi-transparent OS window positioned at
Top-Middle third of the primary monitor (X=Width/3, Y=0, W=Width/3, H=Height/3).
"""

import sys
import tkinter as tk
from tkinter import ttk
from src.gui.dashboards.base import BaseDashboard
from src.telemetry.sensors import VehicleSensors
from src.utils.window_utils import get_screen_dimensions


class MonitoringBoard(BaseDashboard):
    """
    Tableau de bord HUD 'monitoringBoard' sous forme de vraie fenêtre système Windows (HWND).
    Positionné de manière fixe dans le tiers haut / milieu de l'écran (grille 3x3 : col=1, row=0).
    """

    def __init__(self):
        super().__init__(name="monitoringBoard")
        self.root: tk.Tk | None = None
        self._lbl_gear = None
        self._lbl_rpm_text = None
        self._bar_rpm = None
        self._bar_abs = None
        self._bar_tc = None
        self._bar_over = None
        self._bar_travel = None

    def build_ui(self) -> None:
        if self.root is not None:
            return

        try:
            self.root = tk.Tk()
            self.root.title("monitoringBoard")

            # Configuration fenêtre OS native : sans bordure, Always-On-Top, semi-transparente
            self.root.overrideredirect(True)
            self.root.attributes("-topmost", True)
            try:
                self.root.attributes("-alpha", 0.88)
            except Exception:
                pass

            self.root.configure(bg="#121216")

            # Calcul du rectangle grille 3x3 : col=1 (milieu), row=0 (haut)
            sw, sh = get_screen_dimensions()
            w = max(360, sw // 3)
            h = max(220, sh // 3)
            x = (sw - w) // 2
            y = 0
            self.root.geometry(f"{w}x{h}+{x}+{y}")

            # Style ttk sombre
            style = ttk.Style()
            style.theme_use("clam")
            style.configure("TProgressbar", thickness=14, troughcolor="#1c1c23", background="#00d2ff")
            style.configure("Abs.Horizontal.TProgressbar", thickness=14, troughcolor="#1c1c23", background="#e74c3c")
            style.configure("Tc.Horizontal.TProgressbar", thickness=14, troughcolor="#1c1c23", background="#ff9900")
            style.configure("Over.Horizontal.TProgressbar", thickness=14, troughcolor="#1c1c23", background="#a569bd")
            style.configure("Curb.Horizontal.TProgressbar", thickness=14, troughcolor="#1c1c23", background="#2ecc71")

            # En-tête HUD
            header_frame = tk.Frame(self.root, bg="#121216")
            header_frame.pack(fill="x", px=10, py=6)

            lbl_brand = tk.Label(header_frame, text="SIMPAD ", fg="#00d2ff", bg="#121216", font=("Segoe UI", 11, "bold"))
            lbl_brand.pack(side="left")

            lbl_title = tk.Label(header_frame, text="MONITORING BOARD", fg="#ffc800", bg="#121216", font=("Segoe UI", 11, "bold"))
            lbl_title.pack(side="left")

            lbl_gear_hdr = tk.Label(header_frame, text="  GEAR: ", fg="#b4b4b4", bg="#121216", font=("Segoe UI", 10))
            lbl_gear_hdr.pack(side="left")

            self._lbl_gear = tk.Label(header_frame, text="N", fg="#2ecc71", bg="#121216", font=("Segoe UI", 14, "bold"))
            self._lbl_gear.pack(side="left")

            # Séparateur lumineux
            sep = tk.Frame(self.root, bg="#00d2ff", height=2)
            sep.pack(fill="x", px=8, py=2)

            # Contenu principal
            main_frame = tk.Frame(self.root, bg="#121216")
            main_frame.pack(fill="both", expand=True, px=10, py=4)

            # Barre RPM
            rpm_frame = tk.Frame(main_frame, bg="#121216")
            rpm_frame.pack(fill="x", py=2)

            self._lbl_rpm_text = tk.Label(rpm_frame, text="RPM: 0 / 7500", fg="#b4b4b4", bg="#121216", font=("Segoe UI", 9))
            self._lbl_rpm_text.pack(anchor="w")

            self._bar_rpm = ttk.Progressbar(rpm_frame, orient="horizontal", mode="determinate", maximum=100)
            self._bar_rpm.pack(fill="x", py=2)

            # Grille 2 colonnes (Braking & Dynamics)
            cols_frame = tk.Frame(main_frame, bg="#121216")
            cols_frame.pack(fill="both", expand=True, py=4)

            # Colonne 1 : Freinage (ABS) & Motricité (TC)
            col1 = tk.Frame(cols_frame, bg="#18181c", bd=1, relief="solid")
            col1.pack(side="left", fill="both", expand=True, px=4, py=2)

            tk.Label(col1, text="FREINAGE & MOTRICITÉ", fg="#00d2ff", bg="#18181c", font=("Segoe UI", 9, "bold")).pack(anchor="w", px=4, py=2)
            tk.Label(col1, text="ABS (Blocage):", fg="#b4b4b4", bg="#18181c", font=("Segoe UI", 8)).pack(anchor="w", px=4)
            self._bar_abs = ttk.Progressbar(col1, orient="horizontal", mode="determinate", maximum=100, style="Abs.Horizontal.TProgressbar")
            self._bar_abs.pack(fill="x", px=4, py=2)

            tk.Label(col1, text="TC (Patinage):", fg="#b4b4b4", bg="#18181c", font=("Segoe UI", 8)).pack(anchor="w", px=4)
            self._bar_tc = ttk.Progressbar(col1, orient="horizontal", mode="determinate", maximum=100, style="Tc.Horizontal.TProgressbar")
            self._bar_tc.pack(fill="x", px=4, py=2)

            # Colonne 2 : Dynamique & Châssis
            col2 = tk.Frame(cols_frame, bg="#18181c", bd=1, relief="solid")
            col2.pack(side="right", fill="both", expand=True, px=4, py=2)

            tk.Label(col2, text="DYNAMIQUE & VIBREURS", fg="#00d2ff", bg="#18181c", font=("Segoe UI", 9, "bold")).pack(anchor="w", px=4, py=2)
            tk.Label(col2, text="Sur-Virage (Over):", fg="#b4b4b4", bg="#18181c", font=("Segoe UI", 8)).pack(anchor="w", px=4)
            self._bar_over = ttk.Progressbar(col2, orient="horizontal", mode="determinate", maximum=100, style="Over.Horizontal.TProgressbar")
            self._bar_over.pack(fill="x", px=4, py=2)

            tk.Label(col2, text="Vibreurs (Curbs):", fg="#b4b4b4", bg="#18181c", font=("Segoe UI", 8)).pack(anchor="w", px=4)
            self._bar_travel = ttk.Progressbar(col2, orient="horizontal", mode="determinate", maximum=100, style="Curb.Horizontal.TProgressbar")
            self._bar_travel.pack(fill="x", px=4, py=2)

            # Masquer initialement la fenêtre
            self.root.withdraw()
            self._visible = False
        except Exception as e:
            print(f"[MonitoringBoard] Error building native OS window: {e}", flush=True)

    def show(self) -> None:
        if self.root is not None:
            try:
                self.root.deiconify()
                self.root.lift()
                self.root.attributes("-topmost", True)
                self.root.update()
                self._visible = True
            except Exception as e:
                print(f"[MonitoringBoard] Error showing window: {e}", flush=True)

    def hide(self) -> None:
        if self.root is not None:
            try:
                self.root.withdraw()
                self._visible = False
            except Exception as e:
                print(f"[MonitoringBoard] Error hiding window: {e}", flush=True)

    def update_telemetry(self, sensors: VehicleSensors) -> None:
        if self.root is None or not self._visible:
            return

        try:
            # Rapport engagé
            gear_str = "R" if sensors.gear == -1 else ("N" if sensors.gear == 0 else str(sensors.gear))
            if self._lbl_gear:
                self._lbl_gear.config(text=gear_str)

            # RPM
            rpm_ratio = min(1.0, max(0.0, sensors.rpm_ratio))
            current_rpm = int(rpm_ratio * sensors.engine_max_rpm)
            if self._lbl_rpm_text:
                self._lbl_rpm_text.config(text=f"RPM: {current_rpm} / {int(sensors.engine_max_rpm)}")
            if self._bar_rpm:
                self._bar_rpm["value"] = rpm_ratio * 100

            # Signaux
            if self._bar_abs:
                self._bar_abs["value"] = min(100, max(0, sensors.lock_intensity * 100))

            if self._bar_tc:
                self._bar_tc["value"] = min(100, max(0, sensors.spin_intensity * 100))

            if self._bar_over:
                self._bar_over["value"] = min(100, max(0, sensors.oversteer_intensity * 100))

            if self._bar_travel:
                self._bar_travel["value"] = min(100, max(0, sensors.travel_intensity * 100))

            self.root.update_idletasks()
            self.root.update()
        except Exception:
            pass
