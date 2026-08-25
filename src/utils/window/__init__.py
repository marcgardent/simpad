"""
SimPad Window Management Package.
Exposes BaseWindowManager, WindowsWindowManager, LinuxWindowManager, and WindowManagerFactory.
"""

from src.utils.window.base import BaseWindowManager
from src.utils.window.windows import WindowsWindowManager
from src.utils.window.linux import LinuxWindowManager
from src.utils.window.factory import WindowManagerFactory

__all__ = [
    "BaseWindowManager",
    "WindowsWindowManager",
    "LinuxWindowManager",
    "WindowManagerFactory",
]
