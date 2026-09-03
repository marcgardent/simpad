"""
SimPad Telemetry & Annotation Studio — Onglet Graphique Dear PyGui (IHM).
Visualisation de la télémétrie mètre par mètre (vitesse, frein, accélérateur, volant),
gestion interactive des annotations de pilotage (Brake 'B', Turn-in 'I', Virages 'T', Gear '1'..'8'),
déplacement par Drag & Drop, navigation par curseur (clic / flèches clavier) et suppression ('Suppr').
Architecture SOLID.
"""

import time
import math
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import dearpygui.dearpygui as dpg

from src.telemetry.reference_profile import (
    ReferenceLapProfile,
    TrackAnnotation,
    AnnotationType,
    DEFAULT_REF_LAPS_DIR,
    clean_name_identifier,
)
from src.telemetry.lmu_parser import LMUParser
from src.utils.audio import AudioAnnouncer

logger = logging.getLogger(__name__)


class TelemetryTab:
    """
    Onglet Télémétrie & Annotations de Piste (Telemetry Studio).
    Affiche les courbes spatiales mètre par mètre et permet l'édition interactive des marqueurs.
    """

    def __init__(self):
        self._profile: Optional[ReferenceLapProfile] = None
        self._cursor_distance: float = 0.0
        self._selected_annotation_id: Optional[str] = None
        self._parent_app: Optional[Any] = None
        self._last_loaded_file: Optional[Path] = None
        self._annotation_drag_tags: Dict[str, str] = {}
        self._available_files: List[Path] = []
        self._last_ui_tick: float = 0.0
        self._last_car_pos_tick: float = 0.0
        self._last_known_car_dist: Optional[float] = None
        self._car_track_matches: bool = False

    def build_tab(self, parent_app: Any) -> None:
        """Construit l'interface utilisateur dans l'onglet Telemetry & Annotations."""
        self._parent_app = parent_app

        # ── 1. Barre d'outils supérieure : Profil, Chargement, Sauvegarde ─────
        with dpg.child_window(height=54, border=True, tag="child_telem_toolbar"):
            with dpg.group(horizontal=True):
                dpg.add_text("Reference Lap Profile:", color=[0, 210, 255, 255])

                # Combo de sélection du fichier de profil
                dpg.add_combo(
                    items=["(Live Session Reference Lap)"],
                    default_value="(Live Session Reference Lap)",
                    tag="combo_ref_profile_files",
                    width=280,
                    callback=self._cb_select_profile_file,
                )

                dpg.add_button(
                    label="Refresh Files",
                    width=100,
                    callback=self._cb_refresh_profiles_list,
                )

                dpg.add_spacer(width=10)
                dpg.add_text("Auto-Save Marks: ON (.marks.json)", color=[46, 204, 113, 255])

                dpg.add_spacer(width=15)
                dpg.add_text("Lap Time:", color=[180, 180, 180, 255])
                dpg.add_text("--", tag="lbl_telem_lap_time", color=[46, 204, 113, 255])

                dpg.add_spacer(width=15)
                dpg.add_text("Track Length:", color=[180, 180, 180, 255])
                dpg.add_text("--", tag="lbl_telem_track_len", color=[241, 196, 15, 255])

                dpg.add_spacer(width=15)
                dpg.add_text("S1 Loop:", color=[180, 180, 180, 255])
                dpg.add_text("--", tag="lbl_telem_s1_loop", color=[0, 210, 255, 255])

                dpg.add_spacer(width=15)
                dpg.add_text("S2 Loop:", color=[180, 180, 180, 255])
                dpg.add_text("--", tag="lbl_telem_s2_loop", color=[180, 100, 255, 255])

                dpg.add_spacer(width=15)
                dpg.add_text("Markers:", color=[180, 180, 180, 255])
                dpg.add_text("0", tag="lbl_telem_num_markers", color=[255, 200, 0, 255])

        dpg.add_spacer(height=4)

        # ── 2. Barre d'actions rapides et raccourcis clavier ──────────────────
        with dpg.child_window(height=46, border=True, tag="child_telem_shortcuts"):
            with dpg.group(horizontal=True):
                dpg.add_text("Add Marker at Cursor:", color=[255, 200, 0, 255])

                dpg.add_button(
                    label="+ Brake [B]",
                    width=105,
                    tag="btn_add_brake",
                    callback=lambda: self.add_annotation_at_cursor(AnnotationType.BRAKE),
                )
                dpg.add_button(
                    label="+ Turn-in [I]",
                    width=115,
                    tag="btn_add_turn_in",
                    callback=lambda: self.add_annotation_at_cursor(AnnotationType.TURN_IN),
                )
                dpg.add_button(
                    label="+ Turn (Auto T1..30) [T]",
                    width=190,
                    tag="btn_add_turn",
                    callback=lambda: self.add_annotation_at_cursor(AnnotationType.TURN),
                )

                # Sélecteur de rapport Gear
                dpg.add_combo(
                    items=["1", "2", "3", "4", "5", "6", "7", "8"],
                    default_value="3",
                    tag="combo_gear_select",
                    width=45,
                )
                dpg.add_button(
                    label="+ Gear [1-8]",
                    width=100,
                    tag="btn_add_gear",
                    callback=self._cb_add_gear_from_combo,
                )

                dpg.add_spacer(width=15)
                dpg.add_button(
                    label="Delete Marker [Suppr]",
                    width=165,
                    tag="btn_delete_marker",
                    callback=self._cb_delete_selected_or_nearest,
                )
                dpg.add_button(
                    label="Test Audio",
                    width=90,
                    tag="btn_test_marker_audio",
                    callback=self._cb_test_selected_audio,
                )
                dpg.add_spacer(width=10)
                dpg.add_button(
                    label="Sync to Car [C]",
                    width=135,
                    tag="btn_sync_to_car",
                    callback=self._cb_sync_cursor_to_car,
                )

        dpg.add_spacer(height=4)

        # ── 3. Corps Principal : Graphique Mètre par Mètre & Panneau Latéral ───
        with dpg.group(horizontal=True):
            # Colonne Gauche : Grand Graphique Spatial (Télémétrie Mètre par Mètre)
            with dpg.child_window(width=-360, height=-1, border=True, tag="child_plot_container"):
                with dpg.group(horizontal=True):
                    dpg.add_text("Spatial Telemetry Profile (1m Resolution):", color=[0, 210, 255, 255])
                    dpg.add_spacer(width=15)
                    dpg.add_text("Cursor:", color=[180, 180, 180, 255])
                    dpg.add_text("0.0 m", tag="lbl_hud_cursor_dist", color=[255, 255, 255, 255])
                    dpg.add_text("| Sector:", color=[180, 180, 180, 255])
                    dpg.add_text("S1", tag="lbl_hud_cursor_sector", color=[0, 210, 255, 255])
                    dpg.add_text("| Live Car:", color=[180, 180, 180, 255])
                    dpg.add_text("--", tag="lbl_hud_live_car_dist", color=[0, 220, 255, 255])
                    dpg.add_text("| Speed:", color=[180, 180, 180, 255])
                    dpg.add_text("0.0 km/h", tag="lbl_hud_cursor_speed", color=[241, 196, 15, 255])
                    dpg.add_text("| Gear:", color=[180, 180, 180, 255])
                    dpg.add_text("N", tag="lbl_hud_cursor_gear", color=[46, 204, 113, 255])
                    dpg.add_text("| Thr:", color=[180, 180, 180, 255])
                    dpg.add_text("0 %", tag="lbl_hud_cursor_thr", color=[46, 204, 113, 255])
                    dpg.add_text("| Brk:", color=[180, 180, 180, 255])
                    dpg.add_text("0 %", tag="lbl_hud_cursor_brk", color=[231, 76, 60, 255])
                    dpg.add_text("| Steer:", color=[180, 180, 180, 255])
                    dpg.add_text("0.0 %", tag="lbl_hud_cursor_steer", color=[0, 210, 255, 255])

                # Graphique DPG Spatial
                with dpg.plot(
                    no_title=True,
                    height=-1,
                    width=-1,
                    tag="plot_telemetry_studio",
                    crosshairs=True,
                    query=False,
                ):
                    dpg.add_plot_legend()
                    dpg.add_plot_axis(dpg.mvXAxis, label="Track Distance (m)", tag="axis_telem_dist")

                    # Axe Y Principal (Gauche) : Vitesse (km/h) & Pédales (0-100%)
                    with dpg.plot_axis(dpg.mvYAxis, label="Speed (km/h) / Inputs (%)", tag="axis_telem_y_inputs"):
                        dpg.set_axis_limits("axis_telem_y_inputs", -105, 360)

                        # Zones de fond colorées par secteur (affichées quand S1/S2 sont enregistrés)
                        dpg.add_shade_series([], [], y2=[], label="Sector 1", tag="shade_telem_s1", show=False)
                        dpg.add_shade_series([], [], y2=[], label="Sector 2", tag="shade_telem_s2", show=False)
                        dpg.add_shade_series([], [], y2=[], label="Sector 3", tag="shade_telem_s3", show=False)

                        dpg.add_line_series([], [], label="Speed (km/h)", tag="series_telem_speed")
                        dpg.add_line_series([], [], label="Throttle (%)", tag="series_telem_throttle")
                        dpg.add_line_series([], [], label="Brake (%)", tag="series_telem_brake")
                        dpg.add_line_series([], [], label="Steering (%)", tag="series_telem_steering")

                    # Axe Y Secondaire (Droite) : Rapports de boîte Gear (N, 1..8)
                    with dpg.plot_axis(dpg.mvYAxis2, label="Gear", tag="axis_telem_y_gear"):
                        dpg.set_axis_limits("axis_telem_y_gear", 0, 8.5)
                        dpg.set_axis_ticks("axis_telem_y_gear", (('N', 0), ('1', 1), ('2', 2), ('3', 3), ('4', 4), ('5', 5), ('6', 6), ('7', 7), ('8', 8)))
                        dpg.add_stair_series([], [], label="Gear", tag="series_telem_gear")

                    # Marqueurs de boucle de chrono Secteur 1 et Secteur 2
                    dpg.add_drag_line(
                        label="S1 Loop",
                        tag="dragline_telem_s1_loop",
                        vertical=True,
                        default_value=-999.0,
                        color=[0, 210, 255, 230],
                        thickness=2.0,
                        show=False,
                    )
                    dpg.add_drag_line(
                        label="S2 Loop",
                        tag="dragline_telem_s2_loop",
                        vertical=True,
                        default_value=-999.0,
                        color=[180, 100, 255, 230],
                        thickness=2.0,
                        show=False,
                    )

                    # Ligne verticale interactive pour le curseur blanc d'édition
                    dpg.add_drag_line(
                        label="Cursor",
                        tag="dragline_telem_cursor",
                        vertical=True,
                        default_value=0.0,
                        color=[255, 255, 255, 255],
                        thickness=2.0,
                        callback=self._cb_cursor_dragged,
                    )

                    # Ligne verticale pour la dernière position connue de la voiture (Live Car)
                    dpg.add_drag_line(
                        label="Live Car",
                        tag="dragline_telem_live_car",
                        vertical=True,
                        default_value=-999.0,
                        color=[0, 220, 255, 255],
                        thickness=2.5,
                        show=False,
                    )

            # Colonne Droite : Table & Édition des Marqueurs
            with dpg.child_window(width=-1, height=-1, border=True, tag="child_markers_table_container"):
                dpg.add_text("Track Annotations & Pace Notes:", color=[255, 200, 0, 255])
                dpg.add_text("CTRL + Clic / Glisser sur le tracé pour déplacer le curseur.\nGlisser-déposer directement les repères colorés.", color=[180, 180, 180, 255])
                dpg.add_separator()
                dpg.add_spacer(height=4)

                with dpg.table(
                    tag="table_telem_annotations",
                    header_row=True,
                    borders_innerH=True,
                    borders_outerH=True,
                    borders_innerV=True,
                    borders_outerV=True,
                    row_background=True,
                    resizable=True,
                    scrollX=True,
                    scrollY=True,
                    height=-1,
                ):
                    dpg.add_table_column(label="Type", width_fixed=True, init_width_or_weight=65)
                    dpg.add_table_column(label="Label", width_fixed=True, init_width_or_weight=75)
                    dpg.add_table_column(label="Dist (m)", width_fixed=True, init_width_or_weight=70)
                    dpg.add_table_column(label="Audio", width_fixed=True, init_width_or_weight=65)
                    dpg.add_table_column(label="Action", width_fixed=True, init_width_or_weight=65)

        # Thèmes de fond pour les zones de secteurs S1, S2, S3
        if not dpg.does_item_exist("theme_telem_shade_s1"):
            with dpg.theme(tag="theme_telem_shade_s1"):
                with dpg.theme_component(dpg.mvShadeSeries):
                    dpg.add_theme_color(dpg.mvPlotCol_Fill, (0, 180, 255, 30), category=dpg.mvThemeCat_Plots)
                    dpg.add_theme_color(dpg.mvPlotCol_Line, (0, 0, 0, 0), category=dpg.mvThemeCat_Plots)

        if not dpg.does_item_exist("theme_telem_shade_s2"):
            with dpg.theme(tag="theme_telem_shade_s2"):
                with dpg.theme_component(dpg.mvShadeSeries):
                    dpg.add_theme_color(dpg.mvPlotCol_Fill, (175, 95, 245, 30), category=dpg.mvThemeCat_Plots)
                    dpg.add_theme_color(dpg.mvPlotCol_Line, (0, 0, 0, 0), category=dpg.mvThemeCat_Plots)

        if not dpg.does_item_exist("theme_telem_shade_s3"):
            with dpg.theme(tag="theme_telem_shade_s3"):
                with dpg.theme_component(dpg.mvShadeSeries):
                    dpg.add_theme_color(dpg.mvPlotCol_Fill, (255, 175, 0, 25), category=dpg.mvThemeCat_Plots)
                    dpg.add_theme_color(dpg.mvPlotCol_Line, (0, 0, 0, 0), category=dpg.mvThemeCat_Plots)

        if dpg.does_item_exist("shade_telem_s1") and dpg.does_item_exist("theme_telem_shade_s1"):
            dpg.bind_item_theme("shade_telem_s1", "theme_telem_shade_s1")
        if dpg.does_item_exist("shade_telem_s2") and dpg.does_item_exist("theme_telem_shade_s2"):
            dpg.bind_item_theme("shade_telem_s2", "theme_telem_shade_s2")
        if dpg.does_item_exist("shade_telem_s3") and dpg.does_item_exist("theme_telem_shade_s3"):
            dpg.bind_item_theme("shade_telem_s3", "theme_telem_shade_s3")

        # Enregistrement des gestionnaires d'événements clavier et souris
        self._setup_key_and_mouse_handlers()

        # Rafraîchissement initial des profils
        self._refresh_profiles_list()
        self._load_active_profile()

    def _setup_key_and_mouse_handlers(self) -> None:
        """Configure les raccourcis clavier et les clics souris dans Dear PyGui."""
        # 1. Gestionnaire de clic et glisser directement sur le graphique DPG
        if dpg.does_item_exist("plot_telemetry_studio"):
            if not dpg.does_item_exist("handler_telem_plot_click"):
                with dpg.item_handler_registry(tag="handler_telem_plot_click"):
                    dpg.add_item_clicked_handler(
                        button=dpg.mvMouseButton_Left,
                        callback=self._cb_plot_clicked,
                    )
                    dpg.add_item_active_handler(
                        callback=self._cb_plot_active,
                    )
            dpg.bind_item_handler_registry("plot_telemetry_studio", "handler_telem_plot_click")

        # 2. Gestionnaires de touches globales
        with dpg.handler_registry():
            # Raccourci B : Frein
            dpg.add_key_release_handler(
                key=dpg.mvKey_B,
                callback=lambda: self.add_annotation_at_cursor(AnnotationType.BRAKE),
            )
            # Raccourci I : Turn-In
            dpg.add_key_release_handler(
                key=dpg.mvKey_I,
                callback=lambda: self.add_annotation_at_cursor(AnnotationType.TURN_IN),
            )
            # Raccourci T : Turn (T1..T30)
            dpg.add_key_release_handler(
                key=dpg.mvKey_T,
                callback=lambda: self.add_annotation_at_cursor(AnnotationType.TURN),
            )
            # Raccourci Suppr / Backspace : Supprimer le marqueur sélectionné ou le plus proche
            dpg.add_key_release_handler(
                key=dpg.mvKey_Delete,
                callback=self._cb_delete_selected_or_nearest,
            )
            dpg.add_key_release_handler(
                key=dpg.mvKey_Back,
                callback=self._cb_delete_selected_or_nearest,
            )

            # Raccourcis numériques 1 à 8 pour les rapports de boîte
            for gear_num in range(1, 9):
                key_code = getattr(dpg, f"mvKey_{gear_num}", None)
                numpad_code = getattr(dpg, f"mvKey_NumPad{gear_num}", None)
                if key_code is not None:
                    dpg.add_key_release_handler(
                        key=key_code,
                        user_data=gear_num,
                        callback=lambda s, a, u: self.add_annotation_at_cursor(AnnotationType.GEAR, gear=u),
                    )
                if numpad_code is not None:
                    dpg.add_key_release_handler(
                        key=numpad_code,
                        user_data=gear_num,
                        callback=lambda s, a, u: self.add_annotation_at_cursor(AnnotationType.GEAR, gear=u),
                    )

            # Raccourci C : Synchroniser le curseur d'édition sur la position de la voiture
            dpg.add_key_release_handler(
                key=dpg.mvKey_C,
                callback=self._cb_sync_cursor_to_car,
            )

            # Flèches de navigation pour déplacer le curseur
            dpg.add_key_down_handler(
                key=dpg.mvKey_Left,
                callback=self._cb_arrow_left,
            )
            dpg.add_key_down_handler(
                key=dpg.mvKey_Right,
                callback=self._cb_arrow_right,
            )

    # ── Gestion du Curseur et de la Navigation ────────────────────────────────
    def set_cursor_distance(self, distance: float) -> None:
        """Définit la position du curseur en mètres et met à jour le tracé et les readouts."""
        max_dist = self._get_max_track_dist()
        self._cursor_distance = max(0.0, min(max_dist, distance))

        if dpg.does_item_exist("dragline_telem_cursor"):
            dpg.set_value("dragline_telem_cursor", self._cursor_distance)

        self._update_cursor_hud_readouts()

    def _get_max_track_dist(self) -> float:
        """Retourne la distance maximale de la piste."""
        if self._profile:
            if self._profile.track_length > 0:
                return self._profile.track_length
            if self._profile.num_points > 0:
                return float(self._profile.num_points * self._profile.spatial_step)
        return 10000.0

    def _update_cursor_hud_readouts(self) -> None:
        """Met à jour les afficheurs numériques de télémétrie à la position du curseur."""
        d_val = self._cursor_distance
        if dpg.does_item_exist("lbl_hud_cursor_dist"):
            dpg.set_value("lbl_hud_cursor_dist", f"{d_val:.1f} m")

        if dpg.does_item_exist("lbl_hud_cursor_sector"):
            if self._profile:
                sec_num = self._profile.get_sector_at_dist(d_val)
                sec_str = f"S{sec_num}"
                sec_color = [0, 210, 255, 255] if sec_num == 1 else ([180, 100, 255, 255] if sec_num == 2 else [241, 196, 15, 255])
                dpg.set_value("lbl_hud_cursor_sector", sec_str)
                dpg.configure_item("lbl_hud_cursor_sector", color=sec_color)
            else:
                dpg.set_value("lbl_hud_cursor_sector", "S1")

        if self._profile:
            vals = self._profile.get_value_at_dist(d_val)
            if dpg.does_item_exist("lbl_hud_cursor_speed"):
                dpg.set_value("lbl_hud_cursor_speed", f"{vals['speed_kmh']:.1f} km/h")
            if dpg.does_item_exist("lbl_hud_cursor_gear"):
                g = int(vals.get("gear", 0))
                gear_str = "R" if g == -1 else ("N" if g == 0 else str(g))
                dpg.set_value("lbl_hud_cursor_gear", gear_str)
            if dpg.does_item_exist("lbl_hud_cursor_thr"):
                dpg.set_value("lbl_hud_cursor_thr", f"{vals['throttle'] * 100.0:.0f} %")
            if dpg.does_item_exist("lbl_hud_cursor_brk"):
                dpg.set_value("lbl_hud_cursor_brk", f"{vals['brake'] * 100.0:.0f} %")
            if dpg.does_item_exist("lbl_hud_cursor_steer"):
                dpg.set_value("lbl_hud_cursor_steer", f"{vals['steering'] * 100.0:.1f} %")

    def _is_ctrl_down(self) -> bool:
        """Vérifie si la touche CTRL (gauche ou droite) est enfoncée."""
        try:
            return dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
        except Exception:
            return False

    def _cb_cursor_dragged(self, sender, app_data, user_data):
        """Callback appelé lors du glissement manuel de la ligne blanche de curseur."""
        val = app_data
        if val is None and sender and dpg.does_item_exist(sender):
            val = dpg.get_value(sender)
        if val is not None:
            self.set_cursor_distance(float(val))

    def _cb_plot_clicked(self, sender=None, app_data=None, user_data=None):
        """Déplace le curseur au CTRL + Clic gauche dans le graphique."""
        if not self._is_ctrl_down():
            return
        try:
            mouse_pos = dpg.get_plot_mouse_pos()
            if mouse_pos and len(mouse_pos) >= 1:
                self.set_cursor_distance(float(mouse_pos[0]))
        except Exception as e:
            logger.debug(f"[TelemetryTab] Plot click error: {e}")

    def _cb_plot_active(self, sender=None, app_data=None, user_data=None):
        """Déplace le curseur en direct au CTRL + Clic-Glisser dans le graphique."""
        if not self._is_ctrl_down():
            return
        try:
            if dpg.is_mouse_button_down(dpg.mvMouseButton_Left):
                mouse_pos = dpg.get_plot_mouse_pos()
                if mouse_pos and len(mouse_pos) >= 1:
                    self.set_cursor_distance(float(mouse_pos[0]))
        except Exception as e:
            logger.debug(f"[TelemetryTab] Plot active drag error: {e}")

    def _cb_arrow_left(self, sender=None, app_data=None, user_data=None):
        """Déplace le curseur vers la gauche (-1m)."""
        self.set_cursor_distance(self._cursor_distance - 1.0)

    def _cb_arrow_right(self, sender=None, app_data=None, user_data=None):
        """Déplace le curseur vers la droite (+1m)."""
        self.set_cursor_distance(self._cursor_distance + 1.0)

    def _cb_sync_cursor_to_car(self, sender=None, app_data=None, user_data=None):
        """Place le curseur blanc d'édition exactement sur la position active/dernière connue de la voiture."""
        if self._last_known_car_dist is not None and self._car_track_matches:
            self.set_cursor_distance(self._last_known_car_dist)

    def _sync_profile_to_engine(self) -> None:
        """Synchronise immédiatement le profil actif avec DeltaEngine et RaceEngineer (PaceNotesRole)."""
        if not self._profile:
            return

        # 1. Mettre à jour DeltaEngine
        delta_eng = getattr(LMUParser, "_delta_engine", None)
        if delta_eng:
            delta_eng.set_reference_profile(self._profile)

        # 2. Mettre à jour et réinitialiser PaceNotesRole de l'ingénieur
        if self._parent_app and hasattr(self._parent_app, "_race_engineer") and self._parent_app._race_engineer:
            pace_role = self._parent_app._race_engineer.get_role("pace_notes")
            if pace_role and hasattr(pace_role, "set_reference_profile"):
                pace_role.set_reference_profile(self._profile)

    # ── Ajout & Manipulation des Annotations ─────────────────────────────────
    def add_annotation_at_cursor(
        self,
        ann_type: AnnotationType,
        gear: Optional[int] = None,
        label: Optional[str] = None,
    ) -> Optional[TrackAnnotation]:
        """Ajoute une annotation à la position courante du curseur et la sauvegarde."""
        if not self._profile:
            # Créer un profil par défaut temporaire si absent
            self._profile = ReferenceLapProfile(
                track_name="Active Session Track",
                track_length=max(1000.0, self._cursor_distance + 500.0),
            )

        ann = self._profile.add_annotation(
            ann_type=ann_type,
            distance=self._cursor_distance,
            gear=gear,
            label=label,
            auto_save=True,
        )
        self._selected_annotation_id = ann.id

        # Mettre à jour l'IHM
        self._render_markers_on_plot()
        self._render_markers_table()
        self._update_header_stats()

        # Synchroniser immédiatement avec le DeltaEngine et le RaceEngineer
        self._sync_profile_to_engine()

        # Prononcer immédiatement le repère pour feedback audio utilisateur
        phrase = self._profile.get_annotation_phrase_key(ann)
        AudioAnnouncer.play_phrase(phrase)

        return ann

    def _cb_add_gear_from_combo(self, sender=None, app_data=None):
        """Ajoute un marqueur de vitesse selon la valeur sélectionnée dans le combo."""
        val_str = dpg.get_value("combo_gear_select") if dpg.does_item_exist("combo_gear_select") else "3"
        try:
            g_num = int(val_str)
        except ValueError:
            g_num = 3
        self.add_annotation_at_cursor(AnnotationType.GEAR, gear=g_num)

    def _cb_marker_dragged(self, sender, app_data, user_data):
        """Callback déclenché lors du glisser-déposer (Drag & Drop) d'une ligne d'annotation."""
        ann_id = user_data
        if not self._profile:
            return

        val = app_data
        if val is None and sender and dpg.does_item_exist(sender):
            val = dpg.get_value(sender)

        if val is None:
            return

        new_dist = float(val)
        max_dist = self._get_max_track_dist()
        new_dist = max(0.0, min(max_dist, new_dist))

        # Met à jour la distance et sauvegarde automatiquement dans .marks.json
        self._profile.move_annotation(ann_id, new_dist, auto_save=True)
        self._selected_annotation_id = ann_id
        self._cursor_distance = new_dist

        # Recalculer les numéros de virages et actualiser la table et les labels
        self._update_marker_drag_line_labels()
        self._render_markers_table()
        self._update_cursor_hud_readouts()

        # Synchroniser immédiatement avec le Race Engineer
        self._sync_profile_to_engine()

    def _cb_delete_selected_or_nearest(self, sender=None, app_data=None, user_data=None):
        """Supprime le marqueur sélectionné ou le plus proche du curseur."""
        if not self._profile or not self._profile.annotations:
            return

        target_id = self._selected_annotation_id
        if not target_id:
            # Recherche du marqueur le plus proche du curseur (à moins de 25m)
            closest_ann = None
            min_dist = 25.0
            for a in self._profile.annotations:
                d = abs(a.distance - self._cursor_distance)
                if d < min_dist:
                    min_dist = d
                    closest_ann = a
            if closest_ann:
                target_id = closest_ann.id

        if target_id:
            self._profile.remove_annotation(target_id, auto_save=True)
            self._selected_annotation_id = None
            self._render_markers_on_plot()
            self._render_markers_table()
            self._update_header_stats()
            self._sync_profile_to_engine()

    def _cb_test_selected_audio(self, sender=None, app_data=None):
        """Joue le son de l'annotation actuellement sélectionnée ou la plus proche."""
        if not self._profile or not self._profile.annotations:
            return
        target_ann = None
        for a in self._profile.annotations:
            if a.id == self._selected_annotation_id:
                target_ann = a
                break
        if not target_ann and self._profile.annotations:
            target_ann = self._profile.annotations[0]

        if target_ann:
            phrase = self._profile.get_annotation_phrase_key(target_ann)
            AudioAnnouncer.play_phrase(phrase)

    # ── Rendu Visuel : Lignes Drag & Drop sur le Graphique ────────────────────
    def _get_marker_color(self, ann: TrackAnnotation) -> List[int]:
        """Retourne la couleur distinctive selon le type d'annotation."""
        if ann.color:
            return ann.color
        if ann.type == AnnotationType.BRAKE:
            return [231, 76, 60, 255]      # Rouge vif
        elif ann.type == AnnotationType.TURN_IN:
            return [241, 196, 15, 255]     # Jaune doré
        elif ann.type == AnnotationType.TURN:
            return [230, 126, 34, 255]     # Orange
        elif ann.type == AnnotationType.GEAR:
            return [46, 204, 113, 255]     # Vert émeraude
        return [200, 200, 200, 255]

    def _render_markers_on_plot(self) -> None:
        """Recrée toutes les lignes interactives (drag lines) sur le graphique DPG."""
        if not dpg.does_item_exist("plot_telemetry_studio"):
            return

        # 1. Rendu des repères de boucles de chronométrage Secteur 1 et Secteur 2
        s1_dist = self._profile.sector_1_dist if self._profile else 0.0
        s2_dist = self._profile.sector_2_dist if self._profile else 0.0

        if dpg.does_item_exist("dragline_telem_s1_loop"):
            if s1_dist > 0.0:
                t1_str = f" ({self._profile.sector_1_time:.2f}s)" if (self._profile and self._profile.sector_1_time > 0.0) else ""
                dpg.configure_item(
                    "dragline_telem_s1_loop",
                    show=True,
                    default_value=s1_dist,
                    label=f"S1 Loop ({s1_dist:.0f}m{t1_str})",
                )
            else:
                dpg.configure_item("dragline_telem_s1_loop", show=False)

        if dpg.does_item_exist("dragline_telem_s2_loop"):
            if s2_dist > 0.0:
                t2_str = f" ({self._profile.sector_2_time:.2f}s)" if (self._profile and self._profile.sector_2_time > 0.0) else ""
                dpg.configure_item(
                    "dragline_telem_s2_loop",
                    show=True,
                    default_value=s2_dist,
                    label=f"S2 Loop ({s2_dist:.0f}m{t2_str})",
                )
            else:
                dpg.configure_item("dragline_telem_s2_loop", show=False)

        # 2. Supprimer les anciennes lignes d'annotations utilisateur
        for tag in list(self._annotation_drag_tags.values()):
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)
        self._annotation_drag_tags.clear()

        if not self._profile or not self._profile.annotations:
            return

        for ann in self._profile.annotations:
            tag = f"dragline_ann_{ann.id}"
            label = self._profile.get_annotation_display_label(ann)
            color = self._get_marker_color(ann)

            dpg.add_drag_line(
                parent="plot_telemetry_studio",
                tag=tag,
                label=f"{label} ({ann.distance:.0f}m)",
                vertical=True,
                default_value=ann.distance,
                color=color,
                thickness=2.0,
                user_data=ann.id,
                callback=self._cb_marker_dragged,
            )
            self._annotation_drag_tags[ann.id] = tag

    def _update_marker_drag_line_labels(self) -> None:
        """Met à jour les labels des lignes de repères après déplacement (recalcul T1..T30)."""
        if not self._profile:
            return
        for ann in self._profile.annotations:
            tag = self._annotation_drag_tags.get(ann.id)
            if tag and dpg.does_item_exist(tag):
                label = self._profile.get_annotation_display_label(ann)
                dpg.configure_item(tag, label=f"{label} ({ann.distance:.0f}m)")

    # ── Rendu Visuel : Table Latérale des Annotations ────────────────────────
    def _render_markers_table(self) -> None:
        """Régénère les lignes de la table d'annotations."""
        if not dpg.does_item_exist("table_telem_annotations"):
            return

        # Supprimer les anciennes lignes
        children = dpg.get_item_children("table_telem_annotations", 1)
        if children:
            for child in children:
                dpg.delete_item(child)

        if not self._profile or not self._profile.annotations:
            return

        for ann in self._profile.annotations:
            label = self._profile.get_annotation_display_label(ann)
            phrase = self._profile.get_annotation_phrase_key(ann)
            color = self._get_marker_color(ann)

            with dpg.table_row(parent="table_telem_annotations"):
                # Type avec badge couleur
                dpg.add_text(ann.type.value.upper(), color=color)

                # Label (ex: T1, Brake, Gear 3)
                dpg.add_text(label, color=[255, 255, 255, 255])

                # Distance
                dpg.add_button(
                    label=f"{ann.distance:.1f} m",
                    user_data=ann.distance,
                    callback=lambda s, a, u: self.set_cursor_distance(u),
                )

                # Phrase audio
                dpg.add_text(phrase, color=[180, 180, 180, 255])

                # Boutons d'action (Audio / Supprimer)
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        label="▶",
                        width=22,
                        user_data=phrase,
                        callback=lambda s, a, u: AudioAnnouncer.play_phrase(u),
                    )
                    dpg.add_button(
                        label="X",
                        width=22,
                        user_data=ann.id,
                        callback=self._cb_delete_row,
                    )

    def _cb_delete_row(self, sender, app_data, user_data):
        """Supprime une ligne depuis le bouton X de la table."""
        ann_id = user_data
        if self._profile:
            self._profile.remove_annotation(ann_id, auto_save=True)
            self._render_markers_on_plot()
            self._render_markers_table()
            self._update_header_stats()
            self._sync_profile_to_engine()

    # ── Chargement, Sauvegarde Automatique & Profils ─────────────────────────
    def _refresh_profiles_list(self) -> None:
        """Scanne le dossier profiles/ref_laps et remplit la liste déroulante avec les temps au tour."""
        DEFAULT_REF_LAPS_DIR.mkdir(parents=True, exist_ok=True)
        files = [f for f in DEFAULT_REF_LAPS_DIR.glob("*.json") if not f.name.endswith(".marks.json")]
        self._available_files = files
        self._profile_file_map: Dict[str, Optional[Path]] = {}

        delta_eng = getattr(LMUParser, "_delta_engine", None)
        live_time_str = ""
        if delta_eng and 0.0 < delta_eng.ref_lap_time < 90000.0:
            lt = delta_eng.ref_lap_time
            mins = int(lt // 60)
            secs = lt % 60.0
            live_time_str = f" [{mins}:{secs:06.3f}]" if mins > 0 else f" [{secs:.3f}s]"

        live_label = f"(Live Session Reference Lap){live_time_str}"
        items = [live_label]
        self._profile_file_map[live_label] = None
        self._profile_file_map["(Live Session Reference Lap)"] = None

        for f in sorted(files, key=lambda x: x.name):
            lap_t_str = ""
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    meta = json.load(fp)
                    lt = float(meta.get("lap_time", 0.0))
                    if 0.0 < lt < 90000.0:
                        mins = int(lt // 60)
                        secs = lt % 60.0
                        lap_t_str = f" [{mins}:{secs:06.3f}]" if mins > 0 else f" [{secs:.3f}s]"
            except Exception:
                pass
            item_lbl = f"{f.name}{lap_t_str}"
            items.append(item_lbl)
            self._profile_file_map[item_lbl] = f
            self._profile_file_map[f.name] = f

        if dpg.does_item_exist("combo_ref_profile_files"):
            dpg.configure_item("combo_ref_profile_files", items=items)

    def _cb_refresh_profiles_list(self, sender=None, app_data=None):
        self._refresh_profiles_list()

    def _cb_select_profile_file(self, sender, app_data):
        """Charge le profil sélectionné depuis le disque ou la session active."""
        if not app_data:
            return

        target_file = getattr(self, "_profile_file_map", {}).get(app_data)
        if target_file is None:
            for k, v in getattr(self, "_profile_file_map", {}).items():
                if app_data == k or app_data.startswith(k) or (isinstance(k, str) and k.startswith(app_data)):
                    target_file = v
                    break

        if target_file is None or app_data.startswith("(Live Session Reference Lap)"):
            self._load_active_profile()
            return

        loaded = ReferenceLapProfile.load_from_file(target_file)
        if loaded:
            self._profile = loaded
            self._last_loaded_file = target_file
            self._sync_profile_to_engine()
            self._update_all_ui()

    def _load_active_profile(self) -> None:
        """Charge le profil de référence en mémoire depuis le DeltaEngine."""
        delta_eng = getattr(LMUParser, "_delta_engine", None)
        active_prof = delta_eng.get_reference_profile() if delta_eng else None
        if not active_prof and delta_eng:
            active_prof = delta_eng.all_time_best_profile or delta_eng.current_profile

        if active_prof:
            self._profile = active_prof
        elif delta_eng and delta_eng._ref_t_grid:
            # Créer un ReferenceLapProfile à partir des champs du DeltaEngine
            num_pts = delta_eng._ref_num_points
            self._profile = ReferenceLapProfile(
                track_name=delta_eng._track_name,
                vehicle_name=delta_eng._vehicle_name,
                vehicle_class=delta_eng._vehicle_class,
                lap_time=delta_eng.ref_lap_time,
                track_length=delta_eng._track_length,
                spatial_step=delta_eng._ref_spatial_step,
                num_points=num_pts,
                t_grid=delta_eng._ref_t_grid or [],
                sector_1_dist=delta_eng.sector_1_dist,
                sector_2_dist=delta_eng.sector_2_dist,
            )
            self._sync_profile_to_engine()
        self._update_all_ui()

    def _update_all_ui(self) -> None:
        """Actualise l'ensemble des courbes, tableaux et labels de l'onglet."""
        self._render_curves()
        self._render_markers_on_plot()
        self._render_markers_table()
        self._update_header_stats()
        self._update_cursor_hud_readouts()

    def _update_header_stats(self) -> None:
        """Met à jour les statistiques de l'en-tête (Temps au tour, Longueur, Boucles S1/S2, Nombre de marqueurs)."""
        delta_eng = getattr(LMUParser, "_delta_engine", None)

        lt = 0.0
        if self._profile and 0.0 < self._profile.lap_time < 90000.0:
            lt = self._profile.lap_time
        elif delta_eng and 0.0 < delta_eng.ref_lap_time < 90000.0:
            lt = delta_eng.ref_lap_time

        if dpg.does_item_exist("lbl_telem_lap_time"):
            if 0.0 < lt < 90000.0:
                mins = int(lt // 60)
                secs = lt % 60.0
                dpg.set_value("lbl_telem_lap_time", f"{mins}:{secs:06.3f}" if mins > 0 else f"{secs:.3f}s")
            else:
                dpg.set_value("lbl_telem_lap_time", "--")

        if dpg.does_item_exist("lbl_telem_track_len"):
            tl = self._profile.track_length if self._profile else (delta_eng.track_length if delta_eng else 0.0)
            dpg.set_value("lbl_telem_track_len", f"{tl:.0f} m" if tl > 0 else "--")

        if dpg.does_item_exist("lbl_telem_s1_loop"):
            s1 = self._profile.sector_1_dist if self._profile else (delta_eng.sector_1_dist if delta_eng else 0.0)
            t1 = self._profile.sector_1_time if self._profile else (delta_eng.sector_1_time if delta_eng else 0.0)
            if s1 > 0.0:
                lbl_s1 = f"{s1:.0f} m" + (f" ({t1:.2f}s)" if t1 > 0.0 else "")
                dpg.set_value("lbl_telem_s1_loop", lbl_s1)
            else:
                dpg.set_value("lbl_telem_s1_loop", "--")

        if dpg.does_item_exist("lbl_telem_s2_loop"):
            s2 = self._profile.sector_2_dist if self._profile else (delta_eng.sector_2_dist if delta_eng else 0.0)
            t2 = self._profile.sector_2_time if self._profile else (delta_eng.sector_2_time if delta_eng else 0.0)
            if s2 > 0.0:
                lbl_s2 = f"{s2:.0f} m" + (f" ({t2:.2f}s)" if t2 > 0.0 else "")
                dpg.set_value("lbl_telem_s2_loop", lbl_s2)
            else:
                dpg.set_value("lbl_telem_s2_loop", "--")

        if dpg.does_item_exist("lbl_telem_num_markers"):
            num_marks = len(self._profile.annotations) if (self._profile and self._profile.annotations) else 0
            dpg.set_value("lbl_telem_num_markers", str(num_marks))

    def _render_curves(self) -> None:
        """Injecte les séries de points mètre par mètre dans le tracé DPG."""
        if not self._profile or self._profile.num_points < 2:
            return

        num_pts = self._profile.num_points
        step = self._profile.spatial_step
        x_dist = [i * step for i in range(num_pts)]

        # 0. Zones de fond colorées par secteur (affichées quand les boucles S1 et S2 sont enregistrées)
        s1_dist = self._profile.sector_1_dist if self._profile else 0.0
        s2_dist = self._profile.sector_2_dist if self._profile else 0.0
        max_x = x_dist[-1] if x_dist else (self._profile.track_length if self._profile else 0.0)
        y_min = -105.0
        y_max = 360.0

        if s1_dist > 0.0:
            if dpg.does_item_exist("shade_telem_s1"):
                dpg.configure_item("shade_telem_s1", show=True)
                dpg.set_value("shade_telem_s1", [[0.0, s1_dist], [y_min, y_min], [y_max, y_max]])
        else:
            if dpg.does_item_exist("shade_telem_s1"):
                dpg.configure_item("shade_telem_s1", show=False)

        if s1_dist > 0.0 and s2_dist > s1_dist:
            if dpg.does_item_exist("shade_telem_s2"):
                dpg.configure_item("shade_telem_s2", show=True)
                dpg.set_value("shade_telem_s2", [[s1_dist, s2_dist], [y_min, y_min], [y_max, y_max]])
        else:
            if dpg.does_item_exist("shade_telem_s2"):
                dpg.configure_item("shade_telem_s2", show=False)

        if s2_dist > 0.0 and max_x > s2_dist:
            if dpg.does_item_exist("shade_telem_s3"):
                dpg.configure_item("shade_telem_s3", show=True)
                dpg.set_value("shade_telem_s3", [[s2_dist, max_x], [y_min, y_min], [y_max, y_max]])
        else:
            if dpg.does_item_exist("shade_telem_s3"):
                dpg.configure_item("shade_telem_s3", show=False)

        # 1. Vitesse en km/h
        if self._profile.speed_grid and len(self._profile.speed_grid) == num_pts:
            speed_kmh = [v * 3.6 for v in self._profile.speed_grid]
        else:
            speed_kmh = [0.0] * num_pts

        # 2. Rapport de boîte (Gear)
        if self._profile.gear_grid and len(self._profile.gear_grid) == num_pts:
            gear_data = [float(g) for g in self._profile.gear_grid]
        else:
            gear_data = [0.0] * num_pts

        # 3. Accélérateur (0 - 100%)
        if self._profile.throttle_grid and len(self._profile.throttle_grid) == num_pts:
            thr_pct = [t * 100.0 for t in self._profile.throttle_grid]
        else:
            thr_pct = [0.0] * num_pts

        # 4. Frein (0 - 100%)
        if self._profile.brake_grid and len(self._profile.brake_grid) == num_pts:
            brk_pct = [b * 100.0 for b in self._profile.brake_grid]
        else:
            brk_pct = [0.0] * num_pts

        # 5. Volant (-100% à +100%)
        if self._profile.steering_grid and len(self._profile.steering_grid) == num_pts:
            steer_pct = [s * 100.0 for s in self._profile.steering_grid]
        else:
            steer_pct = [0.0] * num_pts

        if dpg.does_item_exist("series_telem_speed"):
            dpg.set_value("series_telem_speed", [x_dist, speed_kmh])
        if dpg.does_item_exist("series_telem_gear"):
            dpg.set_value("series_telem_gear", [x_dist, gear_data])
        if dpg.does_item_exist("series_telem_throttle"):
            dpg.set_value("series_telem_throttle", [x_dist, thr_pct])
        if dpg.does_item_exist("series_telem_brake"):
            dpg.set_value("series_telem_brake", [x_dist, brk_pct])
        if dpg.does_item_exist("series_telem_steering"):
            dpg.set_value("series_telem_steering", [x_dist, steer_pct])

        if dpg.does_item_exist("axis_telem_dist") and len(x_dist) >= 2:
            dpg.set_axis_limits("axis_telem_dist", x_dist[0], x_dist[-1])

    # ── Rafraîchissement Périodique (Tick UI) ────────────────────────────────
    def render_tick(self) -> None:
        """Mise à jour périodique : position en direct de la voiture (20 Hz) et profil de référence (1 Hz)."""
        now = time.time()

        # 1. Mise à jour de la position de la voiture sur le graphique (20 Hz)
        if (now - self._last_car_pos_tick) >= 0.05:
            self._last_car_pos_tick = now
            self._update_live_car_position()

        # 2. Synchronisation du profil de référence (1 Hz)
        if (now - self._last_ui_tick) >= 1.0:
            self._last_ui_tick = now
            delta_eng = getattr(LMUParser, "_delta_engine", None)
            active_prof = delta_eng.get_reference_profile() if delta_eng else None
            if not active_prof and delta_eng:
                active_prof = delta_eng.all_time_best_profile or delta_eng.current_profile
            if active_prof:
                if (
                    self._profile is None
                    or active_prof.lap_time != self._profile.lap_time
                    or active_prof.track_name != self._profile.track_name
                ):
                    self._profile = active_prof
                    self._update_all_ui()
            self._update_header_stats()

    def _update_live_car_position(self) -> None:
        """Met à jour le curseur bleu ciel de la voiture si le circuit en cours correspond."""
        delta_eng = getattr(LMUParser, "_delta_engine", None)
        if not delta_eng:
            return

        session_track = delta_eng.track_name
        tracks_match = False
        if self._profile and self._profile.track_name and session_track:
            tracks_match = (clean_name_identifier(self._profile.track_name) == clean_name_identifier(session_track))

        self._car_track_matches = tracks_match
        if tracks_match:
            car_dist = delta_eng.get_live_car_distance()
            self._last_known_car_dist = car_dist

            if dpg.does_item_exist("dragline_telem_live_car"):
                dpg.configure_item(
                    "dragline_telem_live_car",
                    show=True,
                    default_value=car_dist,
                    label=f"Live Car ({car_dist:.0f}m)",
                )
            if dpg.does_item_exist("lbl_hud_live_car_dist"):
                dpg.set_value("lbl_hud_live_car_dist", f"{car_dist:.1f} m")
        else:
            self._last_known_car_dist = None
            if dpg.does_item_exist("dragline_telem_live_car"):
                dpg.configure_item("dragline_telem_live_car", show=False)
            if dpg.does_item_exist("lbl_hud_live_car_dist"):
                dpg.set_value("lbl_hud_live_car_dist", "--")
