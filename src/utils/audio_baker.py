"""
SimPad Audio Baker — Synthesize voice sound clips using Piper TTS and ONNX models.
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

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_MODEL_PATH = _PROJECT_ROOT / "assets" / "models" / "en_GB-alan-low.onnx"
DEFAULT_SOUND_DIR = _PROJECT_ROOT / "assets" / "sound"

# Official remote URL fallback for config JSON if missing
MODEL_CONFIG_URLS = {
    "en_GB-alan-low.onnx": "https://huggingface.co/rhasspy/piper-voices/raw/main/en/en_GB/alan/low/en_GB-alan-low.onnx.json"
}

# Standard dictionary of phrases requested for SimPad
DEFAULT_PHRASES: Dict[str, str] = {
    "clean_lap": "Clean lap",
    "dirty_lap": "Dirty lap",
    "lap": "Lap",
    "car": "Car",
    "one": "One",
    "two": "Two",
    "three": "Three",
    "four": "Four",
    "five": "Five",
    "car_clear": "Car clear",
}


class AudioBaker:
    """
    Gestionnaire de génération (bake) de fichiers audio TTS via Piper.
    - Vérification d'existence sur disque pour ne baker que ce qui manque.
    - Barre de progression tqdm détaillée.
    - Synthèse à la demande (on-demand).
    - Post-traitement audio : padding silence (anti-coupure DAC) et rééchantillonnage 44.1 kHz.
    """

    _cached_voice = None
    _cached_model_path: Optional[str] = None

    @classmethod
    def ensure_model_config(cls, model_path: Path) -> Path:
        """
        Vérifie la présence du fichier de configuration .onnx.json associé au modèle.
        S'il est absent, tente de le télécharger automatiquement depuis le dépôt officiel Piper.
        """
        config_path = model_path.with_name(f"{model_path.name}.json")
        if not config_path.exists():
            model_filename = model_path.name
            if model_filename in MODEL_CONFIG_URLS:
                url = MODEL_CONFIG_URLS[model_filename]
                logger.info(f"[AudioBaker] Config JSON manquante pour {model_filename}, téléchargement depuis {url}...")
                print(f"[AudioBaker] Downloading missing model config: {config_path.name} ...")
                urllib.request.urlretrieve(url, config_path)
            else:
                raise FileNotFoundError(
                    f"Le fichier de configuration {config_path} est introuvable pour le modèle {model_path}."
                )
        return config_path

    @classmethod
    def get_voice(cls, model_path: Optional[Path] = None):
        """
        Charge et met en cache l'instance PiperVoice pour des synthèses ultra-rapides en mémoire.
        """
        try:
            from piper.voice import PiperVoice
        except ImportError as e:
            raise ImportError(
                "Le paquet 'piper-tts' n'est pas installé dans l'environnement Python. "
                "Installez-le avec: pip install piper-tts"
            ) from e

        model_p = Path(model_path or DEFAULT_MODEL_PATH).resolve()
        if not model_p.exists():
            raise FileNotFoundError(f"Modèle ONNX introuvable à l'emplacement : {model_p}")

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
        Génère un fichier audio WAV optimisé pour le texte donné.
        Si le fichier existe déjà et force=False, la génération est ignorée (cache disque).
        Ajoute un silence de sécurité (padding) et rééchantillonne en 44.1 kHz pour une compatibilité audio maximale.
        Retourne True si le fichier a été généré, False s'il existait déjà.
        """
        output_path = Path(output_path)

        if output_path.exists() and not force:
            return False

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if voice is None:
            voice = cls.get_voice(model_path)

        # Synthèse brute via Piper
        chunks = list(voice.synthesize(text))
        if not chunks:
            logger.warning(f"[AudioBaker] Aucun chunk audio généré pour '{text}'")
            return False

        orig_sr = voice.config.sample_rate
        raw_bytes = b"".join(chunk.audio_int16_bytes for chunk in chunks)
        samples = np.frombuffer(raw_bytes, dtype=np.int16)

        # Padding silence (évite que les DACs / périphériques Bluetooth ou HDMI ne tronquent le son)
        if pad_silence_sec > 0:
            silence_samples = int(orig_sr * pad_silence_sec)
            silence = np.zeros(silence_samples, dtype=np.int16)
            samples = np.concatenate([silence, samples, silence])

        # Rééchantillonnage de haute qualité vers target_sample_rate (44.1 kHz standard)
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
        Vérifie si le fichier audio existe sur le disque.
        S'il n'existe pas, le génère à la demande immédiatement et retourne le chemin vers le fichier .wav.
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
        Génère un lot de phrases avec une barre de progression tqdm.
        Seuls les fichiers absents du disque sont générés (sauf si force=True).

        Retourne un tuple (nb_baked, nb_skipped).
        """
        items = phrases or DEFAULT_PHRASES
        out_dir = Path(output_dir or DEFAULT_SOUND_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Détection préalable des fichiers à générer
        to_bake = []
        for key, text in items.items():
            wav_path = out_dir / f"{key}.wav"
            if not wav_path.exists() or force:
                to_bake.append((key, text, wav_path))

        baked_count = 0
        skipped_count = len(items) - len(to_bake)

        # Si aucun fichier à générer, on affiche l'information directement
        if not to_bake:
            print(f"[AudioBaker] Tous les fichiers ({len(items)}) sont déjà présents sur le disque. Rien à générer.")
            return baked_count, skipped_count

        # Chargement unique du modèle en mémoire
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
