"""
Tests unitaires pour LapValidityRole (100% stateless : Timing in progress / Time deleted).
"""

import time
import pytest
from src.engineer.context import EngineerContext
from src.engineer.roles.lap_validity import LapValidityRole
from src.telemetry.lmu_parser import TelemetryData
from src.telemetry.state_store import TelemetryStateStore


@pytest.fixture(autouse=True)
def reset_state_store():
    TelemetryStateStore.get_instance().reset()
    yield
    TelemetryStateStore.get_instance().reset()


def test_lap_validity_initialization():
    role = LapValidityRole()
    assert role.role_id == "lap_validity"
    assert role.enabled is True
    assert not role.is_busy()


def test_lap_validity_timing_in_progress_from_flag_1():
    """Vérifie le déclenchement de 'timing_in_progress' lors du passage de flag 1 à 2."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio, busy_duration_sec=1.0)

    # 1. Premier tick avec flag=1 (initialisation silencieuse, aucun son)
    ctx1 = EngineerContext(telemetry=TelemetryData(in_realtime=True, lap_flag=1))
    msg1 = role.update(ctx1)
    assert msg1 is None
    assert len(played_sounds) == 0
    assert not role.is_busy()

    # 2. Flag passe à 2 (Validation du tour -> Timing in progress)
    ctx2 = EngineerContext(telemetry=TelemetryData(in_realtime=True, lap_flag=2))
    msg2 = role.update(ctx2)
    assert msg2 is not None
    assert msg2.phrase_key == "timing_in_progress"
    assert msg2.interrupt is False
    assert ("timing_in_progress", False) in played_sounds
    assert role.is_busy()


def test_lap_validity_timing_in_progress_from_flag_0():
    """Vérifie le déclenchement de 'timing_in_progress' lors du passage de flag 0 à 2."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio, busy_duration_sec=1.0)

    # 1. Premier tick avec flag=0
    ctx1 = EngineerContext(telemetry=TelemetryData(in_realtime=True, lap_flag=0))
    role.update(ctx1)
    assert len(played_sounds) == 0

    # 2. Flag passe à 2
    ctx2 = EngineerContext(telemetry=TelemetryData(in_realtime=True, lap_flag=2))
    msg2 = role.update(ctx2)
    assert msg2 is not None
    assert msg2.phrase_key == "timing_in_progress"
    assert ("timing_in_progress", False) in played_sounds


def test_lap_validity_time_deleted_from_flag_2_to_0():
    """Vérifie le déclenchement de 'time_deleted' lors du passage de flag 2 à 0."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio, busy_duration_sec=1.0)

    # 1. Initialisation avec flag=2 (tour propre)
    ctx1 = EngineerContext(telemetry=TelemetryData(in_realtime=True, lap_flag=2))
    role.update(ctx1)
    assert len(played_sounds) == 0

    # 2. Sortie de piste / cut -> flag passe à 0 (Invalidé -> Time deleted)
    ctx2 = EngineerContext(telemetry=TelemetryData(in_realtime=True, lap_flag=0))
    msg2 = role.update(ctx2)
    assert msg2 is not None
    assert msg2.phrase_key == "time_deleted"
    assert msg2.interrupt is False
    assert ("time_deleted", False) in played_sounds
    assert role.is_busy()


def test_lap_validity_time_deleted_from_flag_2_to_1():
    """Vérifie le déclenchement de 'time_deleted' lors du passage de flag 2 à 1."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio, busy_duration_sec=1.0)

    # 1. Initialisation avec flag=2
    ctx1 = EngineerContext(telemetry=TelemetryData(in_realtime=True, lap_flag=2))
    role.update(ctx1)
    assert len(played_sounds) == 0

    # 2. Cut -> flag passe à 1 (Time deleted)
    ctx2 = EngineerContext(telemetry=TelemetryData(in_realtime=True, lap_flag=1))
    msg2 = role.update(ctx2)
    assert msg2 is not None
    assert msg2.phrase_key == "time_deleted"
    assert ("time_deleted", False) in played_sounds


def test_lap_validity_no_spurious_announcements():
    """Vérifie qu'aucun message n'est émis si le flag ne change pas."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio)

    ctx = EngineerContext(telemetry=TelemetryData(in_realtime=True, lap_flag=2))
    role.update(ctx)

    for _ in range(50):
        msg = role.update(ctx)
        assert msg is None

    assert len(played_sounds) == 0


def test_garage_silent_init_and_exiting_garage():
    """Vérifie que dans le garage et en sortie des stands, le spotter reste silencieux."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio)

    # 1. Dans le garage (in_realtime=False)
    ctx1 = EngineerContext(
        telemetry=TelemetryData(lap_flag=1, in_realtime=False),
        scoring={"mInGarageStall": 1, "mCountLapFlag": 1, "mTotalLaps": 0}
    )
    msg1 = role.update(ctx1)
    assert msg1 is None
    assert len(played_sounds) == 0

    # 2. Sortie des stands (flag=1 au spawn)
    ctx2 = EngineerContext(
        telemetry=TelemetryData(lap_flag=1, in_realtime=True),
        scoring={"mInGarageStall": 0, "mCountLapFlag": 1, "mTotalLaps": 0}
    )
    msg2 = role.update(ctx2)
    assert msg2 is None
    assert len(played_sounds) == 0

    # 3. Premier franchissement / validation sur piste (flag 1 -> 2)
    ctx3 = EngineerContext(
        telemetry=TelemetryData(lap_flag=2, in_realtime=True),
        scoring={"mInGarageStall": 0, "mCountLapFlag": 2, "mTotalLaps": 1}
    )
    msg3 = role.update(ctx3)
    assert msg3 is not None
    assert msg3.phrase_key == "timing_in_progress"
    assert ("timing_in_progress", False) in played_sounds


def test_scoring_vehicle_attribute_detection():
    """Vérifie la détection du flag depuis le paquet de scoring (dictionnaire ou objet)."""
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio)

    # 1. Init tick
    scoring_init = {
        "mVehicles": [
            {"mIsPlayer": 1, "mCountLapFlag": 2, "mTotalLaps": 3, "mInGarageStall": 0}
        ]
    }
    role.update(EngineerContext(scoring=scoring_init))

    # 2. Cut tick (mCountLapFlag -> 1)
    scoring_data = {
        "mVehicles": [
            {"mIsPlayer": 1, "mCountLapFlag": 1, "mTotalLaps": 3, "mInGarageStall": 0}
        ]
    }
    ctx = EngineerContext(scoring=scoring_data)
    msg = role.update(ctx)
    assert msg is not None
    assert msg.phrase_key == "time_deleted"

    summary = role.get_state_summary()
    assert summary["lap_flag"] == 1
    assert summary["last_event"] == "TIME_DELETED"
    assert summary["is_busy"] is True


def test_mixed_udp_stream_no_infinite_loop():
    """Vérifie qu'un flux mixte de paquets haute fréquence (TelemInfo) et CompactScoring ne boucle jamais."""
    from isimotor_rawudp_client import CompactScoring, TelemInfo
    played_sounds = []

    def mock_audio(phrase_key, interrupt=False):
        played_sounds.append((phrase_key, interrupt))

    role = LapValidityRole(audio_engine=mock_audio)

    # 1. Flux normal tour propre
    telem = TelemInfo(unfiltered_throttle=1.0, gear=3)
    scoring_clean = CompactScoring(count_lap_flag=2, total_laps=1, in_garage_stall=0)

    # 100 ticks alternant TelemInfo et CompactScoring sur tour propre
    for _ in range(50):
        role.update(EngineerContext(telemetry=telem, scoring=scoring_clean))

    assert len(played_sounds) == 0  # Aucun son intempestif en régime établi

    # 2. Cut du pilote -> flag passe à 1
    scoring_cut = CompactScoring(count_lap_flag=1, total_laps=1, in_garage_stall=0)
    for _ in range(50):
        role.update(EngineerContext(telemetry=telem, scoring=scoring_cut))

    # Doit avoir joué 'time_deleted' EXACTEMENT 1 fois
    assert played_sounds == [("time_deleted", False)]

    # 3. Le pilote valide à nouveau -> flag repasse à 2
    for _ in range(50):
        role.update(EngineerContext(telemetry=telem, scoring=scoring_clean))

    # Doit avoir joué 'timing_in_progress' EXACTEMENT 1 fois
    assert played_sounds == [("time_deleted", False), ("timing_in_progress", False)]


def test_reset_functionality():
    """Vérifie que reset() réinitialise correctement l'état interne."""
    role = LapValidityRole()
    ctx = EngineerContext(telemetry=TelemetryData(in_realtime=True, lap_flag=2))
    role.update(ctx)
    assert role._last_lap_flag == 2

    role.reset()
    assert role._last_lap_flag is None
    assert role._last_event_name == "IDLE"
    assert role._last_event_time == 0.0


def test_get_sound_requirements():
    """Vérifie que les sons requis sont déclarés."""
    role = LapValidityRole()
    sounds = role.get_sound_requirements()
    assert "timing_in_progress" in sounds
    assert "time_deleted" in sounds










