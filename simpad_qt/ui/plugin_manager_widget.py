"""
SimPad Qt6 Plugin Manager UI Tab Widget.
Provides an interactive dashboard to inspect, enable, disable, and monitor plugins.
"""

from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QTextEdit, QMessageBox
)
from simpad_qt.plugins.manager import PluginManager
from simpad_qt.plugins.contracts import (
    PluginState, PluginErrorReport, ITabProvider, ITelemetrySubscriber, IHudWidgetProvider
)


class PluginManagerWidget(QWidget):
    """Interactive Qt6 tab to manage plugins."""

    def __init__(self, plugin_manager: PluginManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.plugin_manager = plugin_manager
        self._init_ui()

        # Connect signals
        self.plugin_manager.plugin_loaded.connect(self._refresh_table)
        self.plugin_manager.plugin_unloaded.connect(self._refresh_table)
        self.plugin_manager.plugin_state_changed.connect(self._on_state_changed)
        self.plugin_manager.plugin_faulted.connect(self._on_faulted)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Header info
        header_group = QGroupBox("🔌 SimPad Extension & Plugin Hub", self)
        h_layout = QVBoxLayout(header_group)
        info_lbl = QLabel(
            "Manage modular SimPad plugins. Plugins can inject interactive studio tabs, "
            "subscribe to high-frequency telemetry, and render transparent in-game HUD overlays.",
            header_group
        )
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet("color: #94a3b8; font-size: 13px;")
        h_layout.addWidget(info_lbl)
        layout.addWidget(header_group)

        # Table of plugins
        self.table = QTableWidget(self)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Icon", "Plugin Name", "Version", "Capabilities", "Status", "Action"
        ])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table)

        # Bottom section: Plugin details & actions
        detail_group = QGroupBox("Plugin Inspector", self)
        d_layout = QVBoxLayout(detail_group)
        self.detail_text = QTextEdit(detail_group)
        self.detail_text.setReadOnly(True)
        self.detail_text.setFixedHeight(90)
        self.detail_text.setStyleSheet("background-color: #0f1115; border: 1px solid #23272e; color: #cbd5e1;")
        d_layout.addWidget(self.detail_text)

        btn_row = QHBoxLayout()
        self.toggle_btn = QPushButton("Toggle Enable/Disable", self)
        self.toggle_btn.clicked.connect(self._toggle_selected_plugin)
        btn_row.addWidget(self.toggle_btn)

        btn_row.addStretch()
        d_layout.addLayout(btn_row)
        layout.addWidget(detail_group)

        self._refresh_table()

    def _refresh_table(self) -> None:
        """Populate the plugin list table."""
        plugins = self.plugin_manager.plugins
        self.table.setRowCount(len(plugins))

        for row, (pid, plugin) in enumerate(plugins.items()):
            meta = plugin.metadata

            # Icon
            icon_item = QTableWidgetItem(meta.icon)
            icon_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, icon_item)

            # Name
            name_item = QTableWidgetItem(f"{meta.name}\n({pid})")
            self.table.setItem(row, 1, name_item)

            # Version
            ver_item = QTableWidgetItem(meta.version)
            ver_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, ver_item)

            # Capabilities
            caps = []
            if isinstance(plugin, ITabProvider):
                caps.append("Tab")
            if isinstance(plugin, ITelemetrySubscriber):
                caps.append("Telem")
            if isinstance(plugin, IHudWidgetProvider):
                caps.append("HUD")
            caps_item = QTableWidgetItem(" | ".join(caps) if caps else "None")
            caps_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, caps_item)

            # Status
            status_str = plugin.state.name
            status_item = QTableWidgetItem(status_str)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if plugin.state == PluginState.ENABLED:
                status_item.setForeground(Qt.GlobalColor.green)
            elif plugin.state == PluginState.FAULTED:
                status_item.setForeground(Qt.GlobalColor.red)
            else:
                status_item.setForeground(Qt.GlobalColor.gray)
            self.table.setItem(row, 4, status_item)

            # Action button
            action_btn = QPushButton("Disable" if plugin.state == PluginState.ENABLED else "Enable")
            action_btn.clicked.connect(lambda checked=False, p_id=pid: self._toggle_plugin(p_id))
            self.table.setCellWidget(row, 5, action_btn)

    def _on_selection_changed(self) -> None:
        selected_rows = self.table.selectedIndexes()
        if not selected_rows:
            self.detail_text.clear()
            return

        row = selected_rows[0].row()
        plugins = list(self.plugin_manager.plugins.values())
        if row < len(plugins):
            p = plugins[row]
            meta = p.metadata
            self.detail_text.setHtml(
                f"<b>{meta.name}</b> (<code>{meta.id}</code>) v{meta.version}<br/>"
                f"<b>Author:</b> {meta.author}<br/>"
                f"<b>Description:</b> {meta.description}<br/>"
                f"<b>State:</b> <span style='color: {'#22c55e' if p.state == PluginState.ENABLED else '#ef4444'}'>{p.state.name}</span>"
            )

    def _toggle_selected_plugin(self) -> None:
        selected_rows = self.table.selectedIndexes()
        if not selected_rows:
            return
        row = selected_rows[0].row()
        pids = list(self.plugin_manager.plugins.keys())
        if row < len(pids):
            self._toggle_plugin(pids[row])

    def _toggle_plugin(self, plugin_id: str) -> None:
        plugin = self.plugin_manager.plugins.get(plugin_id)
        if not plugin:
            return
        if plugin.state == PluginState.ENABLED:
            self.plugin_manager.disable_plugin(plugin_id)
        else:
            self.plugin_manager.enable_plugin(plugin_id)
        self._refresh_table()

    def _on_state_changed(self, plugin_id: str, state: PluginState) -> None:
        self._refresh_table()

    def _on_faulted(self, report: PluginErrorReport) -> None:
        self._refresh_table()
        QMessageBox.warning(
            self,
            "Circuit Breaker Tripped",
            f"Plugin '{report.plugin_id}' has been automatically disabled in action '{report.action_name}' "
            f"after {report.consecutive_error_count} repeated exceptions:\n\n{report.error_message}"
        )
