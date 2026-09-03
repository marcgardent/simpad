"""
SimPad Window Management — Windows (Win32 API & DWM) Implementation.
Provides native Win32 window text, process ID, DWM transparency, and window extended styles.
"""

import sys
import ctypes
from pathlib import Path
from src.utils.window.base import BaseWindowManager
from src.utils.glfw_manager import GLFWWindowManager

if sys.platform == "win32":
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    class MARGINS(ctypes.Structure):
        _fields_ = [
            ("cxLeftWidth", ctypes.c_int),
            ("cxRightWidth", ctypes.c_int),
            ("cyTopHeight", ctypes.c_int),
            ("cyBottomHeight", ctypes.c_int),
        ]
else:
    user32 = None
    kernel32 = None


class WindowsWindowManager(BaseWindowManager):
    """Windows-specific implementation via Win32 and DWM APIs."""

    def get_foreground_window_title(self) -> str:
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

    def get_foreground_process_name(self) -> str:
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

    def is_lmu_running(self) -> bool:
        if not kernel32:
            return False
        TH32CS_SNAPPROCESS = 0x00000002
        hSnapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if hSnapshot == -1 or not hSnapshot:
            return False

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.c_ulong),
                ("cntUsage", ctypes.c_ulong),
                ("th32ProcessID", ctypes.c_ulong),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", ctypes.c_ulong),
                ("cntThreads", ctypes.c_ulong),
                ("th32ParentProcessID", ctypes.c_ulong),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.c_ulong),
                ("szExeFile", ctypes.c_wchar * 260),
            ]

        try:
            pe = PROCESSENTRY32W()
            pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            target_names = {"lemansultimate.exe", "rfactor2.exe", "lemansultimate", "rfactor2", "start_protected_game.exe"}
            if kernel32.Process32FirstW(hSnapshot, ctypes.byref(pe)):
                while True:
                    exe_name = pe.szExeFile.lower()
                    if exe_name in target_names or "lemans" in exe_name or "le mans" in exe_name:
                        return True
                    if not kernel32.Process32NextW(hSnapshot, ctypes.byref(pe)):
                        break
        except Exception:
            pass
        finally:
            kernel32.CloseHandle(hSnapshot)
        return False

    def make_transparent_overlay(self, window_title: str) -> bool:
        if not user32:
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

    def force_viewport_fullscreen_overlay(self, window_title: str) -> bool:
        super().force_viewport_fullscreen_overlay(window_title)
        if not user32:
            return False

        try:
            hwnd = user32.FindWindowW(None, window_title)
            if hwnd:
                sw, sh = GLFWWindowManager.get_screen_dimensions()

                GWL_EXSTYLE = -20
                WS_EX_TOPMOST = 0x00000008
                WS_EX_LAYERED = 0x00080000
                WS_EX_TRANSPARENT = 0x00000020
                WS_EX_NOACTIVATE = 0x08000000

                style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                style |= (WS_EX_TOPMOST | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

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

    def restore_viewport_windowed(self, window_title: str) -> bool:
        super().restore_viewport_windowed(window_title)
        if not user32:
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
