"""Expected Timing Inspector — studio tab (live readout bound to VehicleSensors)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGridLayout, QLabel
from simpulse_sdk import VehicleSensors

if TYPE_CHECKING:
    from simpulse.builtin_plugins.expected_timing.plugin import ExpectedTimingPlugin


class ExpectedTimingTabWidget(QWidget):
    def __init__(self, plugin: ExpectedTimingPlugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        lay = QVBoxLayout(self)
        g = QGridLayout()

        self.est_lbl = QLabel("--:--.---")
        self.est_lbl.setStyleSheet("font-size: 26px; font-weight: bold; color:#00d2ff;")
        g.addWidget(QLabel("EXPECTED"), 0, 0)
        g.addWidget(self.est_lbl, 0, 1)

        self.delta_lbl = QLabel("--")
        g.addWidget(QLabel("Δ live"), 1, 0)
        g.addWidget(self.delta_lbl, 1, 1)

        self.sec_lbl = QLabel("S1 --   S2 --   S3 --")
        self.sec_lbl.setWordWrap(True)
        g.addWidget(QLabel("Expected sectors"), 2, 0)
        g.addWidget(self.sec_lbl, 2, 1)

        self.refs_lbl = QLabel("--")
        self.refs_lbl.setWordWrap(True)
        g.addWidget(QLabel("References"), 3, 0)
        g.addWidget(self.refs_lbl, 3, 1)

        self.state_lbl = QLabel("no data yet")
        g.addWidget(self.state_lbl, 4, 0, 1, 2)
        lay.addLayout(g)
        lay.addStretch()

    def update_sensors(self, sensors: VehicleSensors) -> None:
        if not self.isVisible():
            return
        self.est_lbl.setText(sensors.estimated_lap_time_str if sensors.has_delta_reference else "--:--.---")
        tok = sensors.expected_status
        d = sensors.delta_time
        pr_suffix = "  [PR]" if sensors.expected_lap_is_pr else ""
        self.delta_lbl.setText(
            ((f"{d:+.3f} s" if abs(d) > 0.0005 else "±0.000 s") if sensors.has_delta_reference else "--")
            + ("" if sensors.has_delta_reference else "  (no ref)") + pr_suffix)
        # Projected sector time, not the raw completed split — colour is
        # session-scoped only; all-time-best is flagged as "[PR]" text.
        parts = "   ".join([
            f"S1 {sensors.expected_sector1_time}[{sensors.expected_sector1_status}]"
            + ("[PR]" if sensors.expected_sector1_is_pr else ""),
            f"S2 {sensors.expected_sector2_time}[{sensors.expected_sector2_status}]"
            + ("[PR]" if sensors.expected_sector2_is_pr else ""),
            f"S3 {sensors.expected_sector3_time}[{sensors.expected_sector3_status}]"
            + ("[PR]" if sensors.expected_sector3_is_pr else ""),
        ])
        self.sec_lbl.setText(parts)
        self.refs_lbl.setText(
            f"my session best {sensors.my_session_best_lap_time_str}   "
            f"session best {sensors.session_best_lap_time_str}   "
            f"my all-time best {sensors.my_all_time_best_lap_time_str}"
        )
        self.state_lbl.setText(
            f"expected token: {tok if sensors.has_delta_reference else '- (no active reference)'} · "
            f"sector {sensors.current_sector} · freeze {sensors.is_lap_freeze_active}")
