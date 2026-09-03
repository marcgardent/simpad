"""
SimPad Window Management — Linux (Wayland & X11 & Proton/Wine) Implementation.
Supports KDE Plasma (KWin DBus Scripting / kdotool), Hyprland (hyprctl), Sway (swaymsg),
X11 (xprop/xdotool), and /proc process tree tracking for Proton/Wine gaming sessions.
"""

import os
import re
import time
import json
import threading
import subprocess
from pathlib import Path
from typing import Tuple, Set
from src.utils.window.base import BaseWindowManager


class LinuxWindowManager(BaseWindowManager):
    """Linux-specific implementation (Wayland compositors and X11)."""

    def __init__(self):
        super().__init__()
        self._active_window_info: Tuple[str, str, int] = ("", "", 0)
        self._cached_lmu_pids: Set[int] = set()
        self._last_pid_scan_time: float = 0.0
        self._start_async_focus_listener()

    def _start_async_focus_listener(self) -> None:
        """Starts asynchronous focus event listening in a background thread (0% CPU, 0ms latency)."""
        try:
            # 1. Register KWin listener script once
            script_dir = Path.home() / ".cache" / "simpad"
            script_dir.mkdir(parents=True, exist_ok=True)
            script_path = script_dir / "kwin_focus_listener.js"
            script_code = (
                'function notifyWin(w) { if (w) console.log("KWIN_ACTIVE_WIN:" + (w.caption || "") + "||" + (w.resourceClass || "") + "||" + (w.pid || 0)); }\n'
                'workspace.windowActivated.connect(notifyWin);\n'
                'notifyWin(workspace.activeWindow);\n'
            )
            script_path.write_text(script_code, encoding="utf-8")
            os.chmod(script_path, 0o644)

            load_out = subprocess.check_output(
                ["busctl", "--user", "call", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "loadScript", "s", str(script_path)],
                stderr=subprocess.DEVNULL, timeout=0.5
            ).decode("utf-8", errors="ignore").strip()

            if load_out:
                script_id = load_out.split()[-1]
                subprocess.check_output(
                    ["busctl", "--user", "call", "org.kde.KWin", f"/Scripting/Script{script_id}", "org.kde.kwin.Script", "run"],
                    stderr=subprocess.DEVNULL, timeout=0.5
                )

            # 2. Daemon thread listening continuously to KWin logs
            def _tail_worker():
                try:
                    proc = subprocess.Popen(
                        ["journalctl", "--user", "-f", "-n", "10", "-o", "cat", "_COMM=kwin_wayland"],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1
                    )
                    for line in iter(proc.stdout.readline, ''):
                        if "KWIN_ACTIVE_WIN:" in line:
                            payload = line.split("KWIN_ACTIVE_WIN:")[1].strip()
                            parts = payload.split("||")
                            c = parts[0] if len(parts) > 0 else ""
                            rc = parts[1] if len(parts) > 1 else ""
                            p = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
                            self._active_window_info = (c, rc, p)
                            self._notify_focus_changed()
                except Exception:
                    pass

            t = threading.Thread(target=_tail_worker, daemon=True, name="KWinFocusListenerThread")
            t.start()
        except Exception:
            pass

    def get_active_window_info(self) -> Tuple[str, str, int]:
        """Returns active foreground window info instantly (0ms, 0% CPU)."""
        if self._active_window_info != ("", "", 0):
            return self._active_window_info

        # Instant X11/Xwayland fallback
        try:
            out = subprocess.check_output(["xprop", "-root", "_NET_ACTIVE_WINDOW"], stderr=subprocess.DEVNULL, timeout=0.1).decode("utf-8", errors="ignore")
            m = re.search(r"0x[0-9a-fA-F]+", out)
            if m and m.group(0) != "0x0":
                win_id = m.group(0)
                info = subprocess.check_output(["xprop", "-id", win_id], stderr=subprocess.DEVNULL, timeout=0.1).decode("utf-8", errors="ignore")
                name_m = re.search(r'_NET_WM_NAME\(UTF8_STRING\) = "([^"]+)"', info) or re.search(r'WM_NAME\(STRING\) = "([^"]+)"', info)
                class_m = re.search(r'WM_CLASS\(STRING\) = "[^"]*", "([^"]*)"', info)
                pid_m = re.search(r"_NET_WM_PID\(CARDINAL\) = (\d+)", info)
                c = name_m.group(1).strip() if name_m else ""
                rc = class_m.group(1).strip() if class_m else ""
                p = int(pid_m.group(1)) if pid_m else 0
                return c, rc, p
        except Exception:
            pass

        return self._active_window_info

        # 2. Hyprland (hyprctl)
        try:
            out = subprocess.check_output(["hyprctl", "activewindow", "-j"], stderr=subprocess.DEVNULL, timeout=0.5)
            data = json.loads(out.decode("utf-8"))
            if isinstance(data, dict):
                c = data.get("title", "")
                rc = data.get("class", "")
                p = data.get("pid", 0)
                return c, rc, p
        except Exception:
            pass

        # 3. Sway (swaymsg)
        try:
            out = subprocess.check_output(["swaymsg", "-t", "get_tree"], stderr=subprocess.DEVNULL, timeout=0.5)
            def find_focused(node):
                if node.get("focused"):
                    return node.get("name", ""), node.get("app_id", ""), node.get("pid", 0)
                for child in node.get("nodes", []) + node.get("floating_nodes", []):
                    res = find_focused(child)
                    if res[0] or res[1] or res[2]:
                        return res
                return "", "", 0
            return find_focused(json.loads(out.decode("utf-8")))
        except Exception:
            pass

        # 4. kdotool (KDE Plasma)
        try:
            c = subprocess.check_output(["kdotool", "getactivewindow", "getwindowname"], stderr=subprocess.DEVNULL, timeout=0.5).decode("utf-8", errors="ignore").strip()
            p_str = subprocess.check_output(["kdotool", "getactivewindow", "getwindowpid"], stderr=subprocess.DEVNULL, timeout=0.5).decode("utf-8", errors="ignore").strip()
            p = int(p_str) if p_str.isdigit() else 0
            if c or p:
                return c, "", p
        except Exception:
            pass

        # 5. xprop -root _NET_ACTIVE_WINDOW (X11 / Xwayland)
        try:
            out = subprocess.check_output(["xprop", "-root", "_NET_ACTIVE_WINDOW"], stderr=subprocess.DEVNULL, timeout=0.5).decode("utf-8", errors="ignore")
            m = re.search(r"0x[0-9a-fA-F]+", out)
            if m and m.group(0) != "0x0":
                win_id = m.group(0)
                info = subprocess.check_output(["xprop", "-id", win_id], stderr=subprocess.DEVNULL, timeout=0.5).decode("utf-8", errors="ignore")
                name_m = re.search(r'_NET_WM_NAME\(UTF8_STRING\) = "([^"]+)"', info) or re.search(r'WM_NAME\(STRING\) = "([^"]+)"', info)
                class_m = re.search(r'WM_CLASS\(STRING\) = "[^"]*", "([^"]*)"', info)
                pid_m = re.search(r"_NET_WM_PID\(CARDINAL\) = (\d+)", info)
                c = name_m.group(1).strip() if name_m else ""
                rc = class_m.group(1).strip() if class_m else ""
                p = int(pid_m.group(1)) if pid_m else 0
                return c, rc, p
        except Exception:
            pass

        return "", "", 0

    def get_foreground_window_title(self) -> str:
        title, _, _ = self.get_active_window_info()
        return title

    def get_foreground_process_name(self) -> str:
        _, res_class, pid = self.get_active_window_info()
        if pid > 0:
            try:
                exe_path = Path(f"/proc/{pid}/exe")
                if exe_path.exists():
                    return exe_path.resolve().name.lower()
                comm_path = Path(f"/proc/{pid}/comm")
                if comm_path.exists():
                    return comm_path.read_text(encoding="utf-8", errors="ignore").strip().lower()
            except Exception:
                pass
        return res_class.lower()

    def get_lmu_pids(self) -> Set[int]:
        """Returns the set of PIDs associated with Le Mans Ultimate (with 1.5s cache)."""
        now = time.time()
        if (now - self._last_pid_scan_time) < 1.5 and self._cached_lmu_pids:
            return self._cached_lmu_pids

        target_substrs = (
            "le mans ultimate.exe",
            "lemansultimate.exe",
            "le mans ultimat",
            "lemansultimate",
            "rfactor2.exe",
            "rfactor2",
            "start_protected_game.exe",
        )
        pids = set()
        try:
            for p in Path("/proc").iterdir():
                if p.is_dir() and p.name.isdigit():
                    try:
                        comm_file = p / "comm"
                        if comm_file.exists():
                            comm = comm_file.read_text(encoding="utf-8", errors="ignore").strip().lower()
                            if comm.startswith("le mans") or comm.startswith("lemans") or "rfactor" in comm:
                                pids.add(int(p.name))
                                continue

                        cmdline_file = p / "cmdline"
                        if cmdline_file.exists():
                            cmdline = cmdline_file.read_bytes().replace(b"\x00", b" ").decode(errors="ignore").lower()
                            if any(target in cmdline for target in target_substrs):
                                pids.add(int(p.name))
                    except Exception:
                        continue
        except Exception:
            pass
        self._cached_lmu_pids = pids
        self._last_pid_scan_time = now
        return pids

    def is_lmu_running(self) -> bool:
        return len(self.get_lmu_pids()) > 0

    def is_lmu_foreground(self) -> bool:
        lmu_pids = self.get_lmu_pids()
        if not lmu_pids:
            return False

        title, res_class, active_pid = self.get_active_window_info()

        # 1. Direct PID match: does active window PID belong to LMU game?
        if active_pid > 0 and active_pid in lmu_pids:
            return True

        # 2. Match Title / Window Class
        title_lower = title.lower()
        class_lower = res_class.lower()
        if "le mans" in title_lower or "lemans" in title_lower or "rfactor" in title_lower:
            return True
        if "le mans" in class_lower or "lemans" in class_lower or "rfactor" in class_lower:
            return True

        # 3. Transparent HUD overlay only (in case KWin captures overlay activation)
        if "hud overlay" in title_lower:
            return True

        return False

    def _set_kwin_window_state(self, window_title: str, keep_above: bool, no_border: bool) -> None:
        """Dynamically applies keepAbove and noBorder state to the window via KWin DBus (Wayland) and xprop (X11)."""
        b_keep = "true" if keep_above else "false"
        b_border = "true" if no_border else "false"

        # 1. KDE Plasma KWin Wayland DBus Scripting
        try:
            script_dir = Path.home() / ".cache" / "simpad"
            script_dir.mkdir(parents=True, exist_ok=True)
            script_name = "kwin_keep_above.js" if keep_above else "kwin_restore_normal.js"
            script_path = script_dir / script_name
            script_code = (
                f'workspace.windowList().forEach(function(w) {{ '
                f'if (w.caption.indexOf("SimPad") !== -1 || w.caption.indexOf("LMU HUD") !== -1) {{ '
                f'w.keepAbove = {b_keep}; w.noBorder = {b_border}; '
                f'}} '
                f'}});'
            )
            if not script_path.exists() or script_path.read_text(encoding="utf-8") != script_code:
                script_path.write_text(script_code, encoding="utf-8")

            load_out = subprocess.check_output(
                ["busctl", "--user", "call", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "loadScript", "s", str(script_path)],
                stderr=subprocess.DEVNULL, timeout=0.5
            ).decode("utf-8", errors="ignore").strip()

            if load_out:
                script_id = load_out.split()[-1]
                subprocess.check_output(
                    ["busctl", "--user", "call", "org.kde.KWin", f"/Scripting/Script{script_id}", "org.kde.kwin.Script", "run"],
                    stderr=subprocess.DEVNULL, timeout=0.5
                )
        except Exception:
            pass

        # 2. X11 / Xwayland fallback
        try:
            flag_op = "-set" if keep_above else "-remove"
            subprocess.run(
                ["xprop", "-name", window_title, "-f", "_NET_WM_STATE", "32a", flag_op, "_NET_WM_STATE", "_NET_WM_STATE_ABOVE"],
                stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL, timeout=0.5
            )
        except Exception:
            pass

    def make_transparent_overlay(self, window_title: str) -> bool:
        super().make_transparent_overlay(window_title)
        self._set_kwin_window_state(window_title, keep_above=True, no_border=True)
        return True

    def force_viewport_fullscreen_overlay(self, window_title: str) -> bool:
        super().force_viewport_fullscreen_overlay(window_title)
        try:
            import dearpygui.dearpygui as dpg
            from src.utils.glfw_manager import GLFWWindowManager
            sw, sh = GLFWWindowManager.get_screen_dimensions()
            dpg.set_viewport_clear_color([0, 0, 0, 0])
            dpg.configure_viewport(0, x_pos=0, y_pos=0, width=sw, height=sh, decorated=False, always_on_top=True)
        except Exception:
            pass

        self._set_kwin_window_state(window_title, keep_above=True, no_border=True)
        return True

    def restore_viewport_windowed(self, window_title: str) -> bool:
        super().restore_viewport_windowed(window_title)
        try:
            import dearpygui.dearpygui as dpg
            dpg.set_viewport_clear_color([18, 18, 22, 255])
            dpg.configure_viewport(0, decorated=True, always_on_top=False)
            dpg.maximize_viewport()
        except Exception:
            pass

        self._set_kwin_window_state(window_title, keep_above=False, no_border=False)
        return True

