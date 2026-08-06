"""
SimPad — Utility functions for Windows system window state management.
Provides foreground window detection for Le Mans Ultimate (LMU).
"""

import sys
import ctypes
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
else:
    user32 = None
    kernel32 = None


def get_foreground_window_title() -> str:
    """Returns the title of the currently active foreground window on Windows."""
    if not user32:
        return ""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def get_foreground_process_name() -> str:
    """Returns the executable filename of the currently active foreground process on Windows."""
    if not user32 or not kernel32:
        return ""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    hProcess = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not hProcess:
        return ""
    try:
        buf_size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(hProcess, 0, ctypes.byref(buf), ctypes.byref(buf_size)):
            return Path(buf.value).name.lower()
    except Exception:
        pass
    finally:
        kernel32.CloseHandle(hProcess)

    return ""


def is_lmu_foreground() -> bool:
    """
    Returns True if Le Mans Ultimate is the active window in the foreground.
    Checks both window title and process image name.
    """
    if sys.platform != "win32":
        return False

    title = get_foreground_window_title().lower()
    if any(k in title for k in ("le mans ultimate", "lemansultimate", "lmu", "rfactor2")):
        return True

    proc_name = get_foreground_process_name().lower()
    if any(k in proc_name for k in ("lemansultimate", "le mans ultimate", "lmu", "rfactor2")):
        return True

    return False


def get_screen_dimensions() -> tuple[int, int]:
    """Returns primary monitor resolution (width, height). Defaults to (1920, 1080) if unavailable."""
    if user32:
        try:
            SM_CXSCREEN = 0
            SM_CYSCREEN = 1
            w = user32.GetSystemMetrics(SM_CXSCREEN)
            h = user32.GetSystemMetrics(SM_CYSCREEN)
            if w > 0 and h > 0:
                return (w, h)
        except Exception:
            pass
    return (1920, 1080)


def get_3x3_grid_rect(col: int = 1, row: int = 0) -> tuple[int, int, int, int]:
    """
    Calculates (x, y, width, height) for a 3x3 physical screen grid cell.
    Always uses the primary monitor's physical resolution so width is exactly 1/3 of the screen.
    col: 0 (left), 1 (middle), 2 (right)
    row: 0 (top), 1 (middle), 2 (bottom)

    Top-Middle (col=1, row=0) returns:
    x = Screen_Width / 3
    y = 0
    w = Screen_Width / 3
    h = Screen_Height / 3
    """
    sw, sh = get_screen_dimensions()
    w = max(300, sw // 3)
    h = max(180, sh // 3)
    x = (sw - w) // 2 if col == 1 else col * w
    y = row * h
    return (int(x), int(y), int(w), int(h))


if sys.platform == "win32":
    class MARGINS(ctypes.Structure):
        _fields_ = [
            ("cxLeftWidth", ctypes.c_int),
            ("cxRightWidth", ctypes.c_int),
            ("cyTopHeight", ctypes.c_int),
            ("cyBottomHeight", ctypes.c_int),
        ]


def make_transparent_overlay(window_title: str) -> bool:
    """
    Extends DWM frame into client area for full window background transparency on Windows.
    Enables transparent GPU rendering and mouse click pass-through on clear areas.
    """
    if sys.platform != "win32" or not user32:
        return False

    try:
        hwnd = user32.FindWindowW(None, window_title)
        if hwnd:
            margins = MARGINS(-1, -1, -1, -1)
            dwmapi = ctypes.windll.dwmapi
            dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
            print(f"[DWM OVERLAY] Transparent DWM overlay enabled for HWND {hwnd}", flush=True)
            return True
    except Exception as e:
        print(f"[DWM OVERLAY] Error injecting DWM transparency: {e}", flush=True)

    return False


def force_viewport_fullscreen_overlay(window_title: str) -> bool:
    """
    Forces the DPG viewport window to full physical screen resolution (0, 0, SW, SH)
    with HWND_TOPMOST, WS_EX_TRANSPARENT (click pass-through), WS_EX_NOACTIVATE (focus protection),
    and DWM background transparency.
    """
    try:
        import dearpygui.dearpygui as dpg
        dpg.configure_viewport(0, decorated=False, always_on_top=True)
        dpg.maximize_viewport()
    except Exception:
        pass

    if sys.platform != "win32" or not user32:
        return False

    try:
        hwnd = user32.FindWindowW(None, window_title)
        if hwnd:
            sw, sh = get_screen_dimensions()

            # Apply Win32 Extended Window Styles for true click-through & no-activate
            GWL_EXSTYLE = -20
            WS_EX_TOPMOST = 0x00000008
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_NOACTIVATE = 0x08000000

            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= (WS_EX_TOPMOST | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

            # Stretch to full physical screen bounds (0, 0, sw, sh)
            SWP_SHOWWINDOW = 0x0040
            user32.SetWindowPos(hwnd, -1, 0, 0, sw, sh, SWP_SHOWWINDOW)

            margins = MARGINS(-1, -1, -1, -1)
            dwmapi = ctypes.windll.dwmapi
            dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
            print(f"[VIEWPORT OVERLAY] HWND {hwnd} forced to Fullscreen Click-Through Overlay (0, 0, {sw}, {sh})", flush=True)
            return True
    except Exception as e:
        print(f"[VIEWPORT OVERLAY] Error forcing fullscreen overlay: {e}", flush=True)

    return False


def restore_viewport_windowed(window_title: str) -> bool:
    """
    Restores the DPG viewport to maximized desktop console mode with standard window decorations (decorated=True),
    removing WS_EX_TRANSPARENT and WS_EX_NOACTIVATE flags.
    """
    try:
        import dearpygui.dearpygui as dpg
        dpg.configure_viewport(0, decorated=True, always_on_top=False)
        dpg.maximize_viewport()
    except Exception:
        pass

    if sys.platform != "win32" or not user32:
        return False

    try:
        hwnd = user32.FindWindowW(None, window_title)
        if hwnd:
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_NOACTIVATE = 0x08000000

            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style &= ~(WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

            SW_MAXIMIZE = 3
            user32.ShowWindow(hwnd, SW_MAXIMIZE)
            print(f"[VIEWPORT OVERLAY] HWND {hwnd} restored to Maximized Desktop Console (decorated=True)", flush=True)
            return True
    except Exception as e:
        print(f"[VIEWPORT OVERLAY] Error restoring windowed console: {e}", flush=True)

    return False

