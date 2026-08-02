import os
import time
import ctypes
import threading
import logging
from ctypes import (
    c_bool, c_int, c_int16, c_uint16, c_uint32, c_void_p, c_char_p, POINTER
)
from pathlib import Path
from typing import Optional

from src.haptics.base import HapticController

logger = logging.getLogger(__name__)

# ─── SDL3 flags / constantes ─────────────────────────────────────────────────
SDL_INIT_GAMEPAD   = 0x00000200
SDL_RUMBLE_MAX_U16 = 0xFFFF          # plage uint16 pour SDL_RumbleGamepad

# ─── Racine du projet (src/haptics/ → ../../) ────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _find_sdl3() -> Optional[str]:
    """
    Cherche SDL3.dll dans cet ordre :
      1. Racine du projet  (là où l'utilisateur l'a déposée)
      2. Répertoire courant (CWD)
      3. PATH système (LoadLibrary trouvera seul)
    Retourne le chemin absolu si trouvé localement, sinon "SDL3.dll" (PATH).
    """
    candidates = [
        _PROJECT_ROOT / "SDL3.dll",
        Path.cwd() / "SDL3.dll",
    ]
    for p in candidates:
        if p.exists():
            abs_p = p.resolve()
            logger.debug(f"SDL3.dll trouvée : {abs_p}")
            try:
                os.add_dll_directory(str(abs_p.parent))
            except Exception:
                pass
            return str(abs_p)
    return "SDL3.dll"  # fallback : on laisse Windows chercher dans le PATH


class SDL3HapticController(HapticController):
    """
    Retour haptique via SDL3 (SDL3.dll).

    SDL3 utilise le backend GameInput de Microsoft sur Windows 11, qui supporte
    les contrôleurs modernes avec deux moteurs symétriques pleine fréquence,
    sans les limitations de l'API XInput (Xbox 360).

    Prérequis : SDL3.dll dans le PATH ou à côté de l'exécutable.
    Téléchargement : https://github.com/libsdl-org/SDL/releases

    Mapping 4 canaux logiques → 2 moteurs physiques :
      left_low  + left_high  →  low_frequency_rumble  (moteur gauche, 0–65535)
      right_low + right_high →  high_frequency_rumble (moteur droit,  0–65535)

    Mix ADDITIF : les deux textures (grave et aiguë) coexistent sur chaque moteur.
    """

    def __init__(self, device_index: int = 0, invert_sides: bool = False):
        self.device_index = device_index
        self.invert_sides = invert_sides
        self._lock = threading.Lock()

        # Consignes 4 canaux (0.0 à 1.0)
        self.left_low   = 0.0   # Grave Gauche  (TC / Traction)
        self.left_high  = 0.0   # Aigu Gauche   (ABS / Freinage)
        self.right_low  = 0.0   # Grave Droit   (TC / Traction)
        self.right_high = 0.0   # Aigu Droit    (ABS / Freinage)

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._sdl    = None      # handle SDL3.dll
        self._gamepad: Optional[int] = None  # SDL_Gamepad*

        self._init_sdl()

    # ── Initialisation ─────────────────────────────────────────────────────

    def _init_sdl(self):
        """Charge SDL3.dll, active le hint GameInput, initialise le sous-système Gamepad."""
        sdl3_path = _find_sdl3()
        try:
            self._sdl = ctypes.windll.LoadLibrary(sdl3_path)
            self._setup_functions()

            # Active explicitement le backend GameInput sur Windows
            self._sdl.SDL_SetHint(b"SDL_JOYSTICK_GAMEINPUT", b"1")

            ok = self._sdl.SDL_Init(SDL_INIT_GAMEPAD)
            if not ok:
                err = self._sdl.SDL_GetError()
                logger.error(
                    f"SDL_Init(SDL_INIT_GAMEPAD) échoué : "
                    f"{err.decode(errors='replace') if err else '?'}"
                )
            else:
                logger.info(f"SDL3 initialisé depuis « {sdl3_path} » (backend GameInput activé).")

        except OSError as e:
            logger.error(
                f"Impossible de charger SDL3.dll (cherché dans : {sdl3_path}) : {e}\n"
                f"  → Place SDL3.dll à la racine du projet : {_PROJECT_ROOT}"
            )

        # Direct synchronous rumble execution — no background modulation thread conflict

    def _setup_functions(self):
        """Déclare les prototypes ctypes des fonctions SDL3 utilisées."""
        s = self._sdl

        s.SDL_SetHint.restype   = c_bool
        s.SDL_SetHint.argtypes  = [c_char_p, c_char_p]

        s.SDL_Init.restype      = c_bool
        s.SDL_Init.argtypes     = [c_uint32]

        s.SDL_Quit.restype      = None
        s.SDL_Quit.argtypes     = []

        s.SDL_GetError.restype  = c_char_p
        s.SDL_GetError.argtypes = []

        s.SDL_PumpEvents.restype  = None
        s.SDL_PumpEvents.argtypes = []

        # SDL_JoystickID* SDL_GetGamepads(int *count)
        # Retourne un tableau alloué par SDL — libérer avec SDL_free
        s.SDL_GetGamepads.restype  = POINTER(c_uint32)   # SDL_JoystickID = Uint32
        s.SDL_GetGamepads.argtypes = [POINTER(c_int)]

        s.SDL_free.restype  = None
        s.SDL_free.argtypes = [c_void_p]

        # SDL_Gamepad* SDL_OpenGamepad(SDL_JoystickID instance_id)
        s.SDL_OpenGamepad.restype  = c_void_p
        s.SDL_OpenGamepad.argtypes = [c_uint32]

        s.SDL_CloseGamepad.restype  = None
        s.SDL_CloseGamepad.argtypes = [c_void_p]

        # const char* SDL_GetGamepadName(SDL_Gamepad*)
        s.SDL_GetGamepadName.restype  = c_char_p
        s.SDL_GetGamepadName.argtypes = [c_void_p]

        # bool SDL_RumbleGamepad(SDL_Gamepad*, Uint16 lf, Uint16 hf, Uint32 duration_ms)
        s.SDL_RumbleGamepad.restype  = c_bool
        s.SDL_RumbleGamepad.argtypes = [c_void_p, c_uint16, c_uint16, c_uint32]

        # Sint16 SDL_GetGamepadAxis(SDL_Gamepad*, SDL_GamepadAxis axis)
        # Axis indices: LEFTX=0, LEFTY=1, RIGHTX=2, RIGHTY=3, LTRIGGER=4, RTRIGGER=5
        s.SDL_GetGamepadAxis.restype  = c_int16
        s.SDL_GetGamepadAxis.argtypes = [c_void_p, c_int]

        # bool SDL_GetGamepadButton(SDL_Gamepad*, SDL_GamepadButton button)
        # Button indices: SOUTH=0 (A/Cross), EAST=1 (B/Circle),
        #                 WEST=2 (X/Square), NORTH=3 (Y/Triangle)
        s.SDL_GetGamepadButton.restype  = c_bool
        s.SDL_GetGamepadButton.argtypes = [c_void_p, c_int]

    # ── Acquisition / libération du gamepad ────────────────────────────────

    def _acquire_gamepad(self) -> bool:
        """
        Ouvre le gamepad à l'indice device_index parmi ceux reconnus par SDL3.
        Retourne True si un gamepad est disponible.
        """
        if self._gamepad:
            return True
        if not self._sdl:
            return False

        try:
            self._sdl.SDL_PumpEvents()  # rafraîchit la liste des périphériques

            count = c_int(0)
            ids_ptr = self._sdl.SDL_GetGamepads(ctypes.byref(count))

            if not ids_ptr or count.value == 0:
                return False  # aucun gamepad connecté

            # Clamp device_index si l'utilisateur demande un indice hors range
            idx = min(self.device_index, count.value - 1)
            instance_id = ids_ptr[idx]
            self._sdl.SDL_free(ctypes.cast(ids_ptr, c_void_p))

            gamepad = self._sdl.SDL_OpenGamepad(instance_id)
            if not gamepad:
                err = self._sdl.SDL_GetError()
                logger.warning(
                    f"SDL_OpenGamepad(#{idx}) échoué : "
                    f"{err.decode(errors='replace') if err else '?'}"
                )
                return False

            name_b = self._sdl.SDL_GetGamepadName(gamepad)
            name   = name_b.decode(errors='replace') if name_b else "Inconnu"
            self._gamepad_name = name
            logger.info(f"Gamepad ouvert : « {name} » (SDL_Gamepad* = 0x{gamepad:016X})")

            self._gamepad = gamepad
            return True

        except Exception as exc:
            logger.debug(f"_acquire_gamepad : {exc}")
            return False

    def is_connected(self) -> bool:
        """Vérifie si la manette est connectée et ouverte."""
        if self._gamepad is not None:
            return True
        return self._acquire_gamepad()

    def get_gamepad_name(self) -> str:
        """Retourne le nom de la manette détectée."""
        if self.is_connected():
            return getattr(self, '_gamepad_name', 'Manette Détectée')
        return "Aucune Manette"

    def get_axis(self, axis: int) -> float:
        """
        Read a gamepad axis and return a normalised float in [-1.0, 1.0].
        Protected with self._lock for thread safety against background rumble.
        """
        with self._lock:
            if not self._acquire_gamepad() or not self._sdl:
                return 0.0
            try:
                self._sdl.SDL_PumpEvents()
                raw = self._sdl.SDL_GetGamepadAxis(self._gamepad, axis)
                return max(-1.0, raw / 32767.0)
            except Exception:
                return 0.0

    def get_left_stick_x(self) -> float:
        """Left stick horizontal axis normalised to [-1.0, 1.0]."""
        return self.get_axis(0)

    def get_button(self, button: int) -> bool:
        """
        Read a gamepad button state.
        Protected with self._lock for thread safety against background rumble.
        """
        with self._lock:
            if not self._acquire_gamepad() or not self._sdl:
                return False
            try:
                self._sdl.SDL_PumpEvents()
                return bool(self._sdl.SDL_GetGamepadButton(self._gamepad, button))
            except Exception:
                return False

    def get_south_button(self) -> bool:
        """A (Xbox) / Cross (PS) button — used as test-mode trigger."""
        return self.get_button(0)


    def _close_gamepad(self):
        if self._gamepad and self._sdl:
            try:
                self._sdl.SDL_CloseGamepad(self._gamepad)
            except Exception:
                pass
        self._gamepad = None


    # ── Envoi rumble ───────────────────────────────────────────────────────

    def _send_rumble(self, lf: float, hf: float, duration_ms: int = 50) -> None:
        """
        Envoie les intensités via SDL_RumbleGamepad avec durée dynamique exacte.

        lf [0.0–1.0] → low_frequency_rumble  (moteur gauche, uint16)
        hf [0.0–1.0] → high_frequency_rumble (moteur droit,  uint16)
        """
        if not self._acquire_gamepad():
            return

        try:
            lf_u16 = int(lf * SDL_RUMBLE_MAX_U16)
            hf_u16 = int(hf * SDL_RUMBLE_MAX_U16)
            dur = 10 if (lf_u16 == 0 and hf_u16 == 0) else max(20, int(duration_ms))

            ok = self._sdl.SDL_RumbleGamepad(self._gamepad, lf_u16, hf_u16, dur)
            if not ok:
                err = self._sdl.SDL_GetError()
                logger.warning(f"SDL_RumbleGamepad error: {err.decode(errors='replace') if err else '?'}")

        except Exception as exc:
            logger.warning(f"_send_rumble exception : {exc}")
            self._close_gamepad()

    # ── Thread de modulation ───────────────────────────────────────────────

    def _start_modulation_thread(self):
        self._running = True
        self._thread = threading.Thread(target=self._modulation_loop, daemon=True)
        self._thread.start()

    def _modulation_loop(self):
        """
        Boucle de rendu haptique à 100 Hz.

        Passage DIRECT des valeurs physiques aux moteurs — sans modulation artificielle.

        C'est ce que font les jeux de simulation (LMU, iRacing, ACC…) :
        la variation temporelle (pulsations ABS, secousses TC) provient de la
        télémétrie elle-même, pas d'un filtre logiciel surimposé.

        Mapping :
          l_low  (TC roue AV-G)  ┐
          l_high (ABS roue AR-G) ┘ → low_frequency_rumble  (moteur gauche)

          r_low  (TC roue AV-D)  ┐
          r_high (ABS roue AR-D) ┘ → high_frequency_rumble (moteur droit)
        """
        last_lf = last_hf = -1.0

        while self._running:
            with self._lock:
                l_low  = self.left_low
                l_high = self.left_high
                r_low  = self.right_low
                r_high = self.right_high

            # Arrêt immédiat si tout est à zéro
            if l_low == 0.0 and l_high == 0.0 and r_low == 0.0 and r_high == 0.0:
                if last_lf != 0.0 or last_hf != 0.0:
                    self._send_rumble(0.0, 0.0)
                    last_lf = last_hf = 0.0
                time.sleep(0.01)
                continue

            # Mapping direct physique → moteur (addition, clip à 1.0)
            lf = min(1.0, max(0.0, l_low + l_high))
            hf = min(1.0, max(0.0, r_low + r_high))

            if self.invert_sides:
                lf, hf = hf, lf

            self._send_rumble(lf, hf, duration_ms=duration_ms)
            last_lf, last_hf = lf, hf

            time.sleep(0.01)  # 100 Hz

    # ── Interface publique ─────────────────────────────────────────────────

    def set_vibration(
        self,
        left_low:    float = 0.0,
        left_high:   float = 0.0,
        right_low:   float = 0.0,
        right_high:  float = 0.0,
        duration_ms: int   = 0,
    ) -> None:
        """Envoie IMMÉDIATEMENT les valeurs à SDL_RumbleGamepad."""
        lf = max(0.0, min(1.0, float(left_low)  + float(left_high)))
        hf = max(0.0, min(1.0, float(right_low) + float(right_high)))
        if self.invert_sides:
            lf, hf = hf, lf
        self._send_rumble(lf, hf, duration_ms=max(20, duration_ms) if (lf > 0 or hf > 0) else 10)

    def stop(self) -> None:
        self.set_vibration(0.0, 0.0, 0.0, 0.0)
        if self._sdl and self._gamepad:
            try:
                self._sdl.SDL_RumbleGamepad(self._gamepad, 0, 0, 0)
            except Exception:
                pass

    def close(self):
        self._running = False
        self.stop()
        self._close_gamepad()
        if self._sdl:
            try:
                self._sdl.SDL_Quit()
            except Exception:
                pass
            self._sdl = None
