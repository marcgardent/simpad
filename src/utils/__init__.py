"""
Legacy forwarder package for utils.
All implementations have been migrated to simpad_qt.core.utils.
"""
import sys
import simpad_qt.core.utils as _core_utils
import simpad_qt.core.utils.audio as _audio
import simpad_qt.core.utils.audio_baker as _audio_baker
import simpad_qt.core.utils.glfw_manager as _glfw_manager
import simpad_qt.core.utils.window_utils as _window_utils
import simpad_qt.core.utils.window as _window
import simpad_qt.core.utils.window.base as _window_base
import simpad_qt.core.utils.window.factory as _window_factory
import simpad_qt.core.utils.window.windows as _window_windows
import simpad_qt.core.utils.window.linux as _window_linux

# Populate sys.modules so legacy imports directly resolve to simpad_qt.core.utils
sys.modules["src.utils.audio"] = _audio
sys.modules["src.utils.audio_baker"] = _audio_baker
sys.modules["src.utils.glfw_manager"] = _glfw_manager
sys.modules["src.utils.window_utils"] = _window_utils
sys.modules["src.utils.window"] = _window
sys.modules["src.utils.window.base"] = _window_base
sys.modules["src.utils.window.factory"] = _window_factory
sys.modules["src.utils.window.windows"] = _window_windows
sys.modules["src.utils.window.linux"] = _window_linux

audio = _audio
audio_baker = _audio_baker
glfw_manager = _glfw_manager
window_utils = _window_utils
window = _window

for _mod in (_core_utils, _audio, _audio_baker, _glfw_manager, _window_utils, _window):
    for _k, _v in _mod.__dict__.items():
        if not _k.startswith("__"):
            globals()[_k] = _v
