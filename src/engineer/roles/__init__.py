"""
SimPad Race Engineer — Packages de rôles.
Importe tous les rôles pour déclencher leur enregistrement auprès de RoleRegistry.
"""

from src.engineer.roles.lap_validity import LapValidityRole
from src.engineer.roles.traffic_spotter import TrafficSpotterRole, TrafficSpotterState
from src.engineer.roles.traffic_jam import TrafficJamRole
from src.engineer.roles.pace_notes import PaceNotesRole

__all__ = [
    "LapValidityRole",
    "TrafficSpotterRole",
    "TrafficSpotterState",
    "TrafficJamRole",
    "PaceNotesRole",
]
