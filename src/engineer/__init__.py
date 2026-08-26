"""
SimPad Race Engineer — Architecture modulaire pour l'ingénieur de course virtuel.
Exportation des abstractions de base, de la fabrique, du registre et du coordinateur.
"""

from src.engineer.base import BaseRole, RoleStatus, EngineerMessage
from src.engineer.context import EngineerContext
from src.engineer.registry import RoleRegistry
from src.engineer.factory import RoleFactory
from src.engineer.manager import RaceEngineer
from src.engineer.roles.lap_validity import LapValidityRole
from src.engineer.roles.traffic_spotter import TrafficSpotterRole, TrafficSpotterState
from src.engineer.roles.traffic_jam import TrafficJamRole

__all__ = [
    "BaseRole",
    "RoleStatus",
    "EngineerMessage",
    "EngineerContext",
    "RoleRegistry",
    "RoleFactory",
    "RaceEngineer",
    "LapValidityRole",
    "TrafficSpotterRole",
    "TrafficSpotterState",
    "TrafficJamRole",
]
