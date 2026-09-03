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
    """Vérifie le déclenchement de time_cleared (ou clean_lap) lors du passage de flag 1 à 2."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio, busy_duration_sec=1.0, use_actionable_prompt=True)

    # 1. Premier tick avec flag=1 (initialisation silencieuse, aucun son)
    ctx1 = EngineerContext(telemetry=TelemetryData(lap_flag=1))
    msg1 = role.update(ctx1)
    assert msg1 is None
    assert len(played_sounds) == 0
    assert not role.is_busy()

    # 2. Flag passe à 2 (Validation du tour -> Cleared)
    ctx2 = EngineerContext(telemetry=TelemetryData(lap_flag=2))
    msg2 = role.update(ctx2)
    assert msg2 is not None
    assert msg2.phrase_key == "time_cleared"
    assert ("time_cleared", False) in played_sounds
    assert role.is_busy()


def test_lap_validity_dirty_lap_transition():
    """Vérifie le déclenchement de lap_deleted (ou dirty_lap) lors du passage de flag 2 à 0."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio, busy_duration_sec=1.0, use_actionable_prompt=True)

    # 1. Initialisation avec flag=2 (tour propre)
    ctx1 = EngineerContext(telemetry=TelemetryData(lap_flag=2))
    role.update(ctx1)

    # 2. Sortie de piste -> flag passe à 0 (Invalidé -> Lap deleted)
    ctx2 = EngineerContext(telemetry=TelemetryData(lap_flag=0))
    msg2 = role.update(ctx2)
    assert msg2 is not None
    assert msg2.phrase_key == "lap_deleted"
    assert ("lap_deleted", False) in played_sounds
    assert role.is_busy()


def test_lap_validity_no_spurious_announcements():
    """Vérifie qu'aucun message n'est émis si le flag ne change pas."""
    role = LapValidityRole()

    ctx = EngineerContext(telemetry=TelemetryData(lap_flag=2))
    role.update(ctx)

    for _ in range(10):
        msg = role.update(ctx)
        assert msg is None


def test_investigation_give_time_back_actionable():
    """Vérifie le passage au jaune -> Alerte immédiate 'give_time_back' avec interrupt=True."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio, use_actionable_prompt=True)

    # Initialisation sur tour propre
    ctx1 = EngineerContext(telemetry=TelemetryData(lap_flag=2, track_cut_state="green"))
    role.update(ctx1)
    assert len(played_sounds) == 0

    # Sortie de piste -> Jaune / Investigation
    ctx2 = EngineerContext(telemetry=TelemetryData(lap_flag=2, track_cut_state="yellow"))
    msg2 = role.update(ctx2)
    assert msg2 is not None
    assert msg2.phrase_key == "give_time_back"
    assert msg2.interrupt is True
    assert ("give_time_back", True) in played_sounds


def test_investigation_cleared_on_clean_lap():
    """Vérifie le retour au vert sur un tour propre -> Annonce 'time_cleared'."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio, use_actionable_prompt=True)

    ctx1 = EngineerContext(telemetry=TelemetryData(lap_flag=2, track_cut_state="green"))
    role.update(ctx1)

    # Investigation
    ctx2 = EngineerContext(telemetry=TelemetryData(lap_flag=2, track_cut_state="yellow"))
    role.update(ctx2)

    # Le pilote a ralenti -> Temps rendu -> Vert
    ctx3 = EngineerContext(telemetry=TelemetryData(lap_flag=2, track_cut_state="green"))
    msg3 = role.update(ctx3)
    assert msg3 is not None
    assert msg3.phrase_key == "time_cleared"
    assert ("time_cleared", False) in played_sounds
    assert not role._is_lap_dirty


def test_investigation_cleared_on_dirty_lap():
    """
    Règle d'or : Sur un tour déjà invalidé (dirty), un blanchiment d'incident (vert)
    doit annoncer 'no_penalty' et NE DOIT JAMAIS annoncer un Clean Lap !
    """
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio, use_actionable_prompt=True)

    # 1. Le tour démarre ou est invalidé au secteur 1 (flag 0)
    ctx1 = EngineerContext(telemetry=TelemetryData(lap_flag=0, track_cut_state="invalid"))
    role.update(ctx1)
    assert role._is_lap_dirty is True

    # 2. Nouvel incident au secteur 2 (Jaune)
    ctx2 = EngineerContext(telemetry=TelemetryData(lap_flag=1, track_cut_state="yellow"))
    msg2 = role.update(ctx2)
    assert msg2 is not None
    assert msg2.phrase_key == "give_time_back"

    # 3. Le pilote ralentit -> incident effacé (Vert)
    ctx3 = EngineerContext(telemetry=TelemetryData(lap_flag=2, track_cut_state="green"))
    msg3 = role.update(ctx3)
    assert msg3 is not None
    assert msg3.phrase_key == "no_penalty"
    assert ("no_penalty", False) in played_sounds
    # Le tour reste bien dirty !
    assert role._is_lap_dirty is True


def test_investigation_escalates_to_penalty_on_clean_lap():
    """Vérifie l'expiration du temps ou sanction confirmée (Jaune -> Rouge) sur tour propre -> lap_deleted."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio, use_actionable_prompt=True)

    ctx1 = EngineerContext(telemetry=TelemetryData(lap_flag=2, track_cut_state="green"))
    role.update(ctx1)

    ctx2 = EngineerContext(telemetry=TelemetryData(lap_flag=1, track_cut_state="yellow"))
    role.update(ctx2)

    # Le pilote n'a pas ralenti -> Pénalité confirmée (Orange/Red)
    ctx3 = EngineerContext(telemetry=TelemetryData(lap_flag=0, track_cut_state="red"))
    msg3 = role.update(ctx3)
    assert msg3 is not None
    assert msg3.phrase_key == "lap_deleted"
    assert role._is_lap_dirty is True


def test_investigation_escalates_to_penalty_on_dirty_lap():
    """Vérifie sanction confirmée sur un tour déjà dirty -> penalty_applied."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio, use_actionable_prompt=True)

    # Tour déjà invalidé
    ctx1 = EngineerContext(telemetry=TelemetryData(lap_flag=0, track_cut_state="invalid"))
    role.update(ctx1)

    ctx2 = EngineerContext(telemetry=TelemetryData(lap_flag=1, track_cut_state="yellow"))
    role.update(ctx2)

    # Sanction confirmée
    ctx3 = EngineerContext(telemetry=TelemetryData(lap_flag=0, track_cut_state="orange"))
    msg3 = role.update(ctx3)
    assert msg3 is not None
    assert msg3.phrase_key == "penalty_applied"


def test_lap_boundary_resets_dirty_state():
    """Vérifie que le franchissement de ligne (laps_completed + 1) réinitialise le statut dirty."""
    role = LapValidityRole()

    # Tour 1 invalidé
    ctx1 = EngineerContext(telemetry=TelemetryData(lap_flag=0, laps_completed=1, track_cut_state="green"))
    role.update(ctx1)
    assert role._is_lap_dirty is True

    # Tour 2 commence (laps_completed passe à 2, lap_flag=2)
    ctx2 = EngineerContext(telemetry=TelemetryData(lap_flag=2, laps_completed=2, track_cut_state="green"))
    role.update(ctx2)
    assert role._is_lap_dirty is False


def test_parameters_toggle():
    """Vérifie la désactivation des annonces d'investigation ou de blanchiment via paramètres."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(
        audio_engine=mock_audio,
        announce_investigation=False,
        announce_cleared=False,
    )

    ctx1 = EngineerContext(telemetry=TelemetryData(lap_flag=2, track_cut_state="green"))
    role.update(ctx1)

    # Yellow -> pas d'annonce car announce_investigation=False
    ctx2 = EngineerContext(telemetry=TelemetryData(lap_flag=2, track_cut_state="yellow"))
    msg2 = role.update(ctx2)
    assert msg2 is None
    assert len(played_sounds) == 0

    # Green -> pas d'annonce car announce_cleared=False
    ctx3 = EngineerContext(telemetry=TelemetryData(lap_flag=2, track_cut_state="green"))
    msg3 = role.update(ctx3)
    assert msg3 is None
    assert len(played_sounds) == 0


def test_use_actionable_prompt_false_uses_passive_phrases():
    """Vérifie l'utilisation des phrases passives (under_investigation, incident_cleared) si use_actionable_prompt=False."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio, use_actionable_prompt=False)

    ctx1 = EngineerContext(telemetry=TelemetryData(lap_flag=2, track_cut_state="green"))
    role.update(ctx1)

    ctx2 = EngineerContext(telemetry=TelemetryData(lap_flag=2, track_cut_state="yellow"))
    msg2 = role.update(ctx2)
    assert msg2.phrase_key == "under_investigation"

    ctx3 = EngineerContext(telemetry=TelemetryData(lap_flag=2, track_cut_state="green"))
    msg3 = role.update(ctx3)
    assert msg3.phrase_key == "incident_cleared"


def test_scoring_vehicle_attribute_detection():
    """Vérifie la détection de l'état d'incident depuis le paquet de scoring (dictionnaire ou objet)."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio)

    # 1. Init tick
    scoring_init = {
        "mVehicles": [
            {"mIsPlayer": 1, "mCountLapFlag": 2, "mTrackCutState": "green", "mTotalLaps": 3}
        ]
    }
    role.update(EngineerContext(scoring=scoring_init))

    # 2. Cut tick
    scoring_data = {
        "mVehicles": [
            {"mIsPlayer": 1, "mCountLapFlag": 2, "mTrackCutState": "yellow", "mTotalLaps": 3}
        ]
    }
    ctx = EngineerContext(scoring=scoring_data)
    msg = role.update(ctx)
    assert msg is not None
    assert msg.phrase_key == "give_time_back"

    summary = role.get_state_summary()
    assert summary["incident_state"] == "INVESTIGATION"
    assert summary["is_busy"] is True


def test_lap_flag_direct_investigation_and_cleared():
    """Vérifie le flux réel LMU flag 2 -> 1 -> 2 (Cut -> Rendu -> Blanchi)."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio)

    # 1. Tour propre lancé (flag=2)
    ctx1 = EngineerContext(telemetry=TelemetryData(lap_flag=2, laps_completed=3))
    role.update(ctx1)
    assert len(played_sounds) == 0

    # 2. Cut du pilote -> LMU passe flag=1 (Investigation)
    ctx2 = EngineerContext(telemetry=TelemetryData(lap_flag=1, laps_completed=3))
    msg2 = role.update(ctx2)
    assert msg2 is not None
    assert msg2.phrase_key == "give_time_back"
    assert msg2.interrupt is True
    assert ("give_time_back", True) in played_sounds

    # 3. Le pilote rend le temps -> LMU repasse flag=2 (Cleared)
    ctx3 = EngineerContext(telemetry=TelemetryData(lap_flag=2, laps_completed=3))
    msg3 = role.update(ctx3)
    assert msg3 is not None
    assert msg3.phrase_key == "time_cleared"
    assert ("time_cleared", False) in played_sounds
    assert not role._is_lap_dirty


def test_lap_flag_investigation_on_already_deleted_lap():
    """Vérifie qu'un cut sur un tour déjà delete annonce 'give_time_back' puis 'no_penalty' au vert."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio)

    # 1. Le tour a déjà été supprimé au début (flag=0)
    ctx1 = EngineerContext(telemetry=TelemetryData(lap_flag=0, laps_completed=4))
    role.update(ctx1)
    assert role._is_lap_dirty is True

    # 2. Le pilote fait un nouveau cut -> flag passe à 1 (Investigation)
    ctx2 = EngineerContext(telemetry=TelemetryData(lap_flag=1, laps_completed=4))
    msg2 = role.update(ctx2)
    assert msg2 is not None
    assert msg2.phrase_key == "give_time_back"

    # 3. Le pilote rend le temps -> flag repasse à 2
    ctx3 = EngineerContext(telemetry=TelemetryData(lap_flag=2, laps_completed=4))
    msg3 = role.update(ctx3)
    assert msg3 is not None
    assert msg3.phrase_key == "no_penalty"
    assert role._is_lap_dirty is True


def test_lap_flag_investigation_penalty_applied_on_already_deleted_lap():
    """Vérifie qu'un cut non rendu sur un tour déjà delete annonce 'penalty_applied'."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio)

    # 1. Tour déjà delete (flag=0)
    ctx1 = EngineerContext(telemetry=TelemetryData(lap_flag=0, laps_completed=5))
    role.update(ctx1)

    # 2. Cut -> investigation (flag=1)
    ctx2 = EngineerContext(telemetry=TelemetryData(lap_flag=1, laps_completed=5))
    role.update(ctx2)

    # 3. Non respect du temps -> sanction confirmée (flag=0)
    ctx3 = EngineerContext(telemetry=TelemetryData(lap_flag=0, laps_completed=5))
    msg3 = role.update(ctx3)
    assert msg3 is not None
    assert msg3.phrase_key == "penalty_applied"


def test_lap_zero_works_consistently():
    """Vérifie que sur Lap 0, les track limits fonctionnent exactement de la même manière."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio)

    # Lap 0 démarre propre
    ctx1 = EngineerContext(telemetry=TelemetryData(lap_flag=2, laps_completed=0))
    role.update(ctx1)

    # Cut sur Lap 0 -> investigation
    ctx2 = EngineerContext(telemetry=TelemetryData(lap_flag=1, laps_completed=0))
    msg2 = role.update(ctx2)
    assert msg2 is not None
    assert msg2.phrase_key == "give_time_back"

    # Temps rendu sur Lap 0 -> cleared
    ctx3 = EngineerContext(telemetry=TelemetryData(lap_flag=2, laps_completed=0))
    msg3 = role.update(ctx3)
    assert msg3 is not None
    assert msg3.phrase_key == "time_cleared"

