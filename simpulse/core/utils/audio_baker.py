"""
SimPulse Audio Baker — Synthesize voice sound clips using Piper TTS and ONNX models.
Provides caching (skips existing files), progress bar tracking (tqdm),
audio padding (prevents DAC word clipping), and high-compatibility 44.1kHz output.
"""

import os
import wave
import urllib.request
import logging
import numpy as np
from pathlib import Path
from typing import Optional, Dict, Tuple
from tqdm import tqdm

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_MODEL_PATH = _PROJECT_ROOT / "assets" / "models" / "en_GB-alan-low.onnx"
DEFAULT_SOUND_DIR = _PROJECT_ROOT / "assets" / "sound"

# Official remote URL fallback for config JSON if missing
MODEL_CONFIG_URLS = {
    "en_GB-alan-low.onnx": "https://huggingface.co/rhasspy/piper-voices/raw/main/en/en_GB/alan/low/en_GB-alan-low.onnx.json"
}

DEFAULT_PHRASES: Dict[str, str] = {
    # Lap & Spotter Announcements
    "timing_in_progress": "Timing in progress",
    "time_deleted": "Time deleted",
    "dirty_lap": "Dirty lap",
    "give_time_back": "Cut track, give time back",
    "under_investigation": "Under investigation, lift",
    "incident_cleared": "Incident cleared",
    "time_cleared": "Time given back, cleared",
    "no_penalty": "No penalty",
    "lap_deleted": "Lap deleted",
    "lap_invalidated": "Lap invalidated",
    "penalty_applied": "Penalty applied",
    "lap": "Lap",
    "car": "Car",
    "car_clear": "Car clear",
    "incoming": "Incoming",
    "traffic_5": "Traffic five",
    "alongside": "Alongside",
    "overlap": "Overlap",
    "clear": "Clear",
    "car_left": "Car left",
    "car_right": "Car right",
    "clear_left": "Clear left",
    "clear_right": "Clear right",
    "clear_all_round": "Clear all round",
    "still_there": "Still there",
    "three_wide": "Three wide",
    "three_wide_left": "Three wide on the left",
    "three_wide_right": "Three wide on the right",
    "car_inside": "Car inside",
    "car_outside": "Car outside",
    "clear_inside": "Clear inside",
    "clear_outside": "Clear outside",
    "three_wide_inside": "Three wide on the inside",
    "three_wide_outside": "Three wide on the outside",
    "spotter_enabled": "Spotter enabled",
    "spotter_disabled": "Spotter disabled",

    # Gear Numbers (1 to 8)
    "one": "One",
    "two": "Two",
    "three": "Three",
    "four": "Four",
    "five": "Five",
    "six": "Six",
    "seven": "Seven",
    "eight": "Eight",

    # Reference Lap & Pace Notes Annotations
    "brake": "Brake",
    "turn": "Turn",

    # Official LMU Timings & Status Announcements
    "registration_open": "Registration is open",
    "race_starting": "Race is starting",
    "fifteen_minutes": "Fifteen minutes remaining",
    "ten_minutes": "Ten minutes remaining",
    "five_minutes": "Five minutes remaining",
    "one_minute": "One minute remaining",

    # LMU Official Series Names (Setups)
    "lmgt3_fixed": "LMGT3 Fixed",
    "lmp3_fixed": "LMP3 Fixed",
    "lmgte_fixed": "LMGTE Fixed",
    "elms_sprint_trophy": "ELMS Sprint Trophy",
    "lmgt3_sprint_cup": "LMGT3 Sprint Cup",
    "prototype_classic": "Prototype Classic",
    "one_stint_sprint": "One Stint Sprint",
    "elms_super_60": "ELMS Super Sixty",
    "wec_xperience": "WEC Experience",
    "wec_weekly": "WEC Weekly",

    # Gear Announcements G1 to G8 (segregated from spotter countdown)
    **{f"gear_{i}": f"Gear {i}" for i in range(1, 9)},

    # Turns T1 to T30 (compressed dynamic generation)
    **{f"turn_{i}": f"Turn {i}" for i in range(1, 31)},
}


class AudioBaker:
    """
    Manager for generating (baking) TTS audio files via Piper.
    - Checks disk existence to only bake missing files.
    - Detailed tqdm progress bar.
    - On-demand synthesis.
    - Audio post-processing: silence padding (anti-DAC clipping) and 44.1 kHz resampling.
    """

    _cached_voice = None
    _cached_model_path: Optional[str] = None

    @classmethod
    def ensure_model_config(cls, model_path: Path) -> Path:
        """
        Checks presence of .onnx.json config file associated with the model.
        If missing, attempts to download it automatically from official Piper repository.
        """
        config_path = model_path.with_name(f"{model_path.name}.json")
        if not config_path.exists():
            model_filename = model_path.name
            if model_filename in MODEL_CONFIG_URLS:
                url = MODEL_CONFIG_URLS[model_filename]
                logger.info(f"[AudioBaker] Missing JSON config for {model_filename}, downloading from {url}...")
                print(f"[AudioBaker] Downloading missing model config: {config_path.name} ...")
                urllib.request.urlretrieve(url, config_path)
            else:
                raise FileNotFoundError(
                    f"Configuration file {config_path} not found for model {model_path}."
                )
        return config_path

    @classmethod
    def get_voice(cls, model_path: Optional[Path] = None):
        """
        Loads and caches PiperVoice instance for fast in-memory synthesis.
        """
        try:
            from piper.voice import PiperVoice
        except ImportError as e:
            raise ImportError(
                "Package 'piper-tts' is not installed in the Python environment. "
                "Install it with: pip install piper-tts"
            ) from e

        model_p = Path(model_path or DEFAULT_MODEL_PATH).resolve()
        if not model_p.exists():
            raise FileNotFoundError(f"ONNX model not found at path: {model_p}")

        cls.ensure_model_config(model_p)

        str_path = str(model_p)
        if cls._cached_voice is None or cls._cached_model_path != str_path:
            cls._cached_voice = PiperVoice.load(str_path)
            cls._cached_model_path = str_path

        return cls._cached_voice

    @classmethod
    def bake_file(
        cls,
        text: str,
        output_path: Path,
        model_path: Optional[Path] = None,
        force: bool = False,
        voice=None,
        target_sample_rate: int = 44100,
        pad_silence_sec: float = 0.08,
    ) -> bool:
        """
        Generates an optimized WAV audio file for the given text.
        If file already exists and force=False, generation is skipped (disk cache).
        Adds security silence (padding) and resamples to 44.1 kHz for maximum audio compatibility.
        Returns True if file was generated, False if it already existed.
        """
        output_path = Path(output_path)

        if output_path.exists() and not force:
            return False

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if voice is None:
            voice = cls.get_voice(model_path)

        # Raw synthesis via Piper
        chunks = list(voice.synthesize(text))
        if not chunks:
            logger.warning(f"[AudioBaker] No audio chunks generated for '{text}'")
            return False

        orig_sr = voice.config.sample_rate
        raw_bytes = b"".join(chunk.audio_int16_bytes for chunk in chunks)
        samples = np.frombuffer(raw_bytes, dtype=np.int16)

        # Silence padding (prevents DACs / Bluetooth / HDMI devices from clipping audio)
        if pad_silence_sec > 0:
            silence_samples = int(orig_sr * pad_silence_sec)
            silence = np.zeros(silence_samples, dtype=np.int16)
            samples = np.concatenate([silence, samples, silence])

        # High quality resampling towards target_sample_rate (44.1 kHz standard)
        if target_sample_rate and target_sample_rate != orig_sr and len(samples) > 0:
            num_target_samples = int(len(samples) * target_sample_rate / orig_sr)
            processed_samples = np.interp(
                np.linspace(0, len(samples), num_target_samples, endpoint=False),
                np.arange(len(samples)),
                samples,
            ).astype(np.int16)
            final_sr = target_sample_rate
        else:
            processed_samples = samples
            final_sr = orig_sr

        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setframerate(final_sr)
            wav_file.setsampwidth(2)
            wav_file.setnchannels(1)
            wav_file.writeframes(processed_samples.tobytes())

        return True

    @classmethod
    def bake_on_demand(
        cls,
        phrase_key: str,
        text: Optional[str] = None,
        output_dir: Optional[Path] = None,
        model_path: Optional[Path] = None,
        force: bool = False,
    ) -> Path:
        """
        Checks if audio file exists on disk.
        If missing, generates it immediately on-demand and returns the path to the .wav file.
        """
        out_dir = Path(output_dir or DEFAULT_SOUND_DIR)
        wav_path = out_dir / f"{phrase_key}.wav"

        if not wav_path.exists() or force:
            phrase_text = text or DEFAULT_PHRASES.get(phrase_key, phrase_key.replace("_", " ").capitalize())
            cls.bake_file(phrase_text, wav_path, model_path=model_path, force=force)

        return wav_path

    @classmethod
    def bake_batch(
        cls,
        phrases: Optional[Dict[str, str]] = None,
        output_dir: Optional[Path] = None,
        model_path: Optional[Path] = None,
        force: bool = False,
    ) -> Tuple[int, int]:
        """
        Generates a batch of phrases with a tqdm progress bar.
        Only files missing from disk are generated (unless force=True).

        Returns tuple (nb_baked, nb_skipped).
        """
        items = phrases or DEFAULT_PHRASES
        out_dir = Path(output_dir or DEFAULT_SOUND_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Pre-detection of files to bake
        to_bake = []
        for key, text in items.items():
            wav_path = out_dir / f"{key}.wav"
            if not wav_path.exists() or force:
                to_bake.append((key, text, wav_path))

        baked_count = 0
        skipped_count = len(items) - len(to_bake)

        # If no file to generate, display message directly
        if not to_bake:
            print(f"[AudioBaker] All files ({len(items)}) are already on disk. Nothing to generate.")
            return baked_count, skipped_count

        # Load voice model in memory once
        voice = cls.get_voice(model_path)

        pbar = tqdm(
            to_bake,
            desc="Baking audios (Piper TTS)",
            unit="file",
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}] {postfix}",
        )

        for key, text, wav_path in pbar:
            pbar.set_postfix_str(f"'{key}' -> '{text}'")
            cls.bake_file(text, wav_path, force=True, voice=voice)
            baked_count += 1

        pbar.close()
        return baked_count, skipped_count
