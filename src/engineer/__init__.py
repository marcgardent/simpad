"""
SimPad Race Engineer — Modular architecture for virtual race engineer.
Exports base abstractions, factory, registry, and coordinator.
"""

from src.engineer.base import BaseRole, RoleStatus, EngineerMessage
from src.engineer.context import EngineerContext
from src.engineer.registry import RoleRegistry
from src.engineer.factory import RoleFactory
from src.engineer.manager import RaceEngineer
from src.engineer.params import RoleParam, BoolParam, IntRangeParam, FloatRangeParam
from src.engineer.roles.lap_validity import LapValidityRole
from src.engineer.roles.traffic_spotter import TrafficSpotterRole, TrafficSpotterState
from src.engineer.roles.traffic_jam import TrafficJamRole
from src.engineer.roles.pace_notes import PaceNotesRole
from src.engineer.roles.pitlane_spotter import PitlaneSpotterRole, PitlaneSpotterState

__all__ = [
    "BaseRole",
    "RoleStatus",
    "EngineerMessage",
    "EngineerContext",
    "RoleParam",
    "BoolParam",
    "IntRangeParam",
    "FloatRangeParam",
    "RoleRegistry",
    "RoleFactory",
    "RaceEngineer",
    "LapValidityRole",
    "TrafficSpotterRole",
    "TrafficSpotterState",
    "TrafficJamRole",
    "PaceNotesRole",
    "PitlaneSpotterRole",
    "PitlaneSpotterState",
]
