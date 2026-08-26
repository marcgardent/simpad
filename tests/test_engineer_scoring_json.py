"""
Test d'intégration du Race Engineer avec le fichier d'exemple scoring.json du plugin LMU.
"""

import json
from pathlib import Path
import pytest
from src.engineer.manager import RaceEngineer
from src.engineer.roles.traffic_spotter import TrafficSpotterRole
from src.engineer.roles.lap_validity import LapValidityRole


def test_race_engineer_with_real_scoring_json():
    """Charge scoring.json et vérifie le comportement des rôles intégrés."""
    project_root = Path(__file__).resolve().parent.parent
    scoring_file = project_root / "assets" / "plugins" / "lmu" / "LeMansUltimateTelemetryPlugin" / "scoring.json"

    if not scoring_file.exists():
        pytest.skip("scoring.json non présent")

    with open(scoring_file, "r", encoding="utf-8") as f:
        scoring_data = json.load(f)

    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    engineer = RaceEngineer(audio_engine=mock_audio)

    # Exécution du cycle d'évaluation
    messages = engineer.update(telemetry=None, scoring=scoring_data)

    # L'ingénieur doit avoir évalué tous les rôles sans crash
    roles = engineer.get_roles()
    assert len(roles) >= 2

    spotter = engineer.get_role("traffic_spotter")
    assert spotter is not None
    assert isinstance(spotter, TrafficSpotterRole)

    lap_role = engineer.get_role("lap_validity")
    assert lap_role is not None
    assert isinstance(lap_role, LapValidityRole)
