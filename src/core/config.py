import json
from pathlib import Path
from typing import Dict, Any

DEFAULT_CONFIG_PATH = Path("config.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    "abs_threshold": 0.15,
    "tc_threshold": 0.20,
    "lateral_slide_threshold": 0.10,
    "udp_host": "127.0.0.1",
    "udp_port": 5606,
    "update_rate_hz": 100
}


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """Charge la configuration depuis un fichier JSON. Fait un fallback sur les valeurs par défaut."""
    if not config_path.exists():
        save_config(DEFAULT_CONFIG, config_path)
        return DEFAULT_CONFIG.copy()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            # Fusion avec les clés par défaut au cas où certaines soient manquantes
            merged = DEFAULT_CONFIG.copy()
            merged.update(config)
            return merged
    except Exception as e:
        print(f"Erreur lors de la lecture de {config_path}: {e}. Utilisation des valeurs par défaut.")
        return DEFAULT_CONFIG.copy()


def save_config(config: Dict[str, Any], config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Sauvegarde la configuration au format JSON."""
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"Erreur lors de la sauvegarde de {config_path}: {e}")
