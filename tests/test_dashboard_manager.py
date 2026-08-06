"""
Unit tests for DashboardManager, MonitoringBoard, and 3x3 grid geometry calculation.
"""

from src.utils.window_utils import get_3x3_grid_rect, get_screen_dimensions
from src.gui.dashboards.manager import DashboardManager
from src.gui.dashboards.monitoring_board import MonitoringBoard
from src.telemetry.sensors import VehicleSensors


def test_3x3_grid_rect_calculation():
    """Verify 3x3 grid geometry calculations."""
    sw, sh = get_screen_dimensions()
    x, y, w, h = get_3x3_grid_rect(col=1, row=0)  # Top-Middle

    assert w >= 300
    assert h >= 180
    assert y == 0


def test_dashboard_manager_lifecycle():
    """Verify DashboardManager registration, lookup, and lifecycle calls."""
    mgr = DashboardManager()

    # Verify default registration of monitoringBoard
    assert "monitoringBoard" in mgr.dashboard_names
    board = mgr.get_dashboard("monitoringBoard")
    assert board is not None
    assert isinstance(board, MonitoringBoard)

    # Test update_telemetry without errors
    sensors = VehicleSensors(rpm_ratio=0.75, lock_intensity=0.2, spin_intensity=0.1)
    mgr.update_telemetry(sensors)
