"""
Legacy forwarder package for schedule.
All implementations have been migrated to simpad_qt.builtin_plugins.paddock_agent.schedule.
"""
import sys
import simpad_qt.builtin_plugins.paddock_agent.schedule as _schedule
import simpad_qt.builtin_plugins.paddock_agent.schedule.manager as _manager

# Populate sys.modules so legacy imports directly resolve
sys.modules["src.schedule.manager"] = _manager
manager = _manager

for _mod in (_schedule, _manager):
    for _k, _v in _mod.__dict__.items():
        if not _k.startswith("__"):
            globals()[_k] = _v
