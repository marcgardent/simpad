"""
Legacy forwarder package for physics.
All implementations have been migrated to simpad_qt.core.physics.
"""
import sys
import simpad_qt.core.physics as _core_physics
import simpad_qt.core.physics.effects as _effects

sys.modules["src.physics.effects"] = _effects
effects = _effects

for _mod in (_core_physics, _effects):
    for _k, _v in _mod.__dict__.items():
        if not _k.startswith("__"):
            globals()[_k] = _v
