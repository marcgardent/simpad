"""
SimPad Race Engineer — Onglet Graphique Dear PyGui (IHM).
Permet d'activer/désactiver les rôles, de réordonner les priorités,
de visualiser l'état IDLE/BUSY en temps réel et de monitorer le radar de trafic.
"""

import time
import logging
from typing import Optional, Dict, Any, List
import dearpygui.dearpygui as dpg

from src.engineer.manager import RaceEngineer
from src.engineer.base import BaseRole, RoleStatus
from src.engineer.roles.traffic_spotter import TrafficSpotterRole, TrafficSpotterState
from src.utils.audio import AudioAnnouncer

logger = logging.getLogger(__name__)


class RaceEngineerTab:
    """
    Gestionnaire de l'onglet IHM dédié à l'Ingénieur de Course Virtuel.
    Supporte la configuration dynamique, le tri de priorité par glissement/boutons,
    l'activation unitaire et la visualisation temps réel de la FSM spotter.
    """

    def __init__(self, race_engineer: RaceEngineer):
        self.engineer = race_engineer
        self._last_ui_refresh: float = 0.0
        self._parent_app: Optional[Any] = None

    def build_tab(self, parent_app: Any) -> None:
        """Construit l'interface Dear PyGui dans l'onglet Race Engineer."""
        self._parent_app = parent_app

        # ── 1. Entête & Contrôles Maîtres ────────────────────────────────────
        with dpg.child_window(height=52, border=True):
            with dpg.group(horizontal=True):
                dpg.add_text("Race Engineer Master:", color=[0, 210, 255, 255])
                dpg.add_checkbox(
                    label="Enabled",
                    tag="chk_engineer_master_enabled",
                    default_value=self.engineer.enabled,
                    callback=self._cb_toggle_master_enabled,
                )

                dpg.add_spacer(width=20)
                dpg.add_text("Audio Output:", color=[180, 180, 180, 255])
                dpg.add_checkbox(
                    label="Mute Voice",
                    tag="chk_engineer_mute_voice",
                    default_value=AudioAnnouncer.is_muted(),
                    callback=self._cb_toggle_mute,
                )

                dpg.add_spacer(width=20)
                dpg.add_text("Global Status:", color=[180, 180, 180, 255])
                dpg.add_text("STANDBY (All roles IDLE)", tag="lbl_engineer_global_status", color=[46, 204, 113, 255])

                dpg.add_spacer(width=25)
                dpg.add_button(
                    label="Test Voice",
                    width=100,
                    callback=self._cb_test_voice,
                )
                dpg.add_button(
                    label="Reset Roles",
                    width=100,
                    callback=self._cb_reset_roles,
                )

        dpg.add_spacer(height=6)

        # ── 2. Corps Principal : Liste des Rôles & Radar ─────────────────────
        with dpg.group(horizontal=True):
            # Colonne Gauche : Gestion des Rôles (Priorités & États)
            with dpg.child_window(width=680, height=-1, border=True, tag="child_roles_container"):
                dpg.add_text("Active Roles & Priority Queue (Sortable):", color=[255, 200, 0, 255])
                dpg.add_text("Les rôles supérieurs ont la priorité d'annonce. Utilisez ▲ et ▼ pour réordonner.", color=[150, 150, 150, 255])
                dpg.add_separator()
                dpg.add_spacer(height=6)

                with dpg.group(tag="group_roles_list"):
                    self._render_roles_cards()

            # Colonne Droite : Radar de Trafic & Diagnostic en Direct
            with dpg.child_window(width=-1, height=-1, border=True, tag="child_radar_container"):
                dpg.add_text("Live Spotter Radar & Opponent Tracking:", color=[0, 210, 255, 255])
                dpg.add_text("Surveillance des véhicules proches, delta de vitesse et TTC.", color=[150, 150, 150, 255])
                dpg.add_separator()
                dpg.add_spacer(height=6)

                with dpg.child_window(height=180, border=True, tag="child_spotter_diagnostics"):
                    dpg.add_text("Spotter State Machine Diagnostics:", color=[255, 200, 0, 255])
                    dpg.add_text("FSM State: IDLE", tag="lbl_spotter_fsm_state", color=[46, 204, 113, 255])
                    dpg.add_text("Locked Target: None", tag="lbl_spotter_target", color=[220, 220, 220, 255])
                    dpg.add_text("Live TTC: --", tag="lbl_spotter_ttc", color=[220, 220, 220, 255])
                    dpg.add_text("Relative Distance: --", tag="lbl_spotter_dist", color=[220, 220, 220, 255])
                    dpg.add_text("Speed Delta: --", tag="lbl_spotter_delta_speed", color=[220, 220, 220, 255])

                dpg.add_spacer(height=8)
                dpg.add_text("Opponents on Track (Closest):", color=[255, 200, 0, 255])
                with dpg.table(
                    tag="table_radar_opponents",
                    header_row=True,
                    borders_innerH=True,
                    borders_outerH=True,
                    borders_innerV=True,
                    borders_outerV=True,
                    row_background=True,
                    height=260,
                ):
                    dpg.add_table_column(label="Driver", width_fixed=True, init_width_or_weight=140)
                    dpg.add_table_column(label="Car / Class", width_fixed=True, init_width_or_weight=130)
                    dpg.add_table_column(label="Dist (m)", width_fixed=True, init_width_or_weight=75)
                    dpg.add_table_column(label="Speed", width_fixed=True, init_width_or_weight=75)
                    dpg.add_table_column(label="TTC (s)", width_fixed=True, init_width_or_weight=70)

    def _render_roles_cards(self) -> None:
        """Régénère la liste des cartes de rôles avec leurs boutons de tri et badges."""
        if dpg.does_item_exist("group_roles_list"):
            dpg.delete_item("group_roles_list", children_only=True)

        roles = self.engineer.get_roles()

        for idx, role in enumerate(roles):
            role_id = role.role_id
            card_tag = f"card_role_{role_id}"

            with dpg.child_window(parent="group_roles_list", tag=card_tag, height=130, border=True):
                # Ligne 1 : Boutons UP/DOWN, Priorité, Checkbox Actif, Nom, Badge État
                with dpg.group(horizontal=True):
                    # Bouton UP
                    dpg.add_button(
                        label="▲",
                        width=26,
                        user_data=role_id,
                        callback=self._cb_move_role_up,
                        enabled=(idx > 0),
                    )
                    # Bouton DOWN
                    dpg.add_button(
                        label="▼",
                        width=26,
                        user_data=role_id,
                        callback=self._cb_move_role_down,
                        enabled=(idx < len(roles) - 1),
                    )

                    # Priorité
                    prio_color = [255, 200, 0, 255] if role.priority >= 100 else [180, 180, 180, 255]
                    dpg.add_text(f"[{role.priority:3d}]", tag=f"lbl_prio_{role_id}", color=prio_color)

                    # Checkbox activation
                    dpg.add_checkbox(
                        label="",
                        tag=f"chk_role_{role_id}",
                        default_value=role.enabled,
                        user_data=role_id,
                        callback=self._cb_toggle_role,
                    )

                    # Nom du rôle
                    name_color = [0, 210, 255, 255] if role.enabled else [120, 120, 120, 255]
                    dpg.add_text(f"{role.name}", tag=f"lbl_name_{role_id}", color=name_color)

                    dpg.add_spacer(width=10)
                    # Badge d'état IDLE / BUSY
                    status_str = "BUSY" if role.is_busy() else "IDLE"
                    status_col = [243, 156, 18, 255] if role.is_busy() else [46, 204, 113, 255]
                    dpg.add_text(f"[ {status_str} ]", tag=f"lbl_status_badge_{role_id}", color=status_col)

                # Ligne 2 : Description
                dpg.add_text(f"{role.description}", color=[140, 140, 140, 255], wrap=640)

                dpg.add_spacer(height=2)
                # Ligne 3 : Détails en direct & Test sonore
                with dpg.group(horizontal=True):
                    dpg.add_text("Live: ", color=[180, 180, 180, 255])
                    dpg.add_text("Ready", tag=f"lbl_live_detail_{role_id}", color=[220, 220, 220, 255])

                    dpg.add_spacer(width=20)
                    dpg.add_button(
                        label="Test Audio",
                        width=85,
                        user_data=role_id,
                        callback=self._cb_test_role_audio,
                    )

            dpg.add_spacer(parent="group_roles_list", height=4)

    # ── Callbacks Utilisateur ────────────────────────────────────────────────
    def _cb_toggle_master_enabled(self, sender, app_data):
        self.engineer.enabled = bool(app_data)
        logger.info(f"[RaceEngineer GUI] Master switch: {self.engineer.enabled}")

    def _cb_toggle_mute(self, sender, app_data):
        AudioAnnouncer.set_muted(bool(app_data))
        logger.info(f"[RaceEngineer GUI] Audio Mute: {AudioAnnouncer.is_muted()}")

    def _cb_toggle_role(self, sender, app_data, user_data):
        role_id = user_data
        self.engineer.set_role_enabled(role_id, bool(app_data))
        if dpg.does_item_exist(f"lbl_name_{role_id}"):
            col = [0, 210, 255, 255] if app_data else [120, 120, 120, 255]
            dpg.configure_item(f"lbl_name_{role_id}", color=col)

    def _cb_move_role_up(self, sender, app_data, user_data):
        role_id = user_data
        if self.engineer.move_role_up(role_id):
            self._render_roles_cards()

    def _cb_move_role_down(self, sender, app_data, user_data):
        role_id = user_data
        if self.engineer.move_role_down(role_id):
            self._render_roles_cards()

    def _cb_test_voice(self, sender, app_data):
        AudioAnnouncer.play_phrase("clean_lap")

    def _cb_reset_roles(self, sender, app_data):
        self.engineer.reset_all()

    def _cb_test_role_audio(self, sender, app_data, user_data):
        role_id = user_data
        if role_id == "lap_validity":
            AudioAnnouncer.play_clean_lap()
        elif role_id == "traffic_spotter":
            AudioAnnouncer.play_alongside()
        elif role_id == "traffic_jam":
            AudioAnnouncer.play_car()
        else:
            AudioAnnouncer.play_phrase("lap")

    # ── Rafraîchissement Périodique (Tick UI) ────────────────────────────────
    def render_tick(self) -> None:
        """Met à jour les badges de statut et les indicateurs dynamiques."""
        now = time.time()
        if (now - self._last_ui_refresh) < 0.08:  # ~12 FPS pour l'UI de statut
            return
        self._last_ui_refresh = now

        # 1. Statut global
        any_busy = self.engineer.is_any_role_busy()
        if dpg.does_item_exist("lbl_engineer_global_status"):
            if not self.engineer.enabled:
                dpg.set_value("lbl_engineer_global_status", "DISABLED (Master switch off)")
                dpg.configure_item("lbl_engineer_global_status", color=[231, 76, 60, 255])
            elif any_busy:
                busy_names = ", ".join(r.name for r in self.engineer.get_busy_roles())
                dpg.set_value("lbl_engineer_global_status", f"ENGAGED ({busy_names})")
                dpg.configure_item("lbl_engineer_global_status", color=[243, 156, 18, 255])
            else:
                dpg.set_value("lbl_engineer_global_status", "STANDBY (All roles IDLE)")
                dpg.configure_item("lbl_engineer_global_status", color=[46, 204, 113, 255])

        # 2. Statut unitaire des rôles
        for role in self.engineer.get_roles():
            role_id = role.role_id
            badge_tag = f"lbl_status_badge_{role_id}"
            detail_tag = f"lbl_live_detail_{role_id}"

            if dpg.does_item_exist(badge_tag):
                is_busy = role.is_busy()
                badge_str = "BUSY" if is_busy else "IDLE"
                badge_col = [243, 156, 18, 255] if is_busy else [46, 204, 113, 255]
                dpg.set_value(badge_tag, f"[ {badge_str} ]")
                dpg.configure_item(badge_tag, color=badge_col)

            if dpg.does_item_exist(detail_tag):
                summary = role.get_state_summary()
                detail_text = self._format_role_summary(role_id, summary)
                dpg.set_value(detail_tag, detail_text)

        # 3. Diagnostic Spotter FSM & Radar
        self._update_radar_ui()

    def _format_role_summary(self, role_id: str, summary: Dict[str, Any]) -> str:
        """Formate une ligne de texte concise pour le détail du rôle."""
        if role_id == "traffic_spotter":
            state = summary.get("fsm_state", "IDLE")
            if state != "IDLE":
                target = summary.get("target_driver", "Opponent")
                ttc = summary.get("live_ttc_str", "--")
                dist = summary.get("live_distance_str", "--")
                delta = summary.get("live_speed_delta_str", "--")
                return f"[{state}] Target: {target} | TTC: {ttc} | Dist: {dist} | Delta: {delta}"
            return "IDLE — Track clear behind"

        elif role_id == "lap_validity":
            flag_text = summary.get("lap_status_text", "Ready")
            last_ev = summary.get("last_event", "None")
            return f"Current Lap: {flag_text} | Last Event: {last_ev}"

        elif role_id == "traffic_jam":
            slow_info = summary.get("slow_car_info", "Clear ahead")
            return f"Track Ahead: {slow_info}"

        return str(summary.get("status", "IDLE"))

    def _update_radar_ui(self) -> None:
        """Met à jour le panneau de diagnostic et la table radar des adversaires."""
        traffic_role: Optional[TrafficSpotterRole] = None
        for r in self.engineer.get_roles():
            if isinstance(r, TrafficSpotterRole):
                traffic_role = r
                break

        if traffic_role:
            summ = traffic_role.get_state_summary()
            if dpg.does_item_exist("lbl_spotter_fsm_state"):
                fsm_st = summ.get("fsm_state", "IDLE")
                fsm_col = [46, 204, 113, 255] if fsm_st == "IDLE" else [243, 156, 18, 255]
                dpg.set_value("lbl_spotter_fsm_state", f"FSM State: {fsm_st}")
                dpg.configure_item("lbl_spotter_fsm_state", color=fsm_col)

            if dpg.does_item_exist("lbl_spotter_target"):
                target = summ.get("target_driver", "None")
                car = summ.get("target_car", "")
                dpg.set_value("lbl_spotter_target", f"Locked Target: {target} ({car})")

            if dpg.does_item_exist("lbl_spotter_ttc"):
                dpg.set_value("lbl_spotter_ttc", f"Live TTC: {summ.get('live_ttc_str', '--')}")

            if dpg.does_item_exist("lbl_spotter_dist"):
                dpg.set_value("lbl_spotter_dist", f"Relative Distance: {summ.get('live_distance_str', '--')}")

            if dpg.does_item_exist("lbl_spotter_delta_speed"):
                dpg.set_value("lbl_spotter_delta_speed", f"Speed Delta: {summ.get('live_speed_delta_str', '--')}")
