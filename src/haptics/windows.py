"""
SimPad Haptic Middleware — Implémentation Windows / XInput avec séparation spatiale des fréquences.
"""

from src.haptics.sdl3_controller import SDL3HapticController
from src.haptics.mapper import XInputSeparatedMapper


class WindowsHapticController(SDL3HapticController):
    """
    Implémentation haptique Windows via SDL3 avec stratégie XInput.
    Combine les signaux L/R pour router la basse fréquence vers le moteur lourd gauche
    et la haute fréquence vers le moteur léger droit.
    """

    def __init__(self, device_index: int = 0, invert_sides: bool = False):
        super().__init__(
            device_index=device_index,
            invert_sides=invert_sides,
            mapper=XInputSeparatedMapper(),
        )
