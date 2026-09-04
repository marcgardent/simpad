import os
import tempfile
from pathlib import Path
import pytest
from simpad_qt.core.utils.audio_baker import AudioBaker, DEFAULT_PHRASES, DEFAULT_MODEL_PATH
from simpad_qt.core.utils.audio import AudioAnnouncer


def test_default_phrases_presence():
    expected_keys = ["timing_in_progress", "time_deleted", "lap", "car", "one", "two", "three", "four", "five", "car_clear"]
    for key in expected_keys:
        assert key in DEFAULT_PHRASES


def test_bake_skip_if_file_exists():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        dummy_file = tmp_path / "car.wav"
        dummy_file.write_bytes(b"dummy_wav_content")

        # Must return False because file already exists on disk
        result = AudioBaker.bake_file("Car", dummy_file, force=False)
        assert result is False
        assert dummy_file.read_bytes() == b"dummy_wav_content"


def test_bake_batch_skips_existing():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        # Create all expected files
        for key in DEFAULT_PHRASES.keys():
            (tmp_path / f"{key}.wav").write_bytes(b"dummy")

        baked, skipped = AudioBaker.bake_batch(DEFAULT_PHRASES, output_dir=tmp_path, force=False)
        assert baked == 0
        assert skipped == len(DEFAULT_PHRASES)


@pytest.mark.skipif(not DEFAULT_MODEL_PATH.exists(), reason="ONNX model not found")
def test_bake_real_synthesis():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        out_file = tmp_path / "test_bake.wav"

        baked = AudioBaker.bake_file("One", out_file, model_path=DEFAULT_MODEL_PATH)
        assert baked is True
        assert out_file.exists()
        assert out_file.stat().st_size > 1000

        # Check skip on second call
        baked_again = AudioBaker.bake_file("One", out_file, model_path=DEFAULT_MODEL_PATH, force=False)
        assert baked_again is False


def test_audio_announcer_resolves_files():
    # Assets sound directory should contain baked wav files
    assert AudioAnnouncer._resolve_wav_file("timing_in_progress") is not None
    assert AudioAnnouncer._resolve_wav_file("car") is not None
    assert AudioAnnouncer._resolve_wav_file("car_clear") is not None
