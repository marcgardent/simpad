"""
SimPad Physics — Haptic Processor using Normalized VehicleSensors.
Converts normalized wheel slip ratios into 4 haptic vibration channels.
"""

import math
from typing import Dict, Any, Tuple, Union
from src.telemetry.sensors import VehicleSensors
from src.telemetry.lmu_parser import TelemetryData


def apply_response_curve(raw_intensity: float, gamma: float, gain: float, min_cutoff: float) -> float:
    """Applique une courbe de réponse paramétrique (Gamma/Exposant + Gain + Cutoff)."""
    if raw_intensity < min_cutoff:
        return 0.0

    # Normalisation au-dessus du cutoff
    norm = (raw_intensity - min_cutoff) / max(0.001, 1.0 - min_cutoff)

    # Application de la courbe exponentielle (gamma > 1: progressive, gamma < 1: agressive)
    curved = math.pow(max(0.0, min(1.0, norm)), gamma)

    # Application du gain et saturation à 1.0
    return min(1.0, max(0.0, curved * gain))


class PhysicsToHaptic:
    """
    Processeur physique convertissant les capteurs VehicleSensors en intensités haptiques.
    Gère les 4 effets physiques paramétrables avec courbes de réponse distinctes (Grave et Aigu) :
      1. Blocage de roues (Freinage / ABS)
      2. Survirage (Glissement arrière)
      3. Sousvirage (Glissement avant)
      4. Patinage des roues (Accélération / TC)
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or self.get_default_config()

    @staticmethod
    def get_default_config() -> Dict[str, Any]:
        return {
            # 1. Freinage / Blocage de roues (ABS) — Seuil à 15%
            "lock_threshold": 0.15,
            "lock_low_gamma": 1.0, "lock_low_gain": 0.3, "lock_low_cutoff": 0.0,
            "lock_high_gamma": 1.5, "lock_high_gain": 1.0, "lock_high_cutoff": 0.0,

            # 2. Survirage (Oversteer / Glissement AR) — Seuil à 12%
            "oversteer_threshold": 0.12,
            "oversteer_low_gamma": 1.2, "oversteer_low_gain": 1.0, "oversteer_low_cutoff": 0.0,
            "oversteer_high_gamma": 1.0, "oversteer_high_gain": 0.4, "oversteer_high_cutoff": 0.0,

            # 3. Sousvirage (Understeer / Glissement AV) — Seuil à 10%
            "understeer_threshold": 0.10,
            "understeer_low_gamma": 1.5, "understeer_low_gain": 0.5, "understeer_low_cutoff": 0.0,
            "understeer_high_gamma": 1.0, "understeer_high_gain": 0.8, "understeer_high_cutoff": 0.0,

            # 4. Patinage des roues (TC / Accélération) — Seuil à 18%
            "spin_threshold": 0.18,
            "spin_low_gamma": 1.0, "spin_low_gain": 1.0, "spin_low_cutoff": 0.0,
            "spin_high_gamma": 2.0, "spin_high_gain": 0.2, "spin_high_cutoff": 0.0,
        }

    def update_config(self, new_config: Dict[str, Any]) -> None:
        self.config.update(new_config)

    def process(self, telemetry: Union[VehicleSensors, TelemetryData]) -> Tuple[float, float, float, float]:
        """
        Calcule les intensités vibratoires (left_low, left_high, right_low, right_high)
        à partir des signaux du domaine VehicleSensors.
        """
        s = telemetry.to_sensors() if isinstance(telemetry, TelemetryData) else telemetry

        # 1. FREINAGE / BLOCAGE DE ROUES (ABS) — Roues AV
        lock_thresh = self.config.get("lock_threshold", 0.15)
        raw_lock_g = max(0.0, s.front_left_lock - lock_thresh) / max(0.01, 1.0 - lock_thresh) if s.front_left_lock > lock_thresh else 0.0
        raw_lock_d = max(0.0, s.front_right_lock - lock_thresh) / max(0.01, 1.0 - lock_thresh) if s.front_right_lock > lock_thresh else 0.0

        lock_g_low  = apply_response_curve(raw_lock_g, self.config.get("lock_low_gamma", 1.0), self.config.get("lock_low_gain", 0.3), self.config.get("lock_low_cutoff", 0.0))
        lock_g_high = apply_response_curve(raw_lock_g, self.config.get("lock_high_gamma", 1.5), self.config.get("lock_high_gain", 1.0), self.config.get("lock_high_cutoff", 0.0))
        lock_d_low  = apply_response_curve(raw_lock_d, self.config.get("lock_low_gamma", 1.0), self.config.get("lock_low_gain", 0.3), self.config.get("lock_low_cutoff", 0.0))
        lock_d_high = apply_response_curve(raw_lock_d, self.config.get("lock_high_gamma", 1.5), self.config.get("lock_high_gain", 1.0), self.config.get("lock_high_cutoff", 0.0))

        # 2. SURVIRAGE / OVERSTEER — Roues AR
        over_thresh = self.config.get("oversteer_threshold", 0.12)
        raw_over_g = max(0.0, s.rear_left_lat_slip - over_thresh) / max(0.01, 1.0 - over_thresh) if s.rear_left_lat_slip > over_thresh else 0.0
        raw_over_d = max(0.0, s.rear_right_lat_slip - over_thresh) / max(0.01, 1.0 - over_thresh) if s.rear_right_lat_slip > over_thresh else 0.0

        over_g_low  = apply_response_curve(raw_over_g, self.config.get("oversteer_low_gamma", 1.2), self.config.get("oversteer_low_gain", 1.0), self.config.get("oversteer_low_cutoff", 0.0))
        over_g_high = apply_response_curve(raw_over_g, self.config.get("oversteer_high_gamma", 1.0), self.config.get("oversteer_high_gain", 0.4), self.config.get("oversteer_high_cutoff", 0.0))
        over_d_low  = apply_response_curve(raw_over_d, self.config.get("oversteer_low_gamma", 1.2), self.config.get("oversteer_low_gain", 1.0), self.config.get("oversteer_low_cutoff", 0.0))
        over_d_high = apply_response_curve(raw_over_d, self.config.get("oversteer_high_gamma", 1.0), self.config.get("oversteer_high_gain", 0.4), self.config.get("oversteer_high_cutoff", 0.0))

        # 3. SOUSVIRAGE / UNDERSTEER — Roues AV
        under_thresh = self.config.get("understeer_threshold", 0.10)
        raw_under_g = max(0.0, s.front_left_lat_slip - under_thresh) / max(0.01, 1.0 - under_thresh) if s.front_left_lat_slip > under_thresh else 0.0
        raw_under_d = max(0.0, s.front_right_lat_slip - under_thresh) / max(0.01, 1.0 - under_thresh) if s.front_right_lat_slip > under_thresh else 0.0

        under_g_low  = apply_response_curve(raw_under_g, self.config.get("understeer_low_gamma", 1.5), self.config.get("understeer_low_gain", 0.5), self.config.get("understeer_low_cutoff", 0.0))
        under_g_high = apply_response_curve(raw_under_g, self.config.get("understeer_high_gamma", 1.0), self.config.get("understeer_high_gain", 0.8), self.config.get("understeer_high_cutoff", 0.0))
        under_d_low  = apply_response_curve(raw_under_d, self.config.get("understeer_low_gamma", 1.5), self.config.get("understeer_low_gain", 0.5), self.config.get("understeer_low_cutoff", 0.0))
        under_d_high = apply_response_curve(raw_under_d, self.config.get("understeer_high_gamma", 1.0), self.config.get("understeer_high_gain", 0.8), self.config.get("understeer_high_cutoff", 0.0))

        # 4. PATINAGE / TC — Roues AR
        spin_thresh = self.config.get("spin_threshold", 0.18)
        raw_spin_g = max(0.0, s.rear_left_spin - spin_thresh) / max(0.01, 1.0 - spin_thresh) if s.rear_left_spin > spin_thresh else 0.0
        raw_spin_d = max(0.0, s.rear_right_spin - spin_thresh) / max(0.01, 1.0 - spin_thresh) if s.rear_right_spin > spin_thresh else 0.0

        spin_g_low  = apply_response_curve(raw_spin_g, self.config.get("spin_low_gamma", 1.0), self.config.get("spin_low_gain", 1.0), self.config.get("spin_low_cutoff", 0.0))
        spin_g_high = apply_response_curve(raw_spin_g, self.config.get("spin_high_gamma", 2.0), self.config.get("spin_high_gain", 0.2), self.config.get("spin_high_cutoff", 0.0))
        spin_d_low  = apply_response_curve(raw_spin_d, self.config.get("spin_low_gain", 1.0), self.config.get("spin_low_cutoff", 0.0))
        spin_d_high = apply_response_curve(raw_spin_d, self.config.get("spin_high_gamma", 2.0), self.config.get("spin_high_gain", 0.2), self.config.get("spin_high_cutoff", 0.0))

        # MIXAGE CANAUX (MAX)
        left_low   = min(1.0, max(lock_g_low,  over_g_low,  under_g_low,  spin_g_low))
        left_high  = min(1.0, max(lock_g_high, over_g_high, under_g_high, spin_g_high))
        right_low  = min(1.0, max(lock_d_low,  over_d_low,  under_d_low,  spin_d_low))
        right_high = min(1.0, max(lock_d_high, over_d_high, under_d_high, spin_d_high))

        return left_low, left_high, right_low, right_high
