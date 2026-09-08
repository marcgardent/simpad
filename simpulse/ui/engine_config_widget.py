"""
SimPulse Qt6 Engines Configuration Tab.
Central place for tuning the runtime engines that compute derived telemetry
(currently just DeltaEngine — see ReferenceLapManager). No Engine base class
exists in the codebase; this tab is UI-only infrastructure, one QGroupBox per
engine, added here as engines gain tunable settings.
"""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGridLayout, QGroupBox, QSlider, QScrollArea
)

from simpulse.core.config import ConfigManager
from simpulse.core.reference_lap import ReferenceLapManager


def _format_ms(ms: int) -> str:
    """Display label for a millisecond slider value — 'Xms' below 1s, 'X.Xs' at/above it."""
    if ms >= 1000:
        return f"{ms / 1000.0:.1f}s"
    return f"{ms}ms"


class EngineConfigWidget(QWidget):
    """Studio Tab for tuning DeltaEngine's display-decision settings —
    smoothing window, finish-line freeze duration, and TimeStatus equality
    tolerance. Each control applies immediately to the live DeltaEngine
    (via ReferenceLapManager's setters) and persists through ConfigManager,
    same dual-write pattern as the rest of the Studio's config tabs."""

    def __init__(
        self,
        config_mgr: ConfigManager,
        reference_lap_mgr: ReferenceLapManager,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.config_mgr = config_mgr
        self.reference_lap_mgr = reference_lap_mgr
        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)

        content = QWidget(scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        app_cfg = self.config_mgr.get_app_settings()

        group = QGroupBox("⚙️ Delta Engine", content)
        g_layout = QGridLayout(group)
        g_layout.setSpacing(10)

        # Smoothing window: moving-average window (game time) for
        # DeltaEngine.smoothed_live_delta / time_status_smoothed — same
        # 0-2000ms range as the slider this replaces (used to live in the
        # Cockpit HUD plugin, now a single engine-level setting shared by
        # every consumer).
        window_ms = int(round(app_cfg.delta_smoothing_window_s * 1000))
        self.lbl_smoothing = QLabel(f"Smoothing Window: {_format_ms(window_ms)} (game time)", group)
        g_layout.addWidget(self.lbl_smoothing, 0, 0)
        self.slider_smoothing = QSlider(Qt.Orientation.Horizontal, group)
        self.slider_smoothing.setRange(0, 2000)
        self.slider_smoothing.setValue(window_ms)
        self.slider_smoothing.valueChanged.connect(self._on_smoothing_changed)
        g_layout.addWidget(self.slider_smoothing, 0, 1)

        # Finish-line freeze duration.
        freeze_ms = int(round(app_cfg.delta_freeze_duration * 1000))
        self.lbl_freeze = QLabel(f"Finish-Line Freeze: {app_cfg.delta_freeze_duration:.1f}s", group)
        g_layout.addWidget(self.lbl_freeze, 1, 0)
        self.slider_freeze = QSlider(Qt.Orientation.Horizontal, group)
        self.slider_freeze.setRange(0, 10000)
        self.slider_freeze.setValue(freeze_ms)
        self.slider_freeze.valueChanged.connect(self._on_freeze_changed)
        g_layout.addWidget(self.slider_freeze, 1, 1)

        # TimeStatus equality tolerance (eps).
        eps_ms = int(round(app_cfg.delta_time_status_eps * 1000))
        self.lbl_eps = QLabel(f"Equality Tolerance (eps): {app_cfg.delta_time_status_eps:.3f}s", group)
        g_layout.addWidget(self.lbl_eps, 2, 0)
        self.slider_eps = QSlider(Qt.Orientation.Horizontal, group)
        self.slider_eps.setRange(0, 1000)
        self.slider_eps.setValue(eps_ms)
        self.slider_eps.valueChanged.connect(self._on_eps_changed)
        g_layout.addWidget(self.slider_eps, 2, 1)

        layout.addWidget(group)
        layout.addStretch()

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

    def _on_smoothing_changed(self, ms: int) -> None:
        self.lbl_smoothing.setText(f"Smoothing Window: {_format_ms(ms)} (game time)")
        self.reference_lap_mgr.set_delta_smoothing_window_s(ms / 1000.0)

    def _on_freeze_changed(self, ms: int) -> None:
        val = ms / 1000.0
        self.lbl_freeze.setText(f"Finish-Line Freeze: {val:.1f}s")
        self.reference_lap_mgr.set_freeze_duration(val)

    def _on_eps_changed(self, ms: int) -> None:
        val = ms / 1000.0
        self.lbl_eps.setText(f"Equality Tolerance (eps): {val:.3f}s")
        self.reference_lap_mgr.set_time_status_eps(val)
