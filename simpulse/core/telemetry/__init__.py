"""Package telemetry."""

from .sensors import VehicleSensors
from .state_store import TelemetryStateStore, PacketSlot
from .delta_engine import DeltaEngine, DeltaReferenceMode, format_lap_time
from .fuel_engine import FuelEnergyEngine
from .metadata_engine import MetadataEngine
from .session_energy_gauge import SessionEnergyGaugeResult, compute_session_energy_gauge
from .udp_server import UDPServer
from .reference_profile import ReferenceLapProfile, TrackAnnotation, AnnotationType
from .plugin_installer import LMUPluginManager, SUPPORTED_GAMES, SupportedGame, SimulatorInstallInfo

from isimotor_rawudp_client import (
    IsiMotorClient,
    TelemInfo,
    TelemWheel,
    CompactScoring,
    FullScoringSession,
    VehicleScoring,
    SystemEvent,
    ExtendedState,
    ForceFeedback,
    Graphics,
    WeatherControl,
    HWControlCommand,
    WeatherControlCommand,
)

__all__ = [
    "VehicleSensors",
    "TelemetryStateStore",
    "PacketSlot",
    "DeltaEngine",
    "DeltaReferenceMode",
    "FuelEnergyEngine",
    "MetadataEngine",
    "SessionEnergyGaugeResult",
    "compute_session_energy_gauge",
    "UDPServer",
    "ReferenceLapProfile",
    "TrackAnnotation",
    "AnnotationType",
    "LMUPluginManager",
    "SUPPORTED_GAMES",
    "SupportedGame",
    "SimulatorInstallInfo",
    "format_lap_time",
]

