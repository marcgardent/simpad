"""
SimPad Haptic Middleware — Windows / XInput Implementation with Auto-Reconnection.
Supports SDL3 (GameInput/XInput) and Direct XInput native backend (ctypes.windll).
Handles realtime hotplugging, disconnection, and reconnection.
"""

from __future__ import annotations
import sys
import ctypes
import threading
import logging
from typing import Optional, Any

from src.haptics.base import HapticController
from src.haptics.sdl3_controller import SDL3HapticController
from src.haptics.mapper import HapticChannelMapper, XInputSeparatedMapper

logger = logging.getLogger(__name__)


# ctypes structures for native Windows XInput API
class XINPUT_VIBRATION(ctypes.Structure):
    _fields_ = [
        ("wLeftMotorSpeed", ctypes.c_ushort),
        ("wRightMotorSpeed", ctypes.c_ushort),
    ]


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", ctypes.c_ushort),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", ctypes.c_uint32),
        ("Gamepad", XINPUT_GAMEPAD),
    ]


class NativeWindowsXInputController(HapticController):
    """
    Native Windows direct haptic controller (via xinput1_4.dll, xinput1_3.dll or xinput9_1_0.dll).
    Handles reconnection without delays or external dependencies.
    """

    ERROR_SUCCESS = 0
    ERROR_DEVICE_NOT_CONNECTED = 1167

    def __init__(
        self,
        device_index: int = 0,
        invert_sides: bool = False,
        mapper: Optional[HapticChannelMapper] = None,
    ):
        self.device_index = device_index
        self.invert_sides = invert_sides
        self.mapper = mapper or XInputSeparatedMapper()
        self._lock = threading.Lock()

        self.left_low = 0.0
        self.left_high = 0.0
        self.right_low = 0.0
        self.right_high = 0.0

        self._dll: Optional[Any] = self._load_xinput_dll()
        self._connected = False
        self._gamepad_name = f"Xbox Controller (XInput Slot {device_index + 1})"

    def _load_xinput_dll(self) -> Optional[Any]:
        if sys.platform != "win32":
            return None
        for dll_name in ("xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"):
            try:
                dll = ctypes.windll.LoadLibrary(dll_name)
                logger.info(f"Native Windows XInput loaded: {dll_name}")
                return dll
            except Exception:
                continue
        return None

    def is_connected(self) -> bool:
        if not self._dll:
            return False
        with self._lock:
            state = XINPUT_STATE()
            try:
                res = self._dll.XInputGetState(self.device_index, ctypes.byref(state))
                self._connected = (res == self.ERROR_SUCCESS)
            except Exception:
                self._connected = False
            return self._connected

    def get_gamepad_name(self) -> str:
        if self.is_connected():
            return self._gamepad_name
        return "No Gamepad"

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

        if not self._dll:
            return

        lf, hf = self.mapper.map_channels(left_low, left_high, right_low, right_high)
        if self.invert_sides:
            lf, hf = hf, lf

        lf_u16 = int(max(0.0, min(1.0, lf)) * 65535)
        hf_u16 = int(max(0.0, min(1.0, hf)) * 65535)

        with self._lock:
            try:
                vibe = XINPUT_VIBRATION(lf_u16, hf_u16)
                res = self._dll.XInputSetState(self.device_index, ctypes.byref(vibe))
                self._connected = (res == self.ERROR_SUCCESS)
            except Exception:
                self._connected = False

    def stop(self) -> None:
        self.left_low = 0.0
        self.left_high = 0.0
        self.right_low = 0.0
        self.right_high = 0.0
        self.set_vibration(0.0, 0.0, 0.0, 0.0)

    def close(self) -> None:
        self.stop()


class WindowsHapticController(HapticController):
    """
    Hybrid Windows Controller:
    Attempts SDL3 (with GameInput / XInput mapper) and falls back transparently
    to Direct XInput backend if SDL3 is not installed.
    Handles disconnection and hotplugging.
    """

    def __init__(self, device_index: int = 0, invert_sides: bool = False):
        self.device_index = device_index
        self.invert_sides = invert_sides

        self._sdl: Optional[SDL3HapticController] = None
        self._native: Optional[NativeWindowsXInputController] = None

        # 1. Attempt SDL3
        try:
            sdl = SDL3HapticController(
                device_index=device_index,
                invert_sides=invert_sides,
                mapper=XInputSeparatedMapper(),
            )
            if sdl._sdl_mod or sdl._sdl_cdll:
                self._sdl = sdl
        except Exception:
            pass

        # 2. Attempt Direct Native XInput on Windows
        if sys.platform == "win32":
            try:
                native = NativeWindowsXInputController(
                    device_index=device_index,
                    invert_sides=invert_sides,
                    mapper=XInputSeparatedMapper(),
                )
                if native._dll:
                    self._native = native
            except Exception:
                pass

    @property
    def active_backend(self) -> HapticController:
        if self._sdl and (self._sdl._sdl_mod or self._sdl._sdl_cdll):
            return self._sdl
        if self._native and self._native._dll:
            return self._native
        return self._sdl if self._sdl else (self._native if self._native else SDL3HapticController())

    def is_connected(self) -> bool:
        # Check SDL3 first if connected
        if self._sdl and self._sdl.is_connected():
            return True
        if self._native and self._native.is_connected():
            return True
        return False

    def get_gamepad_name(self) -> str:
        if self._sdl and self._sdl.is_connected():
            return self._sdl.get_gamepad_name()
        if self._native and self._native.is_connected():
            return self._native.get_gamepad_name()
        return "No Gamepad"

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

        # If SDL3 is active and connected, send to SDL3
        if self._sdl:
            self._sdl.set_vibration(left_low, left_high, right_low, right_high, duration_ms)
        elif self._native:
            self._native.set_vibration(left_low, left_high, right_low, right_high, duration_ms)

    def stop(self) -> None:
        self.left_low = 0.0
        self.left_high = 0.0
        self.right_low = 0.0
        self.right_high = 0.0
        if self._sdl:
            self._sdl.stop()
        if self._native:
            self._native.stop()

    def close(self) -> None:
        if self._sdl:
            self._sdl.close()
        if self._native:
            self._native.close()
