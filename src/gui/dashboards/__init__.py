"""
SimPad Dashboards Module — Modular HUD Overlay Dashboard System.
"""

from src.gui.dashboards.base import BaseDashboard
from src.gui.dashboards.monitoring_board import MonitoringBoard
from src.gui.dashboards.manager import DashboardManager

__all__ = ["BaseDashboard", "MonitoringBoard", "DashboardManager"]
