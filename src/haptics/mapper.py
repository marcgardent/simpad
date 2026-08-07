"""
SimPad Haptic Mapper — Stratégies de routage et de mixage des canaux haptiques logiques.
"""

from abc import ABC, abstractmethod
from typing import Tuple


class HapticChannelMapper(ABC):
    """Interface abstraite pour le mapping des 4 canaux logiques vers les moteurs physiques."""

    @abstractmethod
    def map_channels(
        self, left_low: float, left_high: float, right_low: float, right_high: float
    ) -> Tuple[float, float]:
        """
        Transforme les 4 canaux logiques en intensités pour les moteurs (Basse fréquence, Haute fréquence).
        :return: Tuple (low_freq_intensity, high_freq_intensity) normalisé dans [0.0, 1.0].
        """
        pass


class DirectMixMapper(HapticChannelMapper):
    """
    Mixage additif direct 4 canaux -> 2 moteurs.
    left_low + left_high -> moteur gauche (LF)
    right_low + right_high -> moteur droit (HF)
    """

    def map_channels(
        self, left_low: float, left_high: float, right_low: float, right_high: float
    ) -> Tuple[float, float]:
        lf = min(1.0, max(0.0, left_low + left_high))
        hf = min(1.0, max(0.0, right_low + right_high))
        return lf, hf


class XInputSeparatedMapper(HapticChannelMapper):
    """
    Stratégie spécifique pour contrôleurs 2 moteurs type XInput (Xbox 360 / One / Series).
    Unifie les signaux L/R pour séparer strictement la texture basse fréquence (moteur gauche lourd)
    de la texture haute fréquence (moteur droit léger/rapide).
    """

    def map_channels(
        self, left_low: float, left_high: float, right_low: float, right_high: float
    ) -> Tuple[float, float]:
        unified_low = max(left_low, right_low)
        unified_high = max(left_high, right_high)
        lf = min(1.0, max(0.0, unified_low))
        hf = min(1.0, max(0.0, unified_high))
        return lf, hf
