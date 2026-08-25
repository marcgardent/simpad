"""
SimPad Qt Overlay Process Manager.
Spawns and manages the standalone PySide6 transparent HUD Overlay subprocess.
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class QtOverlayProcessManager:
    """
    Gestionnaire du sous-processus d'Overlay HUD PySide6.
    Permet à l'application principale de lancer et fermer l'overlay proprement.
    """

    def __init__(self):
        self._process: Optional[subprocess.Popen] = None

    def is_running(self) -> bool:
        """Indique si le sous-processus d'overlay est actif."""
        return self._process is not None and self._process.poll() is None

    def start(self) -> bool:
        """Démarre l'overlay Qt dans un sous-processus isolé."""
        if self.is_running():
            return True

        runner_script = _PROJECT_ROOT / "src" / "gui" / "overlay" / "overlay_runner.py"
        try:
            python_exe = sys.executable
            env = dict(os.environ)
            env["PYTHONPATH"] = str(_PROJECT_ROOT)
            self._process = subprocess.Popen(
                [python_exe, str(runner_script)],
                cwd=str(_PROJECT_ROOT),
                env=env,
            )
            print(f"[QtOverlayProcessManager] Overlay HUD Qt démarré (PID: {self._process.pid}).", flush=True)
            return True
        except Exception as e:
            print(f"[QtOverlayProcessManager] Erreur lors du lancement de l'overlay: {e}", flush=True)
            return False

    def stop(self) -> None:
        """Arrête proprement le sous-processus d'overlay."""
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=1.0)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            finally:
                self._process = None
                print("[QtOverlayProcessManager] Overlay HUD Qt arrêté.", flush=True)
