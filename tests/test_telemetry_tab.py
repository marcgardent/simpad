"""
Unit tests for TelemetryTab (Dear PyGui Telemetry & Annotation Studio).
"""

import os
import shutil
import tempfile
from pathlib import Path
import unittest
import dearpygui.dearpygui as dpg

from src.gui.telemetry_tab import TelemetryTab
from src.telemetry.reference_profile import (
    ReferenceLapProfile,
    TrackAnnotation,
    AnnotationType,
)
from src.telemetry.lmu_parser import LMUParser


class TestTelemetryTab(unittest.TestCase):
    def setUp(self):
        dpg.create_context()
        self.temp_dir = tempfile.mkdtemp()
        if hasattr(LMUParser, "_delta_engine") and LMUParser._delta_engine:
            LMUParser._delta_engine.reset_session()
        self.tab = TelemetryTab()
        self.tab._profile = ReferenceLapProfile(
            track_name="TestCircuit",
            vehicle_name="TestCar",
            track_length=2000.0,
            spatial_step=1.0,
            num_points=2001,
            t_grid=[(i / 2000.0) * 100.0 for i in range(2001)],
            speed_grid=[30.0 for _ in range(2001)],
            throttle_grid=[0.5 for _ in range(2001)],
            brake_grid=[0.0 for _ in range(2001)],
            steering_grid=[0.0 for _ in range(2001)],
        )
        self.tab._profile.set_marks_filepath(Path(self.temp_dir) / "test.marks.json")

    def tearDown(self):
        if hasattr(LMUParser, "_delta_engine") and LMUParser._delta_engine:
            LMUParser._delta_engine.reset_session()
        dpg.destroy_context()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cursor_distance_setting_and_clamping(self):
        """Test setting cursor distance with automatic clamping to track length."""
        self.tab.set_cursor_distance(450.5)
        self.assertEqual(self.tab._cursor_distance, 450.5)

        # Clamp at 0
        self.tab.set_cursor_distance(-50.0)
        self.assertEqual(self.tab._cursor_distance, 0.0)

        # Clamp at track length
        self.tab.set_cursor_distance(3000.0)
        self.assertEqual(self.tab._cursor_distance, 2000.0)

    def test_add_annotation_at_cursor(self):
        """Test adding annotations at cursor location and auto-saving marks."""
        self.tab.set_cursor_distance(500.0)
        ann_brk = self.tab.add_annotation_at_cursor(AnnotationType.BRAKE)
        self.assertIsNotNone(ann_brk)
        self.assertEqual(ann_brk.distance, 500.0)
        self.assertEqual(ann_brk.type, AnnotationType.BRAKE)

        self.tab.set_cursor_distance(600.0)
        ann_gear = self.tab.add_annotation_at_cursor(AnnotationType.GEAR, gear=3)
        self.assertIsNotNone(ann_gear)
        self.assertEqual(ann_gear.gear, 3)

        self.assertEqual(len(self.tab._profile.annotations), 2)
        # Check that marks file was auto-saved on disk!
        marks_file = Path(self.temp_dir) / "test.marks.json"
        self.assertTrue(marks_file.exists())

    def test_delete_selected_or_nearest(self):
        """Test deleting an annotation either by selection or nearest cursor."""
        self.tab.set_cursor_distance(100.0)
        ann1 = self.tab.add_annotation_at_cursor(AnnotationType.BRAKE)

        self.tab.set_cursor_distance(800.0)
        ann2 = self.tab.add_annotation_at_cursor(AnnotationType.TURN)

        self.assertEqual(len(self.tab._profile.annotations), 2)

        # Delete selected
        self.tab._selected_annotation_id = ann1.id
        self.tab._cb_delete_selected_or_nearest()
        self.assertEqual(len(self.tab._profile.annotations), 1)
        self.assertEqual(self.tab._profile.annotations[0].id, ann2.id)

        # Delete nearest
        self.tab._selected_annotation_id = None
        self.tab.set_cursor_distance(805.0)  # Near ann2
        self.tab._cb_delete_selected_or_nearest()
        self.assertEqual(len(self.tab._profile.annotations), 0)

    def test_sync_cursor_to_car(self):
        """Test snapping editing cursor to live/last-known car position."""
        self.tab._last_known_car_dist = 1234.5
        self.tab._car_track_matches = True
        self.tab._cb_sync_cursor_to_car()
        self.assertEqual(self.tab._cursor_distance, 1234.5)

        # When tracks do not match, sync should be ignored
        self.tab._car_track_matches = False
        self.tab._last_known_car_dist = 500.0
        self.tab._cb_sync_cursor_to_car()
        self.assertEqual(self.tab._cursor_distance, 1234.5)

    def test_sector_loops_and_gear_rendering(self):
        """Test UI elements for sector 1/2 timing loops and gear telemetry."""
        self.tab._profile.sector_1_dist = 650.0
        self.tab._profile.sector_2_dist = 1400.0
        self.tab._profile.sector_1_time = 32.5
        self.tab._profile.sector_2_time = 71.2
        self.tab._profile.gear_grid = [1 if i < 500 else (2 if i < 1000 else 3) for i in range(2001)]

        with dpg.window(label="Test Window"):
            self.tab.build_tab(parent_app=None)

        # Check items exist
        self.assertTrue(dpg.does_item_exist("lbl_telem_s1_loop"))
        self.assertTrue(dpg.does_item_exist("lbl_telem_s2_loop"))
        self.assertTrue(dpg.does_item_exist("lbl_hud_cursor_sector"))
        self.assertTrue(dpg.does_item_exist("series_telem_gear"))
        self.assertTrue(dpg.does_item_exist("shade_telem_s1"))
        self.assertTrue(dpg.does_item_exist("shade_telem_s2"))
        self.assertTrue(dpg.does_item_exist("shade_telem_s3"))

        # Update and verify stats and markers
        self.tab._update_header_stats()
        self.assertIn("650", dpg.get_value("lbl_telem_s1_loop"))
        self.assertIn("1400", dpg.get_value("lbl_telem_s2_loop"))

        # Verify cursor sector HUD
        self.tab.set_cursor_distance(300.0)
        self.assertEqual(dpg.get_value("lbl_hud_cursor_sector"), "S1")
        self.assertEqual(dpg.get_value("lbl_hud_cursor_gear"), "1")

        self.tab.set_cursor_distance(800.0)
        self.assertEqual(dpg.get_value("lbl_hud_cursor_sector"), "S2")
        self.assertEqual(dpg.get_value("lbl_hud_cursor_gear"), "2")

        self.tab.set_cursor_distance(1600.0)
        self.assertEqual(dpg.get_value("lbl_hud_cursor_sector"), "S3")
        self.assertEqual(dpg.get_value("lbl_hud_cursor_gear"), "3")

        # Verify curves and shaded zones rendering
        self.tab._render_curves()
        self.assertTrue(dpg.is_item_shown("shade_telem_s1"))
        self.assertTrue(dpg.is_item_shown("shade_telem_s2"))
        self.assertTrue(dpg.is_item_shown("shade_telem_s3"))
        val_s1 = dpg.get_value("shade_telem_s1")
        self.assertEqual(val_s1[0], [0.0, 650.0])
        val_s2 = dpg.get_value("shade_telem_s2")
        self.assertEqual(val_s2[0], [650.0, 1400.0])
        val_s3 = dpg.get_value("shade_telem_s3")
        self.assertEqual(val_s3[0], [1400.0, 2000.0])

    def test_reference_lap_time_header_display(self):
        """Vérifie que l'en-tête de l'UI affiche le temps au tour correspondant à la référence."""
        with dpg.window(label="Test Window 2"):
            self.tab.build_tab(parent_app=None)

        self.tab._profile.lap_time = 92.450  # 1 min 32.450s
        self.tab._update_header_stats()

        lap_time_val = dpg.get_value("lbl_telem_lap_time")
        self.assertEqual(lap_time_val, "1:32.450")

        # Test sub-minute lap time
        self.tab._profile.lap_time = 58.125
        self.tab._update_header_stats()
        self.assertEqual(dpg.get_value("lbl_telem_lap_time"), "58.125s")

    def test_refresh_profiles_list_and_selection_with_lap_times(self):
        """Vérifie que la liste déroulante affiche le temps au tour des profils et permet la sélection."""
        import json
        with dpg.window(label="Test Window 3"):
            self.tab.build_tab(parent_app=None)

        # Créer un fichier de profil factice avec lap_time
        dummy_file = Path(self.temp_dir) / "ref_spa_ferrari.json"
        with open(dummy_file, "w", encoding="utf-8") as fp:
            json.dump({
                "track_name": "Spa",
                "vehicle_name": "Ferrari",
                "lap_time": 138.750,
                "track_length": 7004.0,
                "num_points": 7005,
                "spatial_step": 1.0,
                "t_grid": [0.0, 138.750],
            }, fp)

        self.tab._available_files = [dummy_file]
        self.tab._profile_file_map = {
            f"ref_spa_ferrari.json [2:18.750]": dummy_file,
            "ref_spa_ferrari.json": dummy_file,
        }

        # Sélectionner via le libellé formaté
        self.tab._cb_select_profile_file(None, "ref_spa_ferrari.json [2:18.750]")
        self.assertIsNotNone(self.tab._profile)
        self.assertEqual(self.tab._profile.lap_time, 138.750)
        self.assertEqual(dpg.get_value("lbl_telem_lap_time"), "2:18.750")

    def test_build_tab_without_initial_profile(self):
        """Vérifie que la construction de l'onglet sans profil actif préalable (démarrage SimPad) ne lève pas d'exception."""
        tab = TelemetryTab()
        self.assertIsNone(tab._profile)
        with dpg.window(label="Test Window Startup"):
            tab.build_tab(parent_app=None)
        # Verify default UI labels when no profile is active
        self.assertEqual(dpg.get_value("lbl_telem_lap_time"), "--")
        self.assertEqual(dpg.get_value("lbl_telem_track_len"), "--")
        self.assertEqual(dpg.get_value("lbl_telem_s1_loop"), "--")
        self.assertEqual(dpg.get_value("lbl_telem_s2_loop"), "--")


if __name__ == "__main__":
    unittest.main()
