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

    title = get_foreground_window_title()
    if "le mans ultimate" in title.lower():
        return True

    proc_name = get_foreground_process_name()
    if "lemansultimate" in proc_name or "le mans ultimate" in proc_name:
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
    Calculates (x, y, width, height) for a 3x3 grid cell.
    col: 0 (left), 1 (middle), 2 (right)
    row: 0 (top), 1 (middle), 2 (bottom)

    Top-Middle (col=1, row=0) returns:
    x = Width / 3
    y = 0
    w = Width / 3
    h = Height / 3
    """
    try:
        import dearpygui.dearpygui as dpg
        if dpg.is_viewport_ok():
            vw = dpg.get_viewport_width()
            vh = dpg.get_viewport_height()
            if vw > 100 and vh > 100:
                w = max(300, vw // 3)
                h = max(180, vh // 3)
                x = (vw - w) // 2 if col == 1 else col * w
                y = row * h
                return (int(x), int(y), int(w), int(h))
    except Exception:
        pass

    sw, sh = get_screen_dimensions()
    w = max(300, sw // 3)
    h = max(180, sh // 3)
    x = (sw - w) // 2 if col == 1 else col * w
    y = row * h
    return (int(x), int(y), int(w), int(h))

