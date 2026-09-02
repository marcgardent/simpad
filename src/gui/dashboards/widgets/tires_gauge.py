"""
Tires Gauge Widget — Physical 4-Tire Life & Slip Representation for Compact HUD canvas.
Displays:
- Left Tires (FL on top, RL on bottom) placed immediately to the right of the Brake gauge.
- Right Tires (FR on top, RR on bottom) placed immediately to the left of the Throttle gauge.

Physical Color Coding:
- Wheel Lockup / Over-Braking: Purple (#c084fc pastel -> #581c87 deep dark)
- Wheel Slip / Spin / Lateral Scrub: Cyan (#a5f3fc pastel -> #0e7490 deep dark)
- Neutral Grip: Dark stealth tire tread (#131822)
"""

from typing import Dict, Any, Tuple
import dearpygui.dearpygui as dpg
from src.gui.dashboards.widgets.base_widget import BaseHudWidget, lerp
from src.telemetry.sensors import VehicleSensors


def get_tire_colors(lock_val: float, slip_val: float) -> Tuple[list, list, str, float]:
    """
    Calcule la couleur de fond, de bordure, le type d'événement et l'intensité
    du pneu selon la physique de contact pneu/route.
    """
    if lock_val > 0.02:
        # Blocage / Freinage critique -> Dégradé VIOLET (Pastel doux vers Foncé profond)
        t = min(1.0, max(0.0, lock_val))
        # Interpolation Pastel (216, 180, 254) -> Foncé (88, 28, 135)
        r = int(216 - t * (216 - 88))
        g = int(180 - t * (180 - 28))
        b = int(254 - t * (254 - 135))
        border_r = min(255, int(r * 1.2 + 30))
        border_g = min(255, int(g * 1.2 + 30))
        border_b = min(255, int(b * 1.2 + 30))
        return [r, g, b, 240], [border_r, border_g, border_b, 255], "LOCK", t

    elif slip_val > 0.02:
        # Glisse / Patinage / Dérive -> Dégradé CYAN (Pastel doux vers Foncé profond)
        t = min(1.0, max(0.0, slip_val))
        # Interpolation Pastel (165, 243, 252) -> Foncé (14, 116, 144)
        r = int(165 - t * (165 - 14))
        g = int(243 - t * (243 - 116))
        b = int(252 - t * (252 - 144))
        border_r = min(255, int(r * 1.2 + 30))
        border_g = min(255, int(g * 1.2 + 30))
        border_b = min(255, int(b * 1.2 + 30))
        return [r, g, b, 240], [border_r, border_g, border_b, 255], "SLIP", t

    else:
        # Pneu neutre au repos (Gomme sombre stylisée)
        return [19, 24, 34, 180], [46, 56, 77, 200], "NONE", 0.0


class TiresGaugeWidget(BaseHudWidget):
    """
    Représentation Physique de la Vie des 4 Pneus.
    - FL & RL disposés verticalement à droite du Frein.
    - FR & RR disposés verticalement à gauche de l'Accélérateur.
    """

    def __init__(self):
        self.disp_fl_lock = 0.0
        self.disp_fr_lock = 0.0
        self.disp_rl_lock = 0.0
        self.disp_rr_lock = 0.0

        self.disp_fl_slip = 0.0
        self.disp_fr_slip = 0.0
        self.disp_rl_slip = 0.0
        self.disp_rr_slip = 0.0

    def draw(
        self,
        drawlist_tag: str,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        # LERP smoothing pour une restitution fluide des 4 roues
        alpha = 0.25
        self.disp_fl_lock = lerp(self.disp_fl_lock, sensors.front_left_lock, alpha)
        self.disp_fr_lock = lerp(self.disp_fr_lock, sensors.front_right_lock, alpha)
        self.disp_rl_lock = lerp(self.disp_rl_lock, sensors.rear_left_lock, alpha)
        self.disp_rr_lock = lerp(self.disp_rr_lock, sensors.rear_right_lock, alpha)

        fl_slip_raw = max(sensors.front_left_spin, sensors.front_left_lat_slip)
        fr_slip_raw = max(sensors.front_right_spin, sensors.front_right_lat_slip)
        rl_slip_raw = max(sensors.rear_left_spin, sensors.rear_left_lat_slip)
        rr_slip_raw = max(sensors.rear_right_spin, sensors.rear_right_lat_slip)

        self.disp_fl_slip = lerp(self.disp_fl_slip, fl_slip_raw, alpha)
        self.disp_fr_slip = lerp(self.disp_fr_slip, fr_slip_raw, alpha)
        self.disp_rl_slip = lerp(self.disp_rl_slip, rl_slip_raw, alpha)
        self.disp_rr_slip = lerp(self.disp_rr_slip, rr_slip_raw, alpha)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        gauge_y = 15.0 * scale_y
        gauge_h = 245.0 * scale_y

        tire_w = 24.0 * scale_x
        tire_gap = 9.0 * scale_y
        tire_h = (gauge_h - tire_gap) / 2.0  # 118.0 * scale_y

        # Positions horizontales :
        # - Pneus Gauche (FL, RL) : immédiatement à droite de la jauge de frein (qui finit à center_x - 220)
        left_tires_x = center_x - (216.0 * scale_x)

        # - Pneus Droite (FR, RR) : immédiatement à gauche de la jauge d'accélérateur (qui commence à center_x + 220)
        right_tires_x = center_x + (192.0 * scale_x)

        front_y = gauge_y
        rear_y = gauge_y + tire_h + tire_gap

        # Liste des 4 pneus (x, y, nom, lock, slip)
        tires_info = [
            (left_tires_x, front_y, "FL", self.disp_fl_lock, self.disp_fl_slip),
            (left_tires_x, rear_y, "RL", self.disp_rl_lock, self.disp_rl_slip),
            (right_tires_x, front_y, "FR", self.disp_fr_lock, self.disp_fr_slip),
            (right_tires_x, rear_y, "RR", self.disp_rr_lock, self.disp_rr_slip),
        ]

        for x, y, label, lock_val, slip_val in tires_info:
            fill_col, border_col, mode, intensity = get_tire_colors(lock_val, slip_val)

            # Corps du pneu (Rectangle aux coins arrondis)
            dpg.draw_rectangle(
                pmin=[x, y],
                pmax=[x + tire_w, y + tire_h],
                fill=fill_col,
                color=border_col,
                thickness=1.5 if intensity > 0.05 else 1.0,
                rounding=4.0 * scale_x,
                parent=drawlist_tag,
            )

            # Rainure de bande de roulement centrale
            groove_x = x + tire_w / 2.0
            dpg.draw_line(
                p1=[groove_x, y + 4.0 * scale_y],
                p2=[groove_x, y + tire_h - 4.0 * scale_y],
                color=[border_col[0], border_col[1], border_col[2], 60 if intensity <= 0.02 else 120],
                thickness=1.0,
                parent=drawlist_tag,
            )

            # Label de la roue (FL, RL, FR, RR)
            text_color = [255, 255, 255, 220] if intensity > 0.05 else [148, 163, 184, 160]
            dpg.draw_text(
                pos=[x + 4.0 * scale_x, y + 4.0 * scale_y],
                text=label,
                color=text_color,
                size=10.0 * scale_x,
                parent=drawlist_tag,
            )

            # Affichage de l'intensité numérique si glisse ou blocage
            if intensity > 0.05:
                pct_str = f"{int(round(intensity * 100))}%"
                dpg.draw_text(
                    pos=[x + 2.0 * scale_x, y + tire_h - 16.0 * scale_y],
                    text=pct_str,
                    color=[255, 255, 255, 255],
                    size=9.0 * scale_x,
                    parent=drawlist_tag,
                )
