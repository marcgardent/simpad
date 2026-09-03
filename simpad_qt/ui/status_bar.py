"""
SimPad Qt6 Core Footer Status Bar.
Displays real-time UDP socket status, game process execution state, window foreground/background focus,
contextual scene detection (On-Track, Garage/Pause, Menu, Desktop), network throughput, active channels,
plugin health, and HUD overlay state.
"""

from __future__ import annotations
from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QStatusBar, QWidget, QLabel

from simpad_qt.core.game_process_watcher import GameProcessWatcher, GameStatus, GameFocusState
from simpad_qt.core.overlay_state_machine import OverlayStateMachine, GameSceneState, OverlayDisplayMode, OverlayStateSnapshot
from simpad_qt.core.telemetry_bus import TelemetryBus, UdpStreamStatus
from simpad_qt.plugins.manager import PluginManager
from simpad_qt.plugins.contracts import PluginState


class SimPadCoreStatusBar(QStatusBar):
    """
    Host Core Status Bar showing infrastructure health, UDP status, game scene, and HUD overlay visibility.
    """

    def __init__(
        self,
        process_watcher: GameProcessWatcher,
        overlay_state_machine: OverlayStateMachine,
        telemetry_bus: TelemetryBus,
        plugin_manager: PluginManager,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.process_watcher = process_watcher
        self.overlay_state_machine = overlay_state_machine
        self.telemetry_bus = telemetry_bus
        self.plugin_manager = plugin_manager

        self.setSizeGripEnabled(False)
        self.setStyleSheet(
            "QStatusBar { background-color: #0b0d11; border-top: 1px solid #1e293b; color: #94a3b8; font-size: 12px; }"
            "QStatusBar::item { border: none; }"
        )

        self._init_widgets()

        # Connect signals
        self.process_watcher.status_changed.connect(self._on_game_status_changed)
        self.overlay_state_machine.snapshot_updated.connect(self._on_overlay_snapshot_updated)
        self.telemetry_bus.metrics_updated.connect(self._on_metrics_updated)
        self.telemetry_bus.stream_status_changed.connect(self._on_stream_status_changed)
        self.plugin_manager.plugin_state_changed.connect(self._on_plugins_changed)
        self.plugin_manager.plugin_faulted.connect(self._on_plugins_changed)

        # Initial render
        self._on_game_status_changed(self.process_watcher.current_status)
        self._on_overlay_snapshot_updated(self.overlay_state_machine.get_snapshot())
        self._on_metrics_updated()
        self._on_plugins_changed()

    def _init_widgets(self) -> None:
        # Left side: Core Host Status message
        self.lbl_host_msg = QLabel("SimPad Core Stack Initialized", self)
        self.lbl_host_msg.setStyleSheet("color: #64748b; font-weight: 500; padding-left: 6px;")
        self.addWidget(self.lbl_host_msg, 1)

        # Right side permanent widgets:
        # 1. Game Scene & Focus Badge
        self.badge_game = QLabel(self)
        self.badge_game.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._style_badge(self.badge_game, "LMU: NOT RUNNING", bg="#1e293b", fg="#94a3b8", border="#334155")
        self.addPermanentWidget(self.badge_game)

        # 2. UDP Telemetry Status Badge
        self.badge_udp = QLabel(self)
        self.badge_udp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._style_badge(self.badge_udp, "UDP: STOPPED", bg="#1e293b", fg="#94a3b8", border="#334155")
        self.addPermanentWidget(self.badge_udp)

        # 3. Bandwidth & Active Channels Badge
        self.badge_bandwidth = QLabel(self)
        self.badge_bandwidth.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._style_badge(self.badge_bandwidth, "0.0 Kb/s | 0/10 Ch.", bg="#0f172a", fg="#38bdf8", border="#1e293b")
        self.addPermanentWidget(self.badge_bandwidth)

        # 4. Plugins Health Badge
        self.badge_plugins = QLabel(self)
        self.badge_plugins.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._style_badge(self.badge_plugins, "Plugins: 0 Active", bg="#0f172a", fg="#a855f7", border="#1e293b")
        self.addPermanentWidget(self.badge_plugins)

        # 5. Overlay Status Badge
        self.badge_overlay = QLabel(self)
        self.badge_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._style_badge(self.badge_overlay, "HUD: AUTO (STANDBY)", bg="#1e293b", fg="#94a3b8", border="#334155")
        self.addPermanentWidget(self.badge_overlay)

    def _style_badge(self, label: QLabel, text: str, bg: str, fg: str, border: str) -> None:
        if label.text() != text:
            label.setText(text)
        style_key = f"{bg}_{fg}_{border}"
        if getattr(label, "_current_style_key", None) != style_key:
            setattr(label, "_current_style_key", style_key)
            label.setStyleSheet(
                f"background-color: {bg}; color: {fg}; border: 1px solid {border}; "
                f"border-radius: 4px; padding: 2px 8px; font-weight: 600; font-size: 11px;"
            )

    def _on_game_status_changed(self, status: GameStatus) -> None:
        self.overlay_state_machine.update_game_status(status)

    def _on_overlay_snapshot_updated(self, snapshot: OverlayStateSnapshot) -> None:
        # 1. Update Game Scene Badge
        if snapshot.scene == GameSceneState.ON_TRACK_DRIVING:
            self._style_badge(self.badge_game, "🟢 LMU: ON TRACK", bg="#064e3b", fg="#34d399", border="#059669")
            self.lbl_host_msg.setText("In-Game Driving on track — Real-time telemetry active")
        elif snapshot.scene == GameSceneState.GARAGE_PAUSE:
            self._style_badge(self.badge_game, "🟡 LMU: GARAGE / PAUSE", bg="#78350f", fg="#fbbf24", border="#d97706")
            self.lbl_host_msg.setText("In-Game Pit Garage / Setup / Pause — HUD auto-recessed")
        elif snapshot.scene == GameSceneState.MAIN_MENU:
            self._style_badge(self.badge_game, "🟡 LMU: MAIN MENU", bg="#78350f", fg="#fbbf24", border="#d97706")
            self.lbl_host_msg.setText("Game running in Main Menu — HUD standing by")
        elif self.process_watcher.current_status.is_running:
            self._style_badge(self.badge_game, "🎮 LMU: BACKGROUND", bg="#78350f", fg="#fbbf24", border="#d97706")
            self.lbl_host_msg.setText("Game running in background")
        else:
            self._style_badge(self.badge_game, "🎮 LMU: NOT RUNNING", bg="#1e293b", fg="#64748b", border="#334155")
            self.lbl_host_msg.setText("Waiting for game execution...")

        # 2. Update Overlay Policy & Visibility Badge
        if snapshot.display_mode == OverlayDisplayMode.FORCE_HIDDEN:
            self._style_badge(self.badge_overlay, "HUD: FORCE OFF", bg="#1e293b", fg="#94a3b8", border="#334155")
        elif snapshot.display_mode == OverlayDisplayMode.FORCE_VISIBLE:
            self._style_badge(self.badge_overlay, "HUD: FORCE VISIBLE", bg="#064e3b", fg="#34d399", border="#059669")
        else:  # AUTO
            if snapshot.is_overlay_visible:
                self._style_badge(self.badge_overlay, "HUD: AUTO (VISIBLE)", bg="#064e3b", fg="#34d399", border="#059669")
            else:
                self._style_badge(self.badge_overlay, "HUD: AUTO (HIDDEN)", bg="#1e293b", fg="#94a3b8", border="#334155")

    def _on_stream_status_changed(self, stream_status: UdpStreamStatus) -> None:
        self._update_udp_ui(stream_status)

    def _on_metrics_updated(self) -> None:
        status = self.telemetry_bus.stream_status
        self._update_udp_ui(status)

        # Update bandwidth and active channels
        kbs = self.telemetry_bus.total_measured_kbs
        active_ch = self.telemetry_bus.active_channels_count
        self.badge_bandwidth.setText(f"{kbs:.1f} Kb/s | {active_ch}/10 Ch.")

    def _update_udp_ui(self, status: UdpStreamStatus) -> None:
        port = self.telemetry_bus.udp_port
        hz = self.telemetry_bus.total_measured_hz

        if status == UdpStreamStatus.RECEIVING:
            self._style_badge(
                self.badge_udp,
                f"📡 UDP: STREAMING ({port} @ {hz:.0f}Hz)",
                bg="#064e3b", fg="#22c55e", border="#15803d"
            )
        elif status == UdpStreamStatus.LISTENING:
            self._style_badge(
                self.badge_udp,
                f"📡 UDP: LISTENING ({port})",
                bg="#78350f", fg="#f59e0b", border="#b45309"
            )
        elif status == UdpStreamStatus.SIMULATION:
            self._style_badge(
                self.badge_udp,
                f"🟣 UDP: SIMULATION (Mock {hz:.0f}Hz)",
                bg="#3b0764", fg="#c084fc", border="#7e22ce"
            )
        else:
            self._style_badge(
                self.badge_udp,
                "📡 UDP: STOPPED",
                bg="#1e293b", fg="#64748b", border="#334155"
            )

    def _on_plugins_changed(self, *args) -> None:
        plugins = self.plugin_manager.plugins
        active_count = sum(1 for p in plugins.values() if p.state == PluginState.ENABLED)
        faulted_count = sum(1 for p in plugins.values() if p.state == PluginState.FAULTED)

        if faulted_count > 0:
            self._style_badge(
                self.badge_plugins,
                f"Plugins: {active_count} Active ({faulted_count} Faulted!)",
                bg="#7f1d1d", fg="#f87171", border="#b91c1c"
            )
        else:
            self._style_badge(
                self.badge_plugins,
                f"Plugins: {active_count} Active",
                bg="#0f172a", fg="#a855f7", border="#4c1d95"
            )
