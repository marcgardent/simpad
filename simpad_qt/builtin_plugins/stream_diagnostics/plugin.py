"""
SimPad Official Plugin — Telemetry Stream Diagnostics & Packet Analyzer.
Monitors all incoming UDP channels, measures real-time throughput (Kb/s), live packet rates (Hz),
and displays packet statistics in a rich Qt6 telemetry diagnostic console.
"""

from __future__ import annotations
import time
from typing import Optional, List, Dict
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox, QPushButton
)

from simpad_qt.plugins.contracts import (
    SimPadPlugin, PluginMetadata, PluginContext,
    ITabProvider, ITelemetrySubscriber, IPacketSubscriber
)
from simpad_qt.core.telemetry_channels import (
    TelemetryChannel, ChannelRequirement, TelemetryRawPacket
)
from src.telemetry.sensors import VehicleSensors


@dataclass
class ChannelStatRecord:
    """Internal per-channel statistical accumulator."""
    channel: TelemetryChannel
    packet_count: int = 0
    total_bytes: int = 0
    last_timestamp: float = 0.0
    hz_estimate: float = 0.0
    kbs_estimate: float = 0.0


class StreamDiagnosticsWidget(QWidget):
    """Interactive Qt6 tab displaying real-time packet frequencies and throughput."""

    def __init__(self, plugin: "TelemetryDiagnosticsPlugin", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.plugin = plugin
        self._is_paused = False
        self._init_ui()

        # UI Refresh timer at 15 Hz for smooth stats rendering
        self._timer = QTimer(self)
        self._timer.setInterval(250)  # 4 Hz refresh rate
        self._timer.timeout.connect(self._refresh_ui)
        self._timer.start()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # 1. Top Summary KPI Cards
        kpi_group = QGroupBox("📊 Global Bandwidth & Frequency Monitor", self)
        kpi_layout = QHBoxLayout(kpi_group)
        kpi_layout.setSpacing(20)

        # Card 1: Total Bandwidth
        self.lbl_kbs = QLabel("0.0 Kb/s", kpi_group)
        self.lbl_kbs.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: #00d2ff; "
            "background: #0f1115; border: 1px solid #1e293b; border-radius: 8px; padding: 10px 16px;"
        )
        self.lbl_kbs.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c1_box = QVBoxLayout()
        c1_box.addWidget(QLabel("TOTAL NETWORK BITRATE", kpi_group))
        c1_box.addWidget(self.lbl_kbs)
        kpi_layout.addLayout(c1_box)

        # Card 2: Total Hz Rate
        self.lbl_hz = QLabel("0.0 Hz", kpi_group)
        self.lbl_hz.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: #22c55e; "
            "background: #0f1115; border: 1px solid #1e293b; border-radius: 8px; padding: 10px 16px;"
        )
        self.lbl_hz.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c2_box = QVBoxLayout()
        c2_box.addWidget(QLabel("GLOBAL PACKET RATE", kpi_group))
        c2_box.addWidget(self.lbl_hz)
        kpi_layout.addLayout(c2_box)

        # Card 3: Total Packets
        self.lbl_pkts = QLabel("0", kpi_group)
        self.lbl_pkts.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: #f59e0b; "
            "background: #0f1115; border: 1px solid #1e293b; border-radius: 8px; padding: 10px 16px;"
        )
        self.lbl_pkts.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c3_box = QVBoxLayout()
        c3_box.addWidget(QLabel("TOTAL PACKETS RECEIVED", kpi_group))
        c3_box.addWidget(self.lbl_pkts)
        kpi_layout.addLayout(c3_box)

        # Controls
        ctrl_box = QVBoxLayout()
        self.btn_pause = QPushButton("⏸️ Freeze", kpi_group)
        self.btn_pause.clicked.connect(self._toggle_pause)
        self.btn_reset = QPushButton("🔄 Reset", kpi_group)
        self.btn_reset.clicked.connect(self.plugin.reset_counters)
        ctrl_box.addWidget(self.btn_pause)
        ctrl_box.addWidget(self.btn_reset)
        kpi_layout.addLayout(ctrl_box)

        layout.addWidget(kpi_group)

        # 2. Main Live Channels Table
        self.table = QTableWidget(self)
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Telemetry Channel", "Decoded Structure", "Measured Rate (Live)",
            "Bitrate (Kb/s)", "Packets Received", "Total Volume", "Last Packet Age", "Status"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        self._init_table_rows()

    def _init_table_rows(self) -> None:
        channels = list(TelemetryChannel)
        self.table.setRowCount(len(channels))
        for row, ch in enumerate(channels):
            # Name
            name_item = QTableWidgetItem(ch.display_name)
            name_item.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            self.table.setItem(row, 0, name_item)

            # Structure type
            struct_names = {
                TelemetryChannel.TELEMETRY: "TelemInfo (SimpTelem)",
                TelemetryChannel.COMPACT_SCORING: "CompactScoring (LiveTiming)",
                TelemetryChannel.FULL_SCORING: "FullScoringSession (Standings)",
                TelemetryChannel.WEATHER: "WeatherControl (Weather)",
                TelemetryChannel.EXTENDED_STATE: "ExtendedState (Lights/States)",
                TelemetryChannel.FORCE_FEEDBACK: "ForceFeedback (Torque)",
                TelemetryChannel.GRAPHICS: "Graphics (Camera)",
                TelemetryChannel.TRACK_RULES: "TrackRules (Flags)",
                TelemetryChannel.PIT_MENU: "PitMenu (Pit Strategy)",
                TelemetryChannel.SYSTEM_EVENTS: "SystemEvents (Transitions)",
            }
            struct_item = QTableWidgetItem(struct_names.get(ch, "Raw Datagram"))
            self.table.setItem(row, 1, struct_item)

            # Default placeholders
            for col in range(2, 8):
                item = QTableWidgetItem("--")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, col, item)

    def _toggle_pause(self) -> None:
        self._is_paused = not self._is_paused
        self.btn_pause.setText("▶️ Resume" if self._is_paused else "⏸️ Freeze")

    def _refresh_ui(self) -> None:
        if not self.isVisible() or self._is_paused:
            return

        now = time.time()
        stats = self.plugin.get_channel_statistics()

        total_hz = sum(s.hz_estimate for s in stats.values())
        total_kbs = sum(s.kbs_estimate for s in stats.values())
        total_pkts = sum(s.packet_count for s in stats.values())

        self.lbl_kbs.setText(f"{total_kbs:.1f} Kb/s")
        self.lbl_hz.setText(f"{total_hz:.1f} Hz")
        self.lbl_pkts.setText(f"{total_pkts:,}")

        channels = list(TelemetryChannel)
        for row, ch in enumerate(channels):
            s = stats.get(ch)
            if not s:
                continue

            # Measured Hz
            hz_item = self.table.item(row, 2)
            hz_item.setText(f"{s.hz_estimate:.1f} Hz")
            if s.hz_estimate > 0:
                hz_item.setForeground(QColor(34, 197, 94))
                hz_item.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            else:
                hz_item.setForeground(QColor(148, 163, 184))

            # Kb/s
            kbs_item = self.table.item(row, 3)
            kbs_item.setText(f"{s.kbs_estimate:.2f} Kb/s")
            if s.kbs_estimate > 0:
                kbs_item.setForeground(QColor(0, 210, 255))
            else:
                kbs_item.setForeground(QColor(148, 163, 184))

            # Packet Count
            pkt_item = self.table.item(row, 4)
            pkt_item.setText(f"{s.packet_count:,}")

            # Total Volume
            vol_item = self.table.item(row, 5)
            if s.total_bytes > 1024 * 1024:
                vol_item.setText(f"{s.total_bytes / (1024 * 1024):.2f} MB")
            else:
                vol_item.setText(f"{s.total_bytes / 1024:.1f} KB")

            # Last Packet Age
            last_item = self.table.item(row, 6)
            if s.last_timestamp > 0:
                age_ms = (now - s.last_timestamp) * 1000.0
                if age_ms < 1000:
                    last_item.setText(f"{age_ms:.0f} ms")
                    last_item.setForeground(QColor(34, 197, 94))
                else:
                    last_item.setText(f"{age_ms / 1000.0:.1f} s")
                    last_item.setForeground(QColor(245, 158, 11))
            else:
                last_item.setText("None")
                last_item.setForeground(QColor(100, 116, 139))

            # Status badge
            stat_item = self.table.item(row, 7)
            if s.last_timestamp > 0 and (now - s.last_timestamp) < 2.5:
                stat_item.setText("🟢 ACTIVE")
                stat_item.setForeground(QColor(34, 197, 94))
            elif s.packet_count > 0:
                stat_item.setText("🟡 PAUSED")
                stat_item.setForeground(QColor(245, 158, 11))
            else:
                stat_item.setText("⚫ IDLE")
                stat_item.setForeground(QColor(100, 116, 139))


class TelemetryDiagnosticsPlugin(SimPadPlugin, ITabProvider, ITelemetrySubscriber, IPacketSubscriber):
    """
    Official SimPad Stream Diagnostics & Packet Analyzer plugin.
    Inspects all raw UDP packets, measures live frequencies and bandwidth consumption.
    """

    def __init__(self):
        super().__init__(PluginMetadata(
            id="simpad.official.stream_diagnostics",
            name="Stream Diagnostics & Packet Analyzer",
            version="1.0.0",
            author="SimPad Team (Official)",
            description="Real-time telemetry stream throughput (Kb/s), frequency (Hz) and packet statistics monitor.",
            icon="📡",
            tags=("diagnostics", "packets", "network", "bandwidth")
        ))
        self._stats: Dict[TelemetryChannel, ChannelStatRecord] = {
            ch: ChannelStatRecord(channel=ch) for ch in TelemetryChannel
        }
        self._sliding_timestamps: Dict[TelemetryChannel, List[float]] = {
            ch: [] for ch in TelemetryChannel
        }
        self._sliding_bytes: Dict[TelemetryChannel, List[tuple]] = {
            ch: [] for ch in TelemetryChannel
        }
        self._active_widget: Optional[StreamDiagnosticsWidget] = None

    def get_channel_requirements(self) -> List[ChannelRequirement]:
        """
        Declares requirements for major telemetry channels so the host configures the game plugin.
        """
        return [
            ChannelRequirement(
                channel=TelemetryChannel.TELEMETRY,
                preferred_hz=100,
                required=True,
                reason="High-frequency physics and latency calculation"
            ),
            ChannelRequirement(
                channel=TelemetryChannel.COMPACT_SCORING,
                preferred_hz=10,
                required=False,
                reason="Real-time lap timing and deltas"
            ),
            ChannelRequirement(
                channel=TelemetryChannel.FULL_SCORING,
                preferred_hz=5,
                required=False,
                reason="Session standings and grid positions"
            ),
            ChannelRequirement(
                channel=TelemetryChannel.WEATHER,
                preferred_hz=1,
                required=False,
                reason="Ambient and track weather parameters"
            ),
            ChannelRequirement(
                channel=TelemetryChannel.EXTENDED_STATE,
                preferred_hz=5,
                required=False,
                reason="Vehicle electronics and flag detection"
            ),
        ]

    def get_tab_title(self) -> str:
        return "Stream Diagnostics"

    def get_tab_icon(self) -> str:
        return "📡"

    def create_tab_widget(self, parent: Optional[QWidget] = None) -> QWidget:
        self._active_widget = StreamDiagnosticsWidget(self, parent)
        return self._active_widget

    def on_telemetry_frame(self, sensors: VehicleSensors) -> None:
        """Fallback subscriber for normalized frames."""
        pass

    def on_telemetry_packet(self, packet: TelemetryRawPacket) -> None:
        """Inspect each individual packet arriving from the UDP receiver."""
        now = packet.timestamp
        ch = packet.channel
        rec = self._stats[ch]
        rec.packet_count += 1
        rec.total_bytes += packet.raw_bytes_len
        rec.last_timestamp = now

        # Append to sliding window for exact Hz/Kbps
        self._sliding_timestamps[ch].append(now)
        self._sliding_bytes[ch].append((now, packet.raw_bytes_len))

        # Prune older than 2s
        cutoff = now - 2.0
        self._sliding_timestamps[ch] = [t for t in self._sliding_timestamps[ch] if t >= cutoff]
        self._sliding_bytes[ch] = [(t, b) for t, b in self._sliding_bytes[ch] if t >= cutoff]

        rec.hz_estimate = len(self._sliding_timestamps[ch]) / 2.0
        total_b = sum(b for _, b in self._sliding_bytes[ch])
        rec.kbs_estimate = (total_b * 8.0) / (2.0 * 1000.0)

    def get_channel_statistics(self) -> Dict[TelemetryChannel, ChannelStatRecord]:
        """Return a snapshot of per-channel statistics."""
        now = time.time()
        cutoff = now - 2.0
        for ch, rec in self._stats.items():
            self._sliding_timestamps[ch] = [t for t in self._sliding_timestamps[ch] if t >= cutoff]
            self._sliding_bytes[ch] = [(t, b) for t, b in self._sliding_bytes[ch] if t >= cutoff]
            rec.hz_estimate = len(self._sliding_timestamps[ch]) / 2.0
            total_b = sum(b for _, b in self._sliding_bytes[ch])
            rec.kbs_estimate = (total_b * 8.0) / (2.0 * 1000.0)
        return self._stats

    def reset_counters(self) -> None:
        """Reset all packet counters and accumulators."""
        for ch in TelemetryChannel:
            self._stats[ch] = ChannelStatRecord(channel=ch)
            self._sliding_timestamps[ch].clear()
            self._sliding_bytes[ch].clear()
