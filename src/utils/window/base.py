"""
SimPad Window Management — Base Abstract Window Manager.
Defines the interface for cross-platform window state, foreground process tracking, and overlay management.
"""

from abc import ABC, abstractmethod


class BaseWindowManager(ABC):
    """Classe abstraite de base pour la gestion des fenêtres et processus selon le système d'exploitation."""

    def __init__(self):
        self._focus_listeners = []

    def add_focus_listener(self, callback) -> None:
        """Enregistre un callback réactif appelé immédiatement lors d'un changement de focus de fenêtre."""
        if callback not in self._focus_listeners:
            self._focus_listeners.append(callback)

    def remove_focus_listener(self, callback) -> None:
        """Détache un callback réactif."""
        if callback in self._focus_listeners:
            self._focus_listeners.remove(callback)

    def _notify_focus_changed(self) -> None:
        """Déclenche immédiatement tous les écouteurs de focus enregistrés."""
        for cb in list(self._focus_listeners):
            try:
                cb()
            except Exception:
                pass

    @abstractmethod
    def get_foreground_window_title(self) -> str:
        """Retourne le titre de la fenêtre active au premier plan."""
        return ""

    @abstractmethod
    def get_foreground_process_name(self) -> str:
        """Retourne le nom de l'exécutable du processus actif au premier plan."""
        return ""

    def is_lmu_running(self) -> bool:
        """Vérifie si le processus du jeu LMU est en cours d'exécution sur le système."""
        return False

    def is_lmu_foreground(self) -> bool:
        """
        Vérifie si le jeu Le Mans Ultimate (LMU) est actuellement la fenêtre active au premier plan.
        """
        proc_name = self.get_foreground_process_name().lower()
        if proc_name in ("lemansultimate.exe", "rfactor2.exe", "lemansultimate", "rfactor2"):
            return True

        title = self.get_foreground_window_title().lower().strip()
        if "le mans" in title or "lemans" in title or "rfactor" in title:
            return True

        # L'overlay HUD transparent uniquement (pas la console Studio parente)
        if "hud overlay" in title:
            return True

        return False

    def get_lmu_window_status(self) -> str:
        """
        Retourne l'état précis du jeu LMU :
        - 'foreground'  : Le jeu est lancé et actif au premier plan.
        - 'background'  : Le jeu est lancé mais en arrière-plan.
        - 'not_running' : Le jeu n'est pas lancé.
        """
        if self.is_lmu_foreground():
            return "foreground"
        if self.is_lmu_running():
            return "background"
        return "not_running"

    def make_transparent_overlay(self, window_title: str) -> bool:
        """Active la transparence de fond sur la fenêtre spécifiée (Spécifique OS)."""
        return False

    def force_viewport_fullscreen_overlay(self, window_title: str) -> bool:
        """Passe la fenêtre en overlay plein écran transparent avec clic traversant."""
        try:
            import dearpygui.dearpygui as dpg
            dpg.configure_viewport(0, decorated=False, always_on_top=True)
            dpg.maximize_viewport()
            return True
        except Exception:
            return False

    def restore_viewport_windowed(self, window_title: str) -> bool:
        """Restaure la fenêtre en mode fenêtré console avec décorations."""
        try:
            import dearpygui.dearpygui as dpg
            dpg.configure_viewport(0, decorated=True, always_on_top=False)
            dpg.maximize_viewport()
            return True
        except Exception:
            return False
