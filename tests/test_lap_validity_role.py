"""
Tests unitaires pour LapValidityRole (Dirty / Clean Lap).
"""

import time
import pytest
from src.engineer.context import EngineerContext
from src.engineer.roles.lap_validity import LapValidityRole
from src.telemetry.lmu_parser import TelemetryData


def test_lap_validity_initialization():
    role = LapValidityRole()
    assert role.role_id == "lap_validity"
    assert role.enabled is True
    assert not role.is_busy()


def test_lap_validity_clean_lap_transition():
    """Vérifie le déclenchement de clean_lap lors du passage de flag 1 (ou 0) à 2."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio, busy_duration_sec=1.0)

    # 1. Premier tick avec flag=1 (initialisation, aucun son)
    ctx1 = EngineerContext(telemetry=TelemetryData(lap_flag=1))
    msg1 = role.update(ctx1)
    assert msg1 is None
    assert len(played_sounds) == 0
    assert not role.is_busy()

    # 2. Flag passe à 2 (Validation du tour -> Clean Lap)
    ctx2 = EngineerContext(telemetry=TelemetryData(lap_flag=2))
    msg2 = role.update(ctx2)
    assert msg2 is not None
    assert msg2.phrase_key == "clean_lap"
    assert ("clean_lap", False) in played_sounds
    assert role.is_busy()


def test_lap_validity_dirty_lap_transition():
    """Vérifie le déclenchement de dirty_lap lors du passage de flag 2 à 0/1."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio, busy_duration_sec=1.0)

    # 1. Initialisation avec flag=2 (tour propre)
    ctx1 = EngineerContext(telemetry=TelemetryData(lap_flag=2))
    role.update(ctx1)

    # 2. Sortie de piste -> flag passe à 0 (Invalidé -> Dirty Lap)
    ctx2 = EngineerContext(telemetry=TelemetryData(lap_flag=0))
    msg2 = role.update(ctx2)
    assert msg2 is not None
    assert msg2.phrase_key == "dirty_lap"
    assert ("dirty_lap", False) in played_sounds
    assert role.is_busy()


def test_lap_validity_no_spurious_announcements():
    """Vérifie qu'aucun message n'est émis si le flag ne change pas."""
    role = LapValidityRole()

    ctx = EngineerContext(telemetry=TelemetryData(lap_flag=2))
    role.update(ctx)

    for _ in range(10):
        msg = role.update(ctx)
        assert msg is None
