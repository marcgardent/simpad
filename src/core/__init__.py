"""
Legacy forwarder package for core.
All implementations have been migrated to simpad_qt.core.
"""
import sys
import simpad_qt.core.math_utils as _math_utils

sys.modules["src.core.math_utils"] = _math_utils
math_utils = _math_utils

for _k, _v in _math_utils.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v
