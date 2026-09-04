"""
Legacy forwarder package for engineer.
All implementations have been migrated to simpad_qt.core.engineer.
"""
import sys
import simpad_qt.core.engineer as _core_engineer
import simpad_qt.core.engineer.base as _base
import simpad_qt.core.engineer.params as _params
import simpad_qt.core.engineer.context as _context
import simpad_qt.core.engineer.registry as _registry
import simpad_qt.core.engineer.factory as _factory
import simpad_qt.core.engineer.manager as _manager
import simpad_qt.core.engineer.roles as _roles
import simpad_qt.core.engineer.roles.lap_validity as _lap_validity
import simpad_qt.core.engineer.roles.traffic_spotter as _traffic_spotter
import simpad_qt.core.engineer.roles.traffic_jam as _traffic_jam
import simpad_qt.core.engineer.roles.pace_notes as _pace_notes
import simpad_qt.core.engineer.roles.pitlane_spotter as _pitlane_spotter
import simpad_qt.core.engineer.roles.fight_spotter as _fight_spotter

# Populate sys.modules so legacy imports directly resolve to simpad_qt.core.engineer
sys.modules["src.engineer.base"] = _base
sys.modules["src.engineer.params"] = _params
sys.modules["src.engineer.context"] = _context
sys.modules["src.engineer.registry"] = _registry
sys.modules["src.engineer.factory"] = _factory
sys.modules["src.engineer.manager"] = _manager
sys.modules["src.engineer.roles"] = _roles
sys.modules["src.engineer.roles.lap_validity"] = _lap_validity
sys.modules["src.engineer.roles.traffic_spotter"] = _traffic_spotter
sys.modules["src.engineer.roles.traffic_jam"] = _traffic_jam
sys.modules["src.engineer.roles.pace_notes"] = _pace_notes
sys.modules["src.engineer.roles.pitlane_spotter"] = _pitlane_spotter
sys.modules["src.engineer.roles.fight_spotter"] = _fight_spotter

base = _base
params = _params
context = _context
registry = _registry
factory = _factory
manager = _manager
roles = _roles

for _mod in (_core_engineer, _base, _params, _context, _registry, _factory, _manager, _roles):
    for _k, _v in _mod.__dict__.items():
        if not _k.startswith("__"):
            globals()[_k] = _v
