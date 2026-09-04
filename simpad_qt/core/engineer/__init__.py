"""
SimPad Race Engineer — Modular architecture for virtual race engineer.
Exports base abstractions, factory, registry, and coordinator.
"""

from .base import BaseRole, RoleStatus, EngineerMessage
from .context import EngineerContext
from .registry import RoleRegistry
from .factory import RoleFactory
from .manager import RaceEngineer, DEFAULT_ENGINEER_CONFIG_PATH
from .params import RoleParam, BoolParam, IntRangeParam, FloatRangeParam, ChoiceParam
from .roles.lap_validity import LapValidityRole
from .roles.traffic_spotter import TrafficSpotterRole, TrafficSpotterState
from .roles.traffic_jam import TrafficJamRole
from .roles.pace_notes import PaceNotesRole
from .roles.pitlane_spotter import PitlaneSpotterRole, PitlaneSpotterState
from .roles.fight_spotter import FightSpotterRole, SpotterSide, SpotterMessageType, FightSpotterState

__all__ = [
    "BaseRole",
    "RoleStatus",
    "EngineerMessage",
    "EngineerContext",
    "RoleParam",
    "BoolParam",
    "IntRangeParam",
    "FloatRangeParam",
    "ChoiceParam",
    "RoleRegistry",
    "RoleFactory",
    "RaceEngineer",
    "DEFAULT_ENGINEER_CONFIG_PATH",
    "LapValidityRole",
    "TrafficSpotterRole",
    "TrafficSpotterState",
    "TrafficJamRole",
    "PaceNotesRole",
    "PitlaneSpotterRole",
    "PitlaneSpotterState",
    "FightSpotterRole",
    "SpotterSide",
    "SpotterMessageType",
    "FightSpotterState",
]
