"""
SimPulse Haptic Middleware — Cross-platform SDL3 Haptic Controller with Auto-Reconnection.
Handles hotplugging, disconnection, sleep/power-off, and auto-reconnection of gamepads.
"""

import sys
import time
import ctypes
import threading
import logging
from typing import Optional, Union

from .base import HapticController
from .loader import SDL3Loader
from .mapper import HapticChannelMapper, DirectMixMapper

logger = logging.getLogger(__name__)

# SDL3 Constants
SDL_INIT_GAMEPAD = 0x00000200
SDL_RUMBLE_MAX_U16 = 0xFFFF


class SDL3HapticController(HapticController):
    """
    Haptic feedback via SDL3 (Cross-platform).
    Automatically locates SDL3 via loader (PyPI package 'sdl3', system lib, or local binary).
    Handles background hotplugging and auto-reconnection continuously.
    """

    def __init__(
        self,
        device_index: int = 0,
        invert_sides: bool = False,
        mapper: Optional[HapticChannelMapper] = None,
    ):
        self.device_index = device_index
        self.invert_sides = invert_sides
        self.mapper = mapper or DirectMixMapper()
        self._lock = threading.Lock()

        # 4-channel levels (0.0 to 1.0)
        self.left_low = 0.0
        self.left_high = 0.0
        self.right_low = 0.0
        self.right_high = 0.0

        self._running = False
        self._sdl_mod = None
        self._sdl_cdll = None
        self._gamepad: Optional[Union[ctypes.c_void_p, int]] = None
        self._gamepad_name = "No Gamepad"

        self._init_sdl()

    def _init_sdl(self):
        """Initializes SDL3 via loader and enables GameInput on Windows."""
        mod, cdll_handle = SDL3Loader.load()
        self._sdl_mod = mod
        self._sdl_cdll = cdll_handle

        if not mod and not cdll_handle:
            logger.error("SDL3Loader: Unable to load SDL3 library.")
            return

        try:
            if self._sdl_mod:
                if sys.platform == "win32":
                    self._sdl_mod.SDL_SetHint(b"SDL_JOYSTICK_GAMEINPUT", b"1")
                ok = self._sdl_mod.SDL_Init(SDL_INIT_GAMEPAD)
            else:
                self._setup_cdll_prototypes()
                if sys.platform == "win32":
                    self._sdl_cdll.SDL_SetHint(b"SDL_JOYSTICK_GAMEINPUT", b"1")
                ok = self._sdl_cdll.SDL_Init(SDL_INIT_GAMEPAD)

            if ok:
                logger.info("SDL3 Gamepad subsystem initialized successfully.")
            else:
                logger.error("SDL_Init(SDL_INIT_GAMEPAD) failed.")
        except Exception as e:
            logger.error(f"Error initializing SDL3: {e}")

    def _setup_cdll_prototypes(self):
        """Configures argument and return types for ctypes CDLL (cdecl)."""
        s = self._sdl_cdll
        if not s:
            return

        s.SDL_SetHint.restype = ctypes.c_bool
        s.SDL_SetHint.argtypes = [ctypes.c_char_p, ctypes.c_char_p]

        s.SDL_Init.restype = ctypes.c_bool
        s.SDL_Init.argtypes = [ctypes.c_uint32]

        s.SDL_Quit.restype = None
        s.SDL_Quit.argtypes = []

        s.SDL_GetError.restype = ctypes.c_char_p
        s.SDL_GetError.argtypes = []

        s.SDL_PumpEvents.restype = None
        s.SDL_PumpEvents.argtypes = []

        s.SDL_GetGamepads.restype = ctypes.POINTER(ctypes.c_uint32)
        s.SDL_GetGamepads.argtypes = [ctypes.POINTER(ctypes.c_int)]

        s.SDL_free.restype = None
        s.SDL_free.argtypes = [ctypes.c_void_p]

        s.SDL_OpenGamepad.restype = ctypes.c_void_p
        s.SDL_OpenGamepad.argtypes = [ctypes.c_uint32]

        s.SDL_CloseGamepad.restype = None
        s.SDL_CloseGamepad.argtypes = [ctypes.c_void_p]

        s.SDL_GetGamepadName.restype = ctypes.c_char_p
        s.SDL_GetGamepadName.argtypes = [ctypes.c_void_p]

        s.SDL_RumbleGamepad.restype = ctypes.c_bool
        s.SDL_RumbleGamepad.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16, ctypes.c_uint32]

        s.SDL_GetGamepadAxis.restype = ctypes.c_int16
        s.SDL_GetGamepadAxis.argtypes = [ctypes.c_void_p, ctypes.c_int]

        s.SDL_GetGamepadButton.restype = ctypes.c_bool
        s.SDL_GetGamepadButton.argtypes = [ctypes.c_void_p, ctypes.c_int]

        if hasattr(s, "SDL_GamepadConnected"):
            s.SDL_GamepadConnected.restype = ctypes.c_bool
            s.SDL_GamepadConnected.argtypes = [ctypes.c_void_p]

    def _is_handle_alive(self) -> bool:
        """Checks if open gamepad handle is still valid and connected."""
        if self._gamepad is None:
            return False
        try:
            if self._sdl_mod:
                self._sdl_mod.SDL_PumpEvents()
                if hasattr(self._sdl_mod, "SDL_GamepadConnected"):
                    return bool(self._sdl_mod.SDL_GamepadConnected(self._gamepad))
                return True
            elif self._sdl_cdll:
                self._sdl_cdll.SDL_PumpEvents()
                if hasattr(self._sdl_cdll, "SDL_GamepadConnected"):
                    return bool(self._sdl_cdll.SDL_GamepadConnected(self._gamepad))
                return True
        except Exception:
            return False
        return True

    def _acquire_gamepad(self) -> bool:
        """Checks gamepad status or attempts to open a new one (auto-reconnection)."""
        with self._lock:
            # 1. If we have an open handle, check if it is still active
            if self._gamepad is not None:
                if self._is_handle_alive():
                    return True
                logger.info(f"Gamepad '{self._gamepad_name}' disconnected or powered off.")
                self._close_gamepad_locked()

            # 2. Search and open an available gamepad
            if not self._sdl_mod and not self._sdl_cdll:
                return False

            try:
                if self._sdl_mod:
                    self._sdl_mod.SDL_PumpEvents()
                    count = ctypes.c_int(0)
                    ids_ptr = self._sdl_mod.SDL_GetGamepads(ctypes.byref(count))
                    if not ids_ptr or count.value == 0:
                        self._gamepad = None
                        self._gamepad_name = "No Gamepad"
                        return False

                    idx = min(self.device_index, count.value - 1)
                    instance_id = ids_ptr[idx]
                    self._sdl_mod.SDL_free(ctypes.cast(ids_ptr, ctypes.c_void_p))

                    gamepad = self._sdl_mod.SDL_OpenGamepad(instance_id)
                    if not gamepad:
                        self._gamepad = None
                        self._gamepad_name = "No Gamepad"
                        return False

                    name_b = self._sdl_mod.SDL_GetGamepadName(gamepad)
                    if isinstance(name_b, bytes):
                        self._gamepad_name = name_b.decode(errors='replace')
                    elif isinstance(name_b, str):
                        self._gamepad_name = name_b
                    else:
                        self._gamepad_name = "SDL3 Gamepad"

                    self._gamepad = gamepad
                    logger.info(f"Gamepad connected / reconnected: '{self._gamepad_name}'")
                    return True
                else:
                    s = self._sdl_cdll
                    s.SDL_PumpEvents()
                    count = ctypes.c_int(0)
                    ids_ptr = s.SDL_GetGamepads(ctypes.byref(count))
                    if not ids_ptr or count.value == 0:
                        self._gamepad = None
                        self._gamepad_name = "No Gamepad"
                        return False

                    idx = min(self.device_index, count.value - 1)
                    instance_id = ids_ptr[idx]
                    s.SDL_free(ctypes.cast(ids_ptr, ctypes.c_void_p))

                    gamepad = s.SDL_OpenGamepad(instance_id)
                    if not gamepad:
                        self._gamepad = None
                        self._gamepad_name = "No Gamepad"
                        return False

                    name_b = s.SDL_GetGamepadName(gamepad)
                    self._gamepad_name = name_b.decode(errors='replace') if name_b else "SDL3 Gamepad"
                    self._gamepad = gamepad
                    logger.info(f"Gamepad connected / reconnected via CDLL: '{self._gamepad_name}'")
                    return True

            except Exception as exc:
                logger.debug(f"_acquire_gamepad exception: {exc}")
                self._gamepad = None
                self._gamepad_name = "No Gamepad"
                return False

    def is_connected(self) -> bool:
        return self._acquire_gamepad()

    def get_gamepad_name(self) -> str:
        if self.is_connected():
            return self._gamepad_name
        return "No Gamepad"

    def get_axis(self, axis: int) -> float:
        if not self._acquire_gamepad():
            return 0.0
        with self._lock:
            if self._gamepad is None:
                return 0.0
            try:
                if self._sdl_mod:
                    self._sdl_mod.SDL_PumpEvents()
                    raw = self._sdl_mod.SDL_GetGamepadAxis(self._gamepad, axis)
                else:
                    self._sdl_cdll.SDL_PumpEvents()
                    raw = self._sdl_cdll.SDL_GetGamepadAxis(self._gamepad, axis)
                return max(-1.0, raw / 32767.0)
            except Exception:
                return 0.0

    def get_left_stick_x(self) -> float:
        return self.get_axis(0)

    def get_button(self, button: int) -> bool:
        if not self._acquire_gamepad():
            return False
        with self._lock:
            if self._gamepad is None:
                return False
            try:
                if self._sdl_mod:
                    self._sdl_mod.SDL_PumpEvents()
                    return bool(self._sdl_mod.SDL_GetGamepadButton(self._gamepad, button))
                else:
                    self._sdl_cdll.SDL_PumpEvents()
                    return bool(self._sdl_cdll.SDL_GetGamepadButton(self._gamepad, button))
            except Exception:
                return False

    def get_south_button(self) -> bool:
        return self.get_button(0)

    def _close_gamepad_locked(self):
        """Closes internal gamepad handle (must be called with self._lock acquired)."""
        if self._gamepad is not None:
            try:
                if self._sdl_mod:
                    self._sdl_mod.SDL_CloseGamepad(self._gamepad)
                elif self._sdl_cdll:
                    self._sdl_cdll.SDL_CloseGamepad(self._gamepad)
            except Exception:
                pass
        self._gamepad = None
        self._gamepad_name = "No Gamepad"

    def _close_gamepad(self):
        with self._lock:
            self._close_gamepad_locked()

    def _send_rumble(self, lf: float, hf: float, duration_ms: int = 50) -> None:
        if not self._acquire_gamepad():
            return

        with self._lock:
            if self._gamepad is None:
                return

            try:
                lf_u16 = int(lf * SDL_RUMBLE_MAX_U16)
                hf_u16 = int(hf * SDL_RUMBLE_MAX_U16)
                dur = 10 if (lf_u16 == 0 and hf_u16 == 0) else max(20, int(duration_ms))

                ok = True
                if self._sdl_mod:
                    ok = bool(self._sdl_mod.SDL_RumbleGamepad(self._gamepad, lf_u16, hf_u16, dur))
                elif self._sdl_cdll:
                    ok = bool(self._sdl_cdll.SDL_RumbleGamepad(self._gamepad, lf_u16, hf_u16, dur))

                if not ok:
                    logger.warning("SDL_RumbleGamepad failed (gamepad disconnected/off). Resetting.")
                    self._close_gamepad_locked()

            except Exception as exc:
                logger.warning(f"_send_rumble exception: {exc}")
                self._close_gamepad_locked()

    def set_vibration(
        self,
        left_low: float = 0.0,
        left_high: float = 0.0,
        right_low: float = 0.0,
        right_high: float = 0.0,
        duration_ms: int = 0,
    ) -> None:
        self.left_low = float(left_low)
        self.left_high = float(left_high)
        self.right_low = float(right_low)
        self.right_high = float(right_high)
        lf, hf = self.mapper.map_channels(left_low, left_high, right_low, right_high)
        if self.invert_sides:
            lf, hf = hf, lf
        self._send_rumble(lf, hf, duration_ms=max(20, duration_ms) if (lf > 0 or hf > 0) else 10)

    def stop(self) -> None:
        self.left_low = 0.0
        self.left_high = 0.0
        self.right_low = 0.0
        self.right_high = 0.0
        self.set_vibration(0.0, 0.0, 0.0, 0.0)
        with self._lock:
            if self._gamepad is not None:
                try:
                    if self._sdl_mod:
                        self._sdl_mod.SDL_RumbleGamepad(self._gamepad, 0, 0, 0)
                    elif self._sdl_cdll:
                        self._sdl_cdll.SDL_RumbleGamepad(self._gamepad, 0, 0, 0)
                except Exception:
                    pass

    def close(self):
        self.stop()
        self._close_gamepad()
        if self._sdl_mod:
            try:
                self._sdl_mod.SDL_Quit()
            except Exception:
                pass
            self._sdl_mod = None
        elif self._sdl_cdll:
            try:
                self._sdl_cdll.SDL_Quit()
            except Exception:
                pass
            self._sdl_cdll = None
