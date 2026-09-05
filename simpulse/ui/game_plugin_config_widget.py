"""
SimPulse Qt6 Game Telemetry Plugin Installer & Channel Configuration Tab.
Allows installing the native DLL, visualizing active plugin desiderata, and tuning channel frequencies (Hz).
"""

from typing import Optional, Dict
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QComboBox, QGridLayout, QMessageBox, QScrollArea, QCheckBox,
    QSizePolicy
)

from simpulse.core.game_plugin_manager import GamePluginManager
from simpulse.core.telemetry_channels import TelemetryChannel
from simpulse.plugins.manager import PluginManager


class GamePluginConfigWidget(QWidget):
    """Studio Tab for installing game DLL and configuring telemetry rates/channels."""

    def __init__(
        self,
        game_plugin_mgr: GamePluginManager,
        plugin_mgr: PluginManager,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.game_plugin_mgr = game_plugin_mgr
        self.plugin_mgr = plugin_mgr
        self._rate_combos: Dict[TelemetryChannel, QComboBox] = {}

        self._init_ui()

        # Connect signals
        self.game_plugin_mgr.state_changed.connect(self._refresh_ui)
        self.plugin_mgr.plugin_state_changed.connect(self._refresh_desiderata_table)

    def _init_ui(self) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        content = QWidget(scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # =====================================================================
        # 1. Detected Game Simulators & Plugin Deployment
        # =====================================================================
        self.inst_group = QGroupBox("🎮 Detected Simulators & isiMotor_RawUDP.dll Deployment", content)
        self.inst_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.inst_layout = QVBoxLayout(self.inst_group)

        # Container for dynamic simulator rows
        self.sim_container = QWidget(self.inst_group)
        self.sim_container_layout = QVBoxLayout(self.sim_container)
        self.sim_container_layout.setContentsMargins(0, 0, 0, 0)
        self.sim_container_layout.setSpacing(8)
        self.inst_layout.addWidget(self.sim_container)

        # Global Action Buttons
        btn_row = QHBoxLayout()
        self.btn_install_all = QPushButton("📥 Deploy DLL to All Simulators", self.inst_group)
        self.btn_install_all.setStyleSheet("font-weight: bold;")
        self.btn_install_all.clicked.connect(self._on_install_all_clicked)
        btn_row.addWidget(self.btn_install_all)

        self.btn_rescan = QPushButton("🔍 Rescan Steam Libraries", self.inst_group)
        self.btn_rescan.clicked.connect(self.game_plugin_mgr.refresh_installation_state)
        btn_row.addWidget(self.btn_rescan)
        btn_row.addStretch()
        self.inst_layout.addLayout(btn_row)

        layout.addWidget(self.inst_group)

        # =====================================================================
        # 2. Aggregated Plugin Desiderata Table
        # =====================================================================
        desiderata_group = QGroupBox("📋 Active SimPulse Plugins Desiderata (Required Channels & Hz)", content)
        desiderata_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        desiderata_layout = QVBoxLayout(desiderata_group)
        desiderata_layout.setContentsMargins(12, 10, 12, 10)
        desiderata_layout.setSpacing(8)

        # Compact header row: description on left, apply button on right
        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        desiderata_desc = QLabel(
            "Each SimPulse plugin declares the telemetry channels it requires and its preferred rate (Hz). "
            "SimPulse Core synthesizes these requirements to configure optimal game rates.",
            desiderata_group
        )
        desiderata_desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        desiderata_desc.setWordWrap(True)
        top_row.addWidget(desiderata_desc, stretch=1)

        btn_apply_recom = QPushButton("⚡ Apply Recommended Rates", desiderata_group)
        btn_apply_recom.setStyleSheet("background-color: #0284c7; color: #ffffff; font-weight: bold; padding: 6px 12px;")
        btn_apply_recom.clicked.connect(self._apply_recommended_rates)
        top_row.addWidget(btn_apply_recom)
        desiderata_layout.addLayout(top_row)

        self.desiderata_table = QTableWidget(desiderata_group)
        self.desiderata_table.setColumnCount(4)
        self.desiderata_table.setHorizontalHeaderLabels([
            "Requesting Plugin", "Required Channel", "Preferred Rate (Hz)", "Reason"
        ])
        self.desiderata_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.desiderata_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.desiderata_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.desiderata_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.desiderata_table.verticalHeader().setVisible(False)
        self.desiderata_table.setFixedHeight(80)
        desiderata_layout.addWidget(self.desiderata_table)

        layout.addWidget(desiderata_group)

        # =====================================================================
        # 3. Channel Rates Configuration (SimPulse Local Storage & Multi-Sim Propagation)
        # =====================================================================
        cfg_group = QGroupBox("⚙️ Telemetry Channel Rates Configuration (SimPulse Preferences)", content)
        cfg_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        c_layout = QVBoxLayout(cfg_group)

        grid = QGridLayout()
        grid.setSpacing(10)

        for idx, ch in enumerate(TelemetryChannel):
            lbl = QLabel(f"{ch.display_name} :", cfg_group)
            combo = QComboBox(cfg_group)
            for rate_opt in ch.available_rates:
                combo.addItem(rate_opt, rate_opt)

            # Set current rate from settings
            curr_rate = self.game_plugin_mgr.settings.rates.get(ch, "off")
            c_idx = combo.findData(curr_rate)
            if c_idx != -1:
                combo.setCurrentIndex(c_idx)

            combo.currentIndexChanged.connect(lambda _, channel=ch, cb=combo: self._on_rate_selected(channel, cb))
            self._rate_combos[ch] = combo

            row = idx // 2
            col = (idx % 2) * 2
            grid.addWidget(lbl, row, col)
            grid.addWidget(combo, row, col + 1)

        c_layout.addLayout(grid)

        self.chk_logging = QCheckBox("Enable C++ Plugin Disk Logging (isiMotor_RawUDP.log — For debugging only)", cfg_group)
        self.chk_logging.setChecked(self.game_plugin_mgr.settings.enable_logging)
        c_layout.addWidget(self.chk_logging)

        save_btn = QPushButton("💾 Save Preferences & Propagate to All Simulators", cfg_group)
        save_btn.setStyleSheet("background-color: #16a34a; color: #ffffff; font-weight: bold; padding: 10px; font-size: 13px;")
        save_btn.clicked.connect(self._save_to_game_json)
        c_layout.addWidget(save_btn)

        layout.addWidget(cfg_group)
        layout.addStretch(1)

        scroll.setWidget(content)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(scroll)

        self._refresh_ui()
        self._refresh_desiderata_table()

    def _refresh_ui(self) -> None:
        # Clear previous simulator rows
        while self.sim_container_layout.count():
            item = self.sim_container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        simulators = self.game_plugin_mgr.simulators
        if not simulators:
            lbl_empty = QLabel("⚠️ No supported simulators (Le Mans Ultimate / rFactor 2) detected in Steam libraries.", self.sim_container)
            lbl_empty.setStyleSheet("color: #ef4444; font-weight: bold; padding: 8px;")
            self.sim_container_layout.addWidget(lbl_empty)
            return

        for sim in simulators:
            row_frame = QWidget(self.sim_container)
            row_frame.setStyleSheet("background-color: #1e293b; border-radius: 6px; padding: 6px;")
            r_layout = QHBoxLayout(row_frame)
            r_layout.setContentsMargins(8, 6, 8, 6)

            icon = "🟢" if sim.plugin_installed else "🔴"
            status_style = "color: #22c55e;" if sim.plugin_installed else "color: #ef4444;"
            
            info_layout = QVBoxLayout()
            lbl_title = QLabel(f"{icon} <b>{sim.name}</b> — <span style='{status_style}'>{sim.status_message}</span>", row_frame)
            lbl_path = QLabel(f"<code>{sim.game_dir}</code>", row_frame)
            lbl_path.setStyleSheet("color: #94a3b8; font-size: 11px;")
            info_layout.addWidget(lbl_title)
            info_layout.addWidget(lbl_path)
            r_layout.addLayout(info_layout, stretch=1)

            btn_inst_sim = QPushButton("🔄 Update DLL" if sim.plugin_installed else "📥 Install DLL", row_frame)
            btn_inst_sim.setStyleSheet("padding: 4px 10px;")
            btn_inst_sim.clicked.connect(lambda _, s=sim: self._on_install_single_clicked(s))
            r_layout.addWidget(btn_inst_sim)

            self.sim_container_layout.addWidget(row_frame)

    def _refresh_desiderata_table(self) -> None:
        reqs_by_plugin = self.plugin_mgr.get_all_channel_requirements()
        total_rows = sum(len(req_list) for req_list in reqs_by_plugin.values())
        self.desiderata_table.setRowCount(total_rows)

        # Adapt table height to row count dynamically (so empty/few rows don't take excess space)
        header_h = self.desiderata_table.horizontalHeader().height() or 26
        target_h = max(58, min(140, header_h + (total_rows * 26) + 4))
        self.desiderata_table.setFixedHeight(target_h)

        row = 0
        for pid, req_list in reqs_by_plugin.items():
            plugin = self.plugin_mgr.plugins.get(pid)
            p_name = plugin.metadata.name if plugin else pid
            for req in req_list:
                # Plugin Name
                self.desiderata_table.setItem(row, 0, QTableWidgetItem(f"{p_name}"))
                # Channel Name
                self.desiderata_table.setItem(row, 1, QTableWidgetItem(req.channel.display_name))
                # Hz
                hz_item = QTableWidgetItem(f"{req.preferred_hz} Hz" if req.preferred_hz > 0 else "N/A")
                hz_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.desiderata_table.setItem(row, 2, hz_item)
                # Reason
                self.desiderata_table.setItem(row, 3, QTableWidgetItem(req.reason or "Telemetry channel consumption"))
                row += 1

    def _on_install_single_clicked(self, sim) -> None:
        success, msg = self.game_plugin_mgr.install_plugin_for_simulator(sim)
        if success:
            QMessageBox.information(self, f"Installation: {sim.name}", msg)
        else:
            QMessageBox.critical(self, f"Installation Error: {sim.name}", msg)

    def _on_install_all_clicked(self) -> None:
        success, msg = self.game_plugin_mgr.install_plugin_dll()
        if success:
            QMessageBox.information(self, "Installation Successful", msg)
        else:
            QMessageBox.critical(self, "Installation Error", msg)

    def _on_rate_selected(self, channel: TelemetryChannel, combo: QComboBox) -> None:
        rate = combo.currentData()
        self.game_plugin_mgr.settings.rates[channel] = rate

    def _apply_recommended_rates(self) -> None:
        reqs = self.plugin_mgr.get_all_channel_requirements()
        recommended = self.game_plugin_mgr.compute_recommended_rates(reqs)

        for ch, rec_rate in recommended.items():
            combo = self._rate_combos.get(ch)
            if combo:
                idx = combo.findData(rec_rate)
                if idx != -1:
                    combo.setCurrentIndex(idx)
            self.game_plugin_mgr.settings.rates[ch] = rec_rate

        QMessageBox.information(
            self,
            "Recommended Rates Applied",
            "Channel rates have been adjusted based on active plugin desiderata!\n"
            "Click 'Save Preferences & Propagate' to write to local storage and games."
        )

    def _save_to_game_json(self) -> None:
        self.game_plugin_mgr.settings.enable_logging = self.chk_logging.isChecked()
        for ch, combo in self._rate_combos.items():
            val = combo.currentData() or combo.currentText()
            self.game_plugin_mgr.settings.rates[ch] = val

        success = self.game_plugin_mgr.apply_rates_to_game()
        count = len(self.game_plugin_mgr.simulators)
        if success:
            QMessageBox.information(
                self,
                "Preferences Saved & Propagated",
                f"Preferences saved locally in SimPulse (config.json) and "
                f"successfully propagated to {count} detected simulator installation(s)!"
            )
        else:
            QMessageBox.warning(
                self,
                "Save Notice",
                "Preferences saved locally, but failed to write to one or more simulator JSON files."
            )
