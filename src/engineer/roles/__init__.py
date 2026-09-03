"""
SimPad Race Engineer — Roles package.
Imports all roles to trigger registration with RoleRegistry.
"""

from src.engineer.roles.lap_validity import LapValidityRole
from src.engineer.roles.traffic_spotter import TrafficSpotterRole, TrafficSpotterState
from src.engineer.roles.traffic_jam import TrafficJamRole
from src.engineer.roles.pace_notes import PaceNotesRole
from src.engineer.roles.pitlane_spotter import PitlaneSpotterRole, PitlaneSpotterState
from src.engineer.roles.fight_spotter import FightSpotterRole, SpotterSide, SpotterMessageType, FightSpotterState

__all__ = [
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
