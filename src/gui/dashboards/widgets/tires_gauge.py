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
    Représentation Physique Tri-Axiale Complète des 4 Pneus :
    - Section HAUTE (CCCC) : Jauge Verticale Cyan (Over-Acceleration / Motricité ⬆️)
    - Section MÉDIANE (LLRR) : Jauge Horizontale Jaune (Dérive Latérale Gauche/Droite ⬅️ ➡️ / Sous-virage & Survirage)
    - Section BASSE (BBBB) : Jauge Verticale Violette (Over-Braking / Blocage de frein ⬇️)
    """

    def __init__(self):
        self.disp_fl_lock = 0.0
        self.disp_fr_lock = 0.0
        self.disp_rl_lock = 0.0
        self.disp_rr_lock = 0.0

        self.disp_fl_spin = 0.0
        self.disp_fr_spin = 0.0
        self.disp_rl_spin = 0.0
        self.disp_rr_spin = 0.0

        self.disp_fl_lat = 0.0
        self.disp_fr_lat = 0.0
        self.disp_rl_lat = 0.0
        self.disp_rr_lat = 0.0

        self.disp_fl_lat_s = 0.0
        self.disp_fr_lat_s = 0.0
        self.disp_rl_lat_s = 0.0
        self.disp_rr_lat_s = 0.0

    def draw(
        self,
        drawlist_tag: str,
        canvas_w: float,
        canvas_h: float,
        sensors: VehicleSensors,
        extra_data: Dict[str, Any],
    ) -> None:
        alpha = 0.25
        # 1. Longitudinal Lock (Over-Braking)
        self.disp_fl_lock = lerp(self.disp_fl_lock, sensors.front_left_lock, alpha)
        self.disp_fr_lock = lerp(self.disp_fr_lock, sensors.front_right_lock, alpha)
        self.disp_rl_lock = lerp(self.disp_rl_lock, sensors.rear_left_lock, alpha)
        self.disp_rr_lock = lerp(self.disp_rr_lock, sensors.rear_right_lock, alpha)

        # 2. Longitudinal Spin (Over-Acceleration)
        self.disp_fl_spin = lerp(self.disp_fl_spin, sensors.front_left_spin, alpha)
        self.disp_fr_spin = lerp(self.disp_fr_spin, sensors.front_right_spin, alpha)
        self.disp_rl_spin = lerp(self.disp_rl_spin, sensors.rear_left_spin, alpha)
        self.disp_rr_spin = lerp(self.disp_rr_spin, sensors.rear_right_spin, alpha)

        # 3. Lateral Scrub (Magnitude)
        self.disp_fl_lat = lerp(self.disp_fl_lat, sensors.front_left_lat_slip, alpha)
        self.disp_fr_lat = lerp(self.disp_fr_lat, sensors.front_right_lat_slip, alpha)
        self.disp_rl_lat = lerp(self.disp_rl_lat, sensors.rear_left_lat_slip, alpha)
        self.disp_rr_lat = lerp(self.disp_rr_lat, sensors.rear_right_lat_slip, alpha)

        # 4. Lateral Scrub Signed (Left -1.0 to Right +1.0)
        self.disp_fl_lat_s = lerp(self.disp_fl_lat_s, getattr(sensors, "front_left_lat_signed", 0.0), alpha)
        self.disp_fr_lat_s = lerp(self.disp_fr_lat_s, getattr(sensors, "front_right_lat_signed", 0.0), alpha)
        self.disp_rl_lat_s = lerp(self.disp_rl_lat_s, getattr(sensors, "rear_left_lat_signed", 0.0), alpha)
        self.disp_rr_lat_s = lerp(self.disp_rr_lat_s, getattr(sensors, "rear_right_lat_signed", 0.0), alpha)

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        # Proportions réalistes de pneu de course (ratio largeur/hauteur ~ 1:1.85)
        tire_w = 40.0 * scale_x
        tire_h = 74.0 * scale_y

        # Alignement :
        # - Pneus Avant (FL, FR) : Alignés vers le HAUT (y = 15px)
        front_y = 15.0 * scale_y

        # - Pneus Arrière (RL, RR) : Alignés vers le BAS (se termine à 236px, avec 14px de marge au-dessus de l'aéro à 250px)
        rear_bot_y = 236.0 * scale_y
        rear_y = rear_bot_y - tire_h  # 162.0 * scale_y

        # Positions horizontales (à côté des jauges de frein et d'accélérateur)
        left_tires_x = center_x - (215.0 * scale_x)
        right_tires_x = center_x + (175.0 * scale_x)

        # Liste des 4 pneus (x, y, label, lock, spin, lat_mag, lat_signed)
        tires_info = [
            (left_tires_x, front_y, "FL", self.disp_fl_lock, self.disp_fl_spin, self.disp_fl_lat, self.disp_fl_lat_s),
            (left_tires_x, rear_y, "RL", self.disp_rl_lock, self.disp_rl_spin, self.disp_rl_lat, self.disp_rl_lat_s),
            (right_tires_x, front_y, "FR", self.disp_fr_lock, self.disp_fr_spin, self.disp_fr_lat, self.disp_fr_lat_s),
            (right_tires_x, rear_y, "RR", self.disp_rr_lock, self.disp_rr_spin, self.disp_rr_lat, self.disp_rr_lat_s),
        ]

        # Découpage proportionnel interne : ccccccc (3) / LLL|RRR (2) / bbbbbbb (3)
        header_h = 12.0 * scale_y
        gap_y = 2.0 * scale_y
        vert_h = 21.0 * scale_y   # Jauges verticales CCCC et BBBB
        lat_h = 14.0 * scale_y    # Jauge médiane horizontale LLL|RRR

        for x, y, label, lock_val, spin_val, lat_val, lat_s in tires_info:
            # 1. Conteneur externe du pneu
            dpg.draw_rectangle(
                pmin=[x, y],
                pmax=[x + tire_w, y + tire_h],
                fill=[19, 24, 34, 220],
                color=[46, 56, 77, 240],
                thickness=1.0,
                rounding=4.0 * scale_x,
                parent=drawlist_tag,
            )

            # En-tête label roue
            dpg.draw_text(
                pos=[x + 4.0 * scale_x, y + 2.0 * scale_y],
                text=label,
                color=[255, 255, 255, 220],
                size=9.0 * scale_x,
                parent=drawlist_tag,
            )

            # ── SECTION 1 (CCCC) : Jauge Verticale Cyan (Over-Acceleration ⬆️) ──
            c_top = y + header_h + gap_y
            dpg.draw_rectangle(
                pmin=[x + 2.0 * scale_x, c_top],
                pmax=[x + tire_w - 2.0 * scale_x, c_top + vert_h],
                fill=[15, 20, 30, 180],
                color=[40, 50, 70, 150],
                thickness=0.8,
                rounding=2.0 * scale_x,
                parent=drawlist_tag,
            )
            if spin_val > 0.02:
                c_fill = max(2.0 * scale_y, vert_h * min(1.0, spin_val))
                c_fill_y = c_top + vert_h - c_fill
                dpg.draw_rectangle(
                    pmin=[x + 2.5 * scale_x, c_fill_y],
                    pmax=[x + tire_w - 2.5 * scale_x, c_top + vert_h],
                    fill=[0, 220, 255, 220],
                    color=[56, 189, 248, 255],
                    thickness=0.8,
                    rounding=1.5 * scale_x,
                    parent=drawlist_tag,
                )
                dpg.draw_line(
                    p1=[x + 3.0 * scale_x, c_fill_y],
                    p2=[x + tire_w - 3.0 * scale_x, c_fill_y],
                    color=[255, 255, 255, 240],
                    thickness=1.0,
                    parent=drawlist_tag,
                )

            # ── SECTION 2 (LLRR) : Jauge Horizontale Jaune avec Flèche (⬅️ ➡️) ──
            l_top = c_top + vert_h + gap_y
            dpg.draw_rectangle(
                pmin=[x + 2.0 * scale_x, l_top],
                pmax=[x + tire_w - 2.0 * scale_x, l_top + lat_h],
                fill=[15, 20, 30, 200],
                color=[50, 60, 80, 180],
                thickness=0.8,
                rounding=2.0 * scale_x,
                parent=drawlist_tag,
            )
            mid_x = x + tire_w / 2.0
            half_w = (tire_w - 7.0 * scale_x) / 2.0

            # Séparateur central net entre Gauche et Droite
            dpg.draw_line(
                p1=[mid_x, l_top + 1.0 * scale_y],
                p2=[mid_x, l_top + lat_h - 1.0 * scale_y],
                color=[148, 163, 184, 255],
                thickness=1.5,
                parent=drawlist_tag,
            )

            # Flèche directionnelle selon le sens de glisse
            if abs(lat_s) > 0.02:
                bar_w = max(4.0 * scale_x, half_w * min(1.0, abs(lat_s)))
                head_w = min(bar_w, 5.0 * scale_x)

                if lat_s < 0:  # Glisse vers la Gauche (◄ Flèche pointant à gauche)
                    tip_x = mid_x - 1.0 * scale_x - bar_w
                    base_x = tip_x + head_w

                    # Corps rectangulaire
                    if bar_w > head_w:
                        dpg.draw_rectangle(
                            pmin=[base_x, l_top + 3.0 * scale_y],
                            pmax=[mid_x - 1.0 * scale_x, l_top + lat_h - 3.0 * scale_y],
                            fill=[250, 204, 21, 220],
                            color=[234, 179, 8, 255],
                            thickness=0.8,
                            parent=drawlist_tag,
                        )
                    # Tête triangulaire
                    dpg.draw_triangle(
                        p1=[tip_x, l_top + lat_h / 2.0],
                        p2=[base_x, l_top + 1.5 * scale_y],
                        p3=[base_x, l_top + lat_h - 1.5 * scale_y],
                        fill=[250, 204, 21, 240],
                        color=[255, 255, 255, 240],
                        thickness=1.0,
                        parent=drawlist_tag,
                    )
                else:  # Glisse vers la Droite (► Flèche pointant à droite)
                    tip_x = mid_x + 1.0 * scale_x + bar_w
                    base_x = tip_x - head_w

                    # Corps rectangulaire
                    if bar_w > head_w:
                        dpg.draw_rectangle(
                            pmin=[mid_x + 1.0 * scale_x, l_top + 3.0 * scale_y],
                            pmax=[base_x, l_top + lat_h - 3.0 * scale_y],
                            fill=[250, 204, 21, 220],
                            color=[234, 179, 8, 255],
                            thickness=0.8,
                            parent=drawlist_tag,
                        )
                    # Tête triangulaire
                    dpg.draw_triangle(
                        p1=[tip_x, l_top + lat_h / 2.0],
                        p2=[base_x, l_top + 1.5 * scale_y],
                        p3=[base_x, l_top + lat_h - 1.5 * scale_y],
                        fill=[250, 204, 21, 240],
                        color=[255, 255, 255, 240],
                        thickness=1.0,
                        parent=drawlist_tag,
                    )
            elif lat_val > 0.02:  # Fallback si amplitude non signée
                bar_w = max(3.0 * scale_x, half_w * min(1.0, lat_val))
                dpg.draw_rectangle(
                    pmin=[mid_x - bar_w / 2.0, l_top + 2.0 * scale_y],
                    pmax=[mid_x + bar_w / 2.0, l_top + lat_h - 2.0 * scale_y],
                    fill=[250, 204, 21, 220],
                    color=[234, 179, 8, 255],
                    thickness=0.8,
                    rounding=1.5 * scale_x,
                    parent=drawlist_tag,
                )

            # ── SECTION 3 (BBBB) : Jauge Verticale Violette (Over-Braking ⬇️) ──
            b_top = l_top + lat_h + gap_y
            dpg.draw_rectangle(
                pmin=[x + 2.0 * scale_x, b_top],
                pmax=[x + tire_w - 2.0 * scale_x, b_top + vert_h],
                fill=[15, 20, 30, 180],
                color=[40, 50, 70, 150],
                thickness=0.8,
                rounding=2.0 * scale_x,
                parent=drawlist_tag,
            )
            if lock_val > 0.02:
                b_fill = max(2.0 * scale_y, vert_h * min(1.0, lock_val))
                b_fill_bot = b_top + b_fill
                dpg.draw_rectangle(
                    pmin=[x + 2.5 * scale_x, b_top],
                    pmax=[x + tire_w - 2.5 * scale_x, b_fill_bot],
                    fill=[168, 85, 247, 220],
                    color=[192, 132, 252, 255],
                    thickness=0.8,
                    rounding=1.5 * scale_x,
                    parent=drawlist_tag,
                )
                dpg.draw_line(
                    p1=[x + 3.0 * scale_x, b_fill_bot],
                    p2=[x + tire_w - 3.0 * scale_x, b_fill_bot],
                    color=[255, 255, 255, 240],
                    thickness=1.0,
                    parent=drawlist_tag,
                )
