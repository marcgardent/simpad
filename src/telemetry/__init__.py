"""
Legacy forwarder package for telemetry.
All implementations have been migrated to simpad_qt.core.telemetry.
"""
import sys
import simpad_qt.core.telemetry as _core_telemetry
import simpad_qt.core.telemetry.delta_engine as _delta_engine
import simpad_qt.core.telemetry.sensors as _sensors
import simpad_qt.core.telemetry.state_store as _state_store
import simpad_qt.core.telemetry.lmu_parser as _lmu_parser
import simpad_qt.core.telemetry.udp_server as _udp_server
import simpad_qt.core.telemetry.reference_profile as _reference_profile
import simpad_qt.core.telemetry.track_limits_logger as _track_limits_logger
import simpad_qt.core.telemetry.overlay_anomaly_logger as _overlay_anomaly_logger
import simpad_qt.core.telemetry.telemetry_logger as _telemetry_logger
import simpad_qt.core.telemetry.plugin_installer as _plugin_installer

# Populate sys.modules so imports like `from src.telemetry.delta_engine import ...`
# directly resolve to the canonical simpad_qt modules.
sys.modules["src.telemetry.delta_engine"] = _delta_engine
sys.modules["src.telemetry.sensors"] = _sensors
sys.modules["src.telemetry.state_store"] = _state_store
sys.modules["src.telemetry.lmu_parser"] = _lmu_parser
sys.modules["src.telemetry.udp_server"] = _udp_server
sys.modules["src.telemetry.reference_profile"] = _reference_profile
sys.modules["src.telemetry.track_limits_logger"] = _track_limits_logger
sys.modules["src.telemetry.overlay_anomaly_logger"] = _overlay_anomaly_logger
sys.modules["src.telemetry.telemetry_logger"] = _telemetry_logger
sys.modules["src.telemetry.plugin_installer"] = _plugin_installer

delta_engine = _delta_engine
sensors = _sensors
state_store = _state_store
lmu_parser = _lmu_parser
udp_server = _udp_server
reference_profile = _reference_profile
track_limits_logger = _track_limits_logger
overlay_anomaly_logger = _overlay_anomaly_logger
telemetry_logger = _telemetry_logger
plugin_installer = _plugin_installer

import logging
logging.getLogger("src.telemetry.udp_server")

for _mod in (_core_telemetry, _sensors, _state_store, _lmu_parser, _delta_engine, _udp_server, _reference_profile, _plugin_installer):
    for _k, _v in _mod.__dict__.items():
        if not _k.startswith("__"):
            globals()[_k] = _v
