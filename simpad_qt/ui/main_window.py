"""
SimPad Qt6 Main Studio Window.
Hosts the centralized tab navigation, telemetry controls, game plugin config, overlay state manager,
and the Core Status Bar.
"""

from typing import Dict, Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTabWidget, QComboBox
)

from simpad_qt.plugins.manager import PluginManager
from simpad_qt.plugins.contracts import ITabProvider, PluginState
from simpad_qt.core.game_plugin_manager import GamePluginManager
from simpad_qt.core.game_process_watcher import GameProcessWatcher
from simpad_qt.core.overlay_state_machine import OverlayStateMachine, OverlayDisplayMode
from simpad_qt.core.telemetry_bus import TelemetryBus
from simpad_qt.core.config import ConfigManager
from simpad_qt.ui.overlay_window import SimPadHudOverlayWindow
from simpad_qt.ui.plugin_manager_widget import PluginManagerWidget
from simpad_qt.ui.game_plugin_config_widget import GamePluginConfigWidget
from simpad_qt.ui.status_bar import SimPadCoreStatusBar
from simpad_qt.ui.theme import DARK_STYLESHEET
from simpad_qt.core.telemetry import VehicleSensors


class SimPadQtMainWindow(QMainWindow):
    """Main Studio Console Window for SimPad Qt6."""

    def __init__(
        self,
        plugin_manager: PluginManager,
        game_plugin_mgr: GamePluginManager,
        process_watcher: GameProcessWatcher,
        overlay_state_machine: OverlayStateMachine,
        telemetry_bus: TelemetryBus,
        config_mgr: ConfigManager,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.plugin_manager = plugin_manager
        self.game_plugin_mgr = game_plugin_mgr
        self.process_watcher = process_watcher
        self.overlay_state_machine = overlay_state_machine
        self.telemetry_bus = telemetry_bus
        self.config_mgr = config_mgr

        self.setWindowTitle("SimPad Studio Console (Qt6 Pure)")
        self.resize(1180, 760)
        self.setStyleSheet(DARK_STYLESHEET)

        # Create overlay window
        self.overlay_window = SimPadHudOverlayWindow(self.plugin_manager)

        self._plugin_tabs: Dict[str, QWidget] = {}

        self._init_ui()
        self._build_plugin_tabs()

        # Connect telemetry bus
        self.telemetry_bus.telemetry_updated.connect(self._on_telemetry_updated)
        self.telemetry_bus.telemetry_fps_changed.connect(self._on_fps_changed)
        self.telemetry_bus.metrics_updated.connect(self._on_metrics_updated)

        # Connect overlay state machine
        self.overlay_state_machine.overlay_visibility_changed.connect(self._on_overlay_visibility_changed)

        # Connect plugin manager state changes to dynamically add/remove tabs
        self.plugin_manager.plugin_state_changed.connect(self._on_plugin_state_changed)

        # Initial state from typed config
        if self.config_mgr.config.app.mock_telemetry:
            self.telemetry_bus.start_mock()

    def _init_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        # Top Control Bar
        top_bar = QHBoxLayout()

        logo_lbl = QLabel("🏎️ <b>SIMPAD</b> <span style='color:#00d2ff;'>STUDIO</span>", self)
        logo_lbl.setStyleSheet("font-size: 16px; color: #ffffff;")
        top_bar.addWidget(logo_lbl)

        top_bar.addSpacing(20)

        # Telemetry FPS badge
        self.fps_badge = QLabel("Telem: 0.0 FPS", self)
        self.fps_badge.setStyleSheet(
            "background-color: #1e293b; color: #38bdf8; padding: 4px 10px; "
            "border-radius: 4px; font-weight: bold; border: 1px solid #334155;"
        )
        top_bar.addWidget(self.fps_badge)

        # Bandwidth badge
        self.bw_badge = QLabel("Bandwidth: 0.0 Kb/s", self)
        self.bw_badge.setStyleSheet(
            "background-color: #1e293b; color: #22c55e; padding: 4px 10px; "
            "border-radius: 4px; font-weight: bold; border: 1px solid #334155;"
        )
        top_bar.addWidget(self.bw_badge)

        top_bar.addStretch()

        # Mock Telemetry toggle button
        is_mock = self.config_mgr.config.app.mock_telemetry
        self.mock_btn = QPushButton(f"Simulation Feeder: {'ON' if is_mock else 'OFF'}", self)
        self.mock_btn.setCheckable(True)
        self.mock_btn.setChecked(is_mock)
        self.mock_btn.clicked.connect(self._toggle_mock_telemetry)
        top_bar.addWidget(self.mock_btn)

        # Overlay Mode Selector (AUTO / FORCE / OFF)
        hud_mode_lbl = QLabel("HUD Policy:", self)
        hud_mode_lbl.setStyleSheet("color: #94a3b8; font-weight: 500;")
        top_bar.addWidget(hud_mode_lbl)

        self.hud_mode_combo = QComboBox(self)
        self.hud_mode_combo.addItem("Auto (On-Track Only)", OverlayDisplayMode.AUTO)
        self.hud_mode_combo.addItem("Force Visible", OverlayDisplayMode.FORCE_VISIBLE)
        self.hud_mode_combo.addItem("Disabled", OverlayDisplayMode.FORCE_HIDDEN)

        current_mode = self.overlay_state_machine.display_mode
        idx = self.hud_mode_combo.findData(current_mode)
        if idx != -1:
            self.hud_mode_combo.setCurrentIndex(idx)
        self.hud_mode_combo.currentIndexChanged.connect(self._on_hud_mode_changed)
        top_bar.addWidget(self.hud_mode_combo)

        # Overlay Debug Boxes button
        self.debug_box_btn = QPushButton("HUD Slots Debug", self)
        self.debug_box_btn.setCheckable(True)
        self.debug_box_btn.setChecked(False)
        self.debug_box_btn.clicked.connect(self._toggle_debug_boxes)
        top_bar.addWidget(self.debug_box_btn)

        root_layout.addLayout(top_bar)

        # Central Tabs Container
        self.tab_widget = QTabWidget(self)
        root_layout.addWidget(self.tab_widget)

        # Core Tab 0: Extensions Hub
        self.pm_tab = PluginManagerWidget(self.plugin_manager, self)
        self.tab_widget.addTab(self.pm_tab, "🔌 Extensions Hub")

        # Core Tab 1: Game Plugin & Channels Config
        self.game_cfg_tab = GamePluginConfigWidget(self.game_plugin_mgr, self.plugin_manager, self)
        self.tab_widget.addTab(self.game_cfg_tab, "🎮 Game Plugin & Channels")

        # Core Footer Status Bar
        self.status_bar = SimPadCoreStatusBar(
            process_watcher=self.process_watcher,
            overlay_state_machine=self.overlay_state_machine,
            telemetry_bus=self.telemetry_bus,
            plugin_manager=self.plugin_manager,
            parent=self
        )
        self.setStatusBar(self.status_bar)

    def _build_plugin_tabs(self) -> None:
        """Inject tabs for all active plugins that implement ITabProvider."""
        for plugin in self.plugin_manager.plugins.values():
            if plugin.state == PluginState.ENABLED and isinstance(plugin, ITabProvider):
                self._add_plugin_tab(plugin)

    def _add_plugin_tab(self, plugin: ITabProvider) -> None:
        pid = plugin.metadata.id
        if pid in self._plugin_tabs:
            return

        tab_widget = plugin.create_tab_widget(self)
        title = f"{plugin.get_tab_icon()} {plugin.get_tab_title()}"
        self.tab_widget.addTab(tab_widget, title)
        self._plugin_tabs[pid] = tab_widget

    def _remove_plugin_tab(self, plugin_id: str) -> None:
        widget = self._plugin_tabs.pop(plugin_id, None)
        if widget:
            index = self.tab_widget.indexOf(widget)
            if index != -1:
                self.tab_widget.removeTab(index)

    def _on_plugin_state_changed(self, plugin_id: str, state: PluginState) -> None:
        plugin = self.plugin_manager.plugins.get(plugin_id)
        if not plugin or not isinstance(plugin, ITabProvider):
            return

        if state == PluginState.ENABLED:
            self._add_plugin_tab(plugin)
        else:
            self._remove_plugin_tab(plugin_id)

    def _toggle_mock_telemetry(self, checked: bool) -> None:
        self.config_mgr.config.app.mock_telemetry = checked
        self.config_mgr.save()
        if checked:
            self.mock_btn.setText("Simulation Feeder: ON")
            self.telemetry_bus.start_mock()
        else:
            self.mock_btn.setText("Simulation Feeder: OFF")
            self.telemetry_bus.start_udp_server()

    def _on_hud_mode_changed(self, index: int) -> None:
        mode = self.hud_mode_combo.currentData()
        self.overlay_state_machine.set_display_mode(mode)

    def _on_overlay_visibility_changed(self, is_visible: bool) -> None:
        if is_visible:
            self.overlay_window.show()
        else:
            self.overlay_window.hide()

    def _toggle_debug_boxes(self, checked: bool) -> None:
        self.overlay_window.set_debug_boxes(checked)

    def _on_telemetry_updated(self, sensors: VehicleSensors) -> None:
        self.overlay_window.update_telemetry(sensors)

    def _on_fps_changed(self, fps: float) -> None:
        self.fps_badge.setText(f"Telem: {fps:.1f} FPS")

    def _on_metrics_updated(self) -> None:
        bw = self.telemetry_bus.total_measured_kbs
        self.bw_badge.setText(f"Bandwidth: {bw:.1f} Kb/s")

    def closeEvent(self, event) -> None:
        self.process_watcher.stop()
        self.overlay_window.close()
        self.telemetry_bus.stop()
        self.plugin_manager.unload_all()
        super().closeEvent(event)
