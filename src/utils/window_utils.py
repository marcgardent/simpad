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
