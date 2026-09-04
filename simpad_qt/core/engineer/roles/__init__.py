"""
SimPad Race Engineer — Roles package.
Imports all roles to trigger registration with RoleRegistry.
"""

from .lap_validity import LapValidityRole
from .traffic_spotter import TrafficSpotterRole, TrafficSpotterState
from .traffic_jam import TrafficJamRole
from .pace_notes import PaceNotesRole
from .pitlane_spotter import PitlaneSpotterRole, PitlaneSpotterState
from .fight_spotter import FightSpotterRole, SpotterSide, SpotterMessageType, FightSpotterState

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
