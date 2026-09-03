"""
Unit & Integration Tests for SimPad Logger Activation Flags & Configuration in config.json.
"""

import json
import logging
from pathlib import Path
import pytest

from src.core.config import (
    DEFAULT_CONFIG,
    DEFAULT_LOGGER_FLAGS,
    LOGGER_CATEGORY_MAP,
    load_config,
    save_config,
    apply_logger_config,
    setup_logging,
    get_logger_flags,
    set_logger_flag,
    _deep_merge_dict,
)
from src.telemetry.track_limits_logger import TrackLimitsLogger
from src.telemetry.overlay_anomaly_logger import OverlayAnomalyLogger
import src.telemetry.delta_engine as delta_engine


class TestLoggerConfiguration:
    def test_default_config_contains_loggers(self):
        """Vérifie que la configuration par défaut contient bien tous les drapeaux de loggers."""
        assert "loggers" in DEFAULT_CONFIG
        loggers = DEFAULT_CONFIG["loggers"]
        expected_flags = [
            "telemetry",
            "engineer",
            "schedule",
            "haptics",
            "gui",
            "utils",
            "track_limits",
            "overlay_anomaly",
            "delta_debug",
        ]
        for flag in expected_flags:
            assert flag in loggers
            assert loggers[flag] is True

    def test_category_mapping(self):
        """Vérifie le mapping des catégories de loggers vers les modules src."""
        assert "telemetry" in LOGGER_CATEGORY_MAP
        assert "src.telemetry" in LOGGER_CATEGORY_MAP["telemetry"]
        assert "src.engineer" in LOGGER_CATEGORY_MAP["engineer"]
        assert "src.schedule" in LOGGER_CATEGORY_MAP["schedule"]
        assert "src.haptics" in LOGGER_CATEGORY_MAP["haptics"]
        assert "src.gui" in LOGGER_CATEGORY_MAP["gui"]
        assert "src.utils" in LOGGER_CATEGORY_MAP["utils"]

    def test_apply_logger_config_enables_and_disables(self):
        """Vérifie que apply_logger_config active ou désactive bien les loggers standard."""
        # Test désactivation de telemetry
        cfg = {"loggers": {"telemetry": False, "engineer": True}}
        apply_logger_config(cfg)

        telem_logger = logging.getLogger("src.telemetry")
        telem_child = logging.getLogger("src.telemetry.udp_server")
        engineer_logger = logging.getLogger("src.engineer")

        assert telem_logger.disabled is True
        assert telem_child.disabled is True
        assert engineer_logger.disabled is False

        # Test réactivation
        cfg = {"loggers": {"telemetry": True}}
        apply_logger_config(cfg)
        assert telem_logger.disabled is False
        assert telem_child.disabled is False
        assert telem_logger.level == logging.INFO

    def test_apply_logger_config_custom_levels(self):
        """Vérifie la définition d'un niveau textuel ou numérique spécifique."""
        cfg = {"loggers": {"telemetry": "DEBUG", "engineer": "WARNING"}}
        apply_logger_config(cfg)

        telem_logger = logging.getLogger("src.telemetry")
        engineer_logger = logging.getLogger("src.engineer")

        assert telem_logger.level == logging.DEBUG
        assert engineer_logger.level == logging.WARNING
        assert telem_logger.disabled is False
        assert engineer_logger.disabled is False

    def test_track_limits_logger_flag(self, tmp_path):
        """Vérifie que le drapeau track_limits active et désactive TrackLimitsLogger."""
        log_file = tmp_path / "test_track_limits.log"
        inst = TrackLimitsLogger(log_path=str(log_file))
        TrackLimitsLogger._instance = inst

        apply_logger_config({"loggers": {"track_limits": False}})
        assert inst.enabled is False
        assert TrackLimitsLogger.default_enabled is False

        # Test émission quand désactivé -> aucun write
        inst.log_telemetry_event("Test", lap_num=1, event_note="Ignored")
        inst.log_spotter_action("TEST_PHRASE", False)

        apply_logger_config({"loggers": {"track_limits": True}})
        assert inst.enabled is True
        assert TrackLimitsLogger.default_enabled is True

    def test_overlay_anomaly_logger_flag(self, tmp_path):
        """Vérifie que le drapeau overlay_anomaly active et désactive OverlayAnomalyLogger."""
        log_file = tmp_path / "test_glitch.log"
        inst = OverlayAnomalyLogger(log_path=log_file)
        OverlayAnomalyLogger._instance = inst

        apply_logger_config({"loggers": {"overlay_anomaly": False}})
        assert inst.enabled is False
        assert OverlayAnomalyLogger.default_enabled is False

        inst.log_event("TEST_CAT", "Test msg")

        apply_logger_config({"loggers": {"overlay_anomaly": True}})
        assert inst.enabled is True
        assert OverlayAnomalyLogger.default_enabled is True

    def test_delta_debug_flag(self):
        """Vérifie que le drapeau delta_debug active et désactive DELTA_DEBUG_ENABLED."""
        apply_logger_config({"loggers": {"delta_debug": False}})
        assert delta_engine.DELTA_DEBUG_ENABLED is False

        apply_logger_config({"loggers": {"delta_debug": True}})
        assert delta_engine.DELTA_DEBUG_ENABLED is True

    def test_set_and_get_logger_flag(self, tmp_path):
        """Vérifie l'utilitaire set_logger_flag et la persistance éventuelle."""
        cfg_file = tmp_path / "custom_config.json"
        cfg = set_logger_flag("telemetry", False, save=True, config_path=cfg_file)

        assert cfg["loggers"]["telemetry"] is False
        assert cfg_file.exists()

        # Relecture depuis le fichier
        loaded = load_config(cfg_file)
        assert loaded["loggers"]["telemetry"] is False
        # Les autres loggers par défaut doivent être présents grâce au deep merge
        assert loaded["loggers"]["engineer"] is True

    def test_deep_merge_dict(self):
        """Vérifie que _deep_merge_dict fusionne les sous-dictionnaires sans supprimer les clés par défaut."""
        base = {
            "a": 1,
            "loggers": {"telemetry": True, "engineer": True, "schedule": True},
        }
        custom = {
            "loggers": {"telemetry": False},
        }
        merged = _deep_merge_dict(base, custom)
        assert merged["loggers"]["telemetry"] is False
        assert merged["loggers"]["engineer"] is True
        assert merged["loggers"]["schedule"] is True
        assert merged["a"] == 1
