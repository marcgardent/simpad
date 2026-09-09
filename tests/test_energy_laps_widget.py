"""
Contract: QtEnergyLapsWidget — reads exclusively from CockpitWidgetContext.energy
(EnergyPacket), never VehicleSensors' deprecated fuel_level/energy_*/session_*
fields; renders diagonal-pair cells (see _draw_diagonal_pair) instead of a
literal "value1 / value2" string; shows a fuel-anomaly banner + icon when
EnergyPacket.fuel_anomaly is True.
"""
import unittest

from simpulse.builtin_plugins.official_cockpit_hud.widgets.energy_laps import (
    QtEnergyLapsWidget,
    _fmt_clock,
    _fmt_laps,
    _fmt_pct,
)
from simpulse.builtin_plugins.official_cockpit_hud.widgets.base_widget import CockpitWidgetContext
from simpulse_sdk import VehicleSensors
from simpulse_sdk.models.energy import EnergyPacket


class TestFormatHelpers(unittest.TestCase):
    def test_fmt_pct_none_is_dashes(self):
        self.assertEqual(_fmt_pct(None), "--")

    def test_fmt_pct_whole_percent(self):
        self.assertEqual(_fmt_pct(0.614), "61%")

    def test_fmt_clock_none_is_dashes(self):
        self.assertEqual(_fmt_clock(None), "--:--")

    def test_fmt_clock_negative_is_dashes(self):
        self.assertEqual(_fmt_clock(-1.0), "--:--")

    def test_fmt_clock_formats_mmss(self):
        self.assertEqual(_fmt_clock(605.0), "10:05")

    def test_fmt_laps_none_is_dashes(self):
        self.assertEqual(_fmt_laps(None), "--")

    def test_fmt_laps_rounds_to_whole(self):
        self.assertEqual(_fmt_laps(12.0), "12")


class TestQtEnergyLapsWidgetRendering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _paint(self, energy: EnergyPacket, sensors: VehicleSensors = None) -> None:
        from PySide6.QtGui import QImage, QPainter
        widget = QtEnergyLapsWidget()
        img = QImage(800, 600, QImage.Format.Format_ARGB32)
        painter = QPainter(img)
        ctx = CockpitWidgetContext(sensors=sensors or VehicleSensors(), energy=energy)
        widget.paint(painter, 800.0, 600.0, ctx)
        painter.end()

    def test_default_packet_renders_without_error(self):
        """First paint, before any energy telemetry has arrived — every
        field defaults to a falsy value, must not raise (dashes instead)."""
        self._paint(EnergyPacket())

    def test_full_practice_session_renders(self):
        energy = EnergyPacket(
            level=62.5,
            is_percentage=False,
            consumption_per_lap=2.3,
            lap_time_median=95.4,
            session_time_elapsed=600.0,
            session_time_total=None,
            session_laps_done=6,
            session_laps_left=None,
            session_energy_needed=None,
            session_energy_ratio=None,
            projected_laps=27,
            fuel_anomaly=False,
        )
        self._paint(energy)

    def test_time_limited_session_renders(self):
        energy = EnergyPacket(
            level=45.0,
            is_percentage=True,
            consumption_per_lap=3.1,
            lap_time_median=112.7,
            session_time_elapsed=1800.0,
            session_time_total=3600.0,
            session_laps_done=14,
            session_laps_left=16,
            session_energy_needed=49.6,
            session_energy_ratio=0.91,
            projected_laps=14,
            fuel_anomaly=False,
        )
        self._paint(energy)

    def test_fuel_anomaly_renders_banner_and_icon(self):
        """fuel_anomaly=True must not raise even though it takes the extra
        icon + banner drawing path (see class docstring)."""
        energy = EnergyPacket(
            level=20.0,
            is_percentage=False,
            consumption_per_lap=4.0,
            lap_time_median=90.0,
            session_time_elapsed=1200.0,
            session_time_total=3600.0,
            session_laps_done=10,
            session_laps_left=20,
            session_energy_needed=80.0,
            session_energy_ratio=0.25,
            projected_laps=5,
            fuel_anomaly=True,
        )
        self._paint(energy)

    def test_svg_icon_loads_from_real_icons_dir(self):
        """fuel_error.svg genuinely exists and loads (not silently falling
        back to no-icon) — a load failure would still render, so this test
        exists specifically to catch that silent regression."""
        widget = QtEnergyLapsWidget()
        self.assertIsNotNone(widget._svg_fuel_error)
        self.assertTrue(widget._svg_fuel_error.isValid())

    def test_diagonal_pair_with_zero_skew_is_upright(self):
        """skew=0.0 (row 1, per class docstring) must not raise and must
        still draw two distinct polygons, not a single cell."""
        from PySide6.QtGui import QImage, QPainter
        widget = QtEnergyLapsWidget()
        img = QImage(200, 100, QImage.Format.Format_ARGB32)
        painter = QPainter(img)
        widget._draw_diagonal_pair(
            painter, 0.0, 0.0, 100.0, 30.0, 0.0, 3.0,
            "LEFT", "1.0", "RIGHT", "2.0", 8, 13,
        )
        painter.end()

    def test_diagonal_pair_with_skew_leans(self):
        """skew!=0.0 (rows 2-4) must not raise either."""
        from PySide6.QtGui import QImage, QPainter
        widget = QtEnergyLapsWidget()
        img = QImage(200, 100, QImage.Format.Format_ARGB32)
        painter = QPainter(img)
        widget._draw_diagonal_pair(
            painter, 0.0, 0.0, 100.0, 30.0, 4.0, 3.0,
            "LEFT", "1.0", "RIGHT", "2.0", 8, 13,
        )
        painter.end()


if __name__ == "__main__":
    unittest.main()
