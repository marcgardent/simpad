from abc import ABC, abstractmethod


class HapticController(ABC):
    """Classe abstraite de base pour le contrôle du retour haptique multicanal."""

    @abstractmethod
    def set_vibration(
        self,
        left_low: float = 0.0,
        left_high: float = 0.0,
        right_low: float = 0.0,
        right_high: float = 0.0,
        duration_ms: int = 0
    ) -> None:
        """
        Définit les intensités haptiques en fréquence pour le côté Gauche et le côté Droit.

        :param left_low: Basse fréquence Côté Gauche (0.0 à 1.0)
        :param left_high: Haute fréquence Côté Gauche (0.0 à 1.0)
        :param right_low: Basse fréquence Côté Droit (0.0 à 1.0)
        :param right_high: Haute fréquence Côté Droit (0.0 à 1.0)
        :param duration_ms: Durée de la vibration en ms
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """Arrête immédiatement toutes les vibrations."""
        pass
