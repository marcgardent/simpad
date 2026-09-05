"""
SimPulse Race Engineer — Roles alias package.
Re-exports sub-plugins for compatibility with role naming.
"""

from ..subplugins import (
    LapValidityRole,
    LapValiditySubplugin,
    TrafficSpotterRole,
    TrafficSpotterState,
    TrafficSpotterSubplugin,
    TrafficJamRole,
    TrafficJamSubplugin,
    PaceNotesRole,
    PaceNotesSubplugin,
    PitlaneSpotterRole,
    PitlaneSpotterState,
    PitlaneSpotterSubplugin,
    FightSpotterRole,
    FightSpotterSubplugin,
    SpotterSide,
    SpotterMessageType,
    FightSpotterState,
)

__all__ = [
    "LapValidityRole",
    "LapValiditySubplugin",
    "TrafficSpotterRole",
    "TrafficSpotterState",
    "TrafficSpotterSubplugin",
    "TrafficJamRole",
    "TrafficJamSubplugin",
    "PaceNotesRole",
    "PaceNotesSubplugin",
    "PitlaneSpotterRole",
    "PitlaneSpotterState",
    "PitlaneSpotterSubplugin",
    "FightSpotterRole",
    "FightSpotterSubplugin",
    "SpotterSide",
    "SpotterMessageType",
    "FightSpotterState",
]
