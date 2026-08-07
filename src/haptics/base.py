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
        duration_ms: int = 0,
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

    @abstractmethod
    def close(self) -> None:
        """Libère les ressources matérielles."""
        pass

    def is_connected(self) -> bool:
        """Vérifie si un périphérique haptique est connecté."""
        return False

    def get_gamepad_name(self) -> str:
        """Retourne le nom de la manette détectée."""
        return "Inconnu"

    def get_axis(self, axis: int) -> float:
        """Lit un axe normalisé entre -1.0 et 1.0."""
        return 0.0

    def get_left_stick_x(self) -> float:
        """Axe horizontal du stick gauche [-1.0, 1.0]."""
        return 0.0

    def get_button(self, button: int) -> bool:
        """Lit l'état d'un bouton."""
        return False

    def get_south_button(self) -> bool:
        """Bouton principal sud (A / Croix)."""
        return False
