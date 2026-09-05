"""
SimPulse Window Management Package.
Exposes BaseWindowManager, WindowsWindowManager, LinuxWindowManager, and WindowManagerFactory.
"""

from .base import BaseWindowManager
from .windows import WindowsWindowManager
from .linux import LinuxWindowManager
from .factory import WindowManagerFactory

__all__ = [
    "BaseWindowManager",
    "WindowsWindowManager",
    "LinuxWindowManager",
    "WindowManagerFactory",
]
