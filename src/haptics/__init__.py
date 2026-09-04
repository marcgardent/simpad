"""
Legacy forwarder package for haptics.
All implementations have been migrated to simpad_qt.core.haptics.
"""
import sys
import simpad_qt.core.haptics as _core_haptics
import simpad_qt.core.haptics.base as _base
import simpad_qt.core.haptics.models as _models
import simpad_qt.core.haptics.manager as _manager
import simpad_qt.core.haptics.factory as _factory
import simpad_qt.core.haptics.loader as _loader
import simpad_qt.core.haptics.mapper as _mapper
import simpad_qt.core.haptics.math_engine as _math_engine
import simpad_qt.core.haptics.mock_controller as _mock_controller
import simpad_qt.core.haptics.sdl3_controller as _sdl3_controller
import simpad_qt.core.haptics.telemetry_math as _telemetry_math
import simpad_qt.core.haptics.windows as _windows
import simpad_qt.core.haptics.subplugins as _subplugins
import simpad_qt.core.haptics.subplugins.base as _subplugins_base
import simpad_qt.core.haptics.subplugins.curbs as _curbs
import simpad_qt.core.haptics.subplugins.grip as _grip
import simpad_qt.core.haptics.subplugins.marc_abs as _marc_abs
import simpad_qt.core.haptics.subplugins.marc_engine_shift as _marc_engine_shift
import simpad_qt.core.haptics.subplugins.marc_tc as _marc_tc
import simpad_qt.core.haptics.subplugins.slip as _slip

# Populate sys.modules so legacy imports directly resolve to simpad_qt.core.haptics
sys.modules["src.haptics.base"] = _base
sys.modules["src.haptics.models"] = _models
sys.modules["src.haptics.manager"] = _manager
sys.modules["src.haptics.factory"] = _factory
sys.modules["src.haptics.loader"] = _loader
sys.modules["src.haptics.mapper"] = _mapper
sys.modules["src.haptics.math_engine"] = _math_engine
sys.modules["src.haptics.mock_controller"] = _mock_controller
sys.modules["src.haptics.sdl3_controller"] = _sdl3_controller
sys.modules["src.haptics.telemetry_math"] = _telemetry_math
sys.modules["src.haptics.windows"] = _windows
sys.modules["src.haptics.subplugins"] = _subplugins
sys.modules["src.haptics.subplugins.base"] = _subplugins_base
sys.modules["src.haptics.subplugins.curbs"] = _curbs
sys.modules["src.haptics.subplugins.grip"] = _grip
sys.modules["src.haptics.subplugins.marc_abs"] = _marc_abs
sys.modules["src.haptics.subplugins.marc_engine_shift"] = _marc_engine_shift
sys.modules["src.haptics.subplugins.marc_tc"] = _marc_tc
sys.modules["src.haptics.subplugins.slip"] = _slip

base = _base
models = _models
manager = _manager
factory = _factory
loader = _loader
mapper = _mapper
math_engine = _math_engine
mock_controller = _mock_controller
sdl3_controller = _sdl3_controller
telemetry_math = _telemetry_math
windows = _windows
subplugins = _subplugins

for _mod in (_core_haptics, _base, _models, _manager, _factory, _loader, _mapper, _math_engine, _telemetry_math, _subplugins):
    for _k, _v in _mod.__dict__.items():
        if not _k.startswith("__"):
            globals()[_k] = _v
