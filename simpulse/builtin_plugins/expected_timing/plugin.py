"""
Expected Timing Inspector — overlay bound EXCLUSIVELY to the `sensors` argument.

The overlay compositor repaints each IHudWidgetProvider calling
``paint_hud(painter, width, height, sensors)`` — the only inbound data a HUD
widget ever receives. This plugin therefore reads every displayed value from
that `sensors` (VehicleSensors merged by the telemetry bus from the delta/time
handler):

  * EXPECTED   → sensors.estimated_lap_time_str / sensors.expected_status
  * Δ lap      → sensors.delta_time / delta display string
  * S1/S2/S3   → sensors.time_status.sectorN.expected_time_str / .target
                 (projected sector time, NOT the raw completed-split time —
                 see simpulse_sdk.models.timing.TimeStatus)
  * REFERENCES → three unambiguously-labelled clocks, each a genuinely
                 different baseline, all read from sensors.time_status.wall_of_fame
                 (the raw, un-projected reference facts — see WallOfFameTimes):
                   "MY SESSION BEST"   wall_of_fame.my_best_session.total_str
                                       (my own best lap THIS session)
                   "PADDOCK BEST"      wall_of_fame.paddock_session_best.total_str
                                       (best lap of any OTHER car, this session)
                   "MY ALL-TIME BEST"  sensors.reference_profile.lap_time
                                       (my best ever, any session — a static
                                       value read from a JSON file, pushed only
                                       when it actually changes; NOT a
                                       per-packet field, see _all_time_best_str
                                       below)

Colour convention — NO PINK: every colour token this overlay paints
(`purple`/`green`/`yellow`/`white`/`invalid`) is scoped to the CURRENT SESSION
only (best-of-session vs. my-session-best). Beating my all-time best ("ever")
is never expressed as a colour; instead the engine flags it via
``time_status.lap.is_personal_record_target`` / ``time_status.sectorN.
is_personal_record_target`` and this overlay prints a literal "PR" tag next
to the time/delta it belongs to.

Nothing cached on the plugin instance is used for painting, so the overlay can
never show stale or empty content. When the bus merged no fresh timing (no
active reference), fields keep their honest defaults (`--:--.---`, `white`),
which the card renders explicitly.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QSize, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QBrush
from PySide6.QtWidgets import QWidget

from simpulse_sdk import (
    SimPulsePlugin,
    PluginMetadata,
    PluginContext,
    ITabProvider,
    ITelemetrySubscriber,
    IHudWidgetProvider,
    HudSlot,
    VehicleSensors,
    TimeTarget,
    format_lap_time,
)

from simpulse.builtin_plugins.expected_timing.config import ExpectedTimingConfig

__all__ = ["ExpectedTimingPlugin", "ExpectedTimingConfig"]

# Session-scoped only — no pink here by design (see module docstring). A "PR"
# text tag stands in for the all-time-best tier instead of a colour.
_TOKEN_RGB = {
    "purple": (168, 85, 247),
    "green": (34, 197, 94),
    "yellow": (234, 179, 8),
    "white": (235, 235, 235),
    "invalid": (156, 163, 175),
    "default": (148, 163, 184),
}

_PR_COLOR = QColor(255, 255, 255)  # PR is a text tag, not a colour tier — plain white

# TimeTarget -> render token (TIME_STATUS_SPEC.md "Table de rendu" — a VIEW
# concern, not the domain's; the sector boxes below are the only place in
# this plugin that reads time_status.sectorN.target instead of the legacy
# expected_sectorN_status).
_TARGET_TOKEN = {
    TimeTarget.NONE: "white",
    TimeTarget.BEHIND: "yellow",
    TimeTarget.SESSION: "green",
    TimeTarget.PADDOCK: "purple",
}


def _all_time_best_str(sensors: VehicleSensors) -> str:
    """"My all-time best" — read straight from the pushed-on-change reference
    profile (sensors.reference_profile), never from a per-packet field. See
    the module docstring and VehicleSensors.reference_profile's own docstring."""
    prof = sensors.reference_profile
    if prof is None or prof.lap_time <= 0.0:
        return "--:--.---"
    return format_lap_time(prof.lap_time)


def _col(token: str) -> QColor:
    r, g, b = _TOKEN_RGB.get((token or "default"), (235, 235, 235))
    return QColor(r, g, b)


class ExpectedTimingPlugin(SimPulsePlugin, ITabProvider, ITelemetrySubscriber, IHudWidgetProvider):
    """Expected lap time + S1/S2/S3 readout overlay (binds ONLY on sensors)."""

    def __init__(self):
        super().__init__(PluginMetadata(
            id="simpulse.builtin.expected_timing",
            name="Expected Timing Inspector",
            version="2.0.0",
            author="SimPulse Team",
            description="Overlay bound to sensors: expected lap time (coloured) + S1/S2/S3 sector times.",
            icon="⏱️",
            tags=("timing", "expected", "sector", "overlay", "diagnostic"),
        ))
        self.config = ExpectedTimingConfig()
        self._active_tab: Optional[QWidget] = None

    # ------------------------------------------------------------------ api
    def get_channel_requirements(self) -> list:
        from simpulse.core.telemetry_channels import TelemetryChannel, ChannelRequirement
        return [
            ChannelRequirement(channel=TelemetryChannel.TELEMETRY, preferred_hz=60,
                               required=False,
                               reason="sensors carry merged expected/sector timing for the overlay"),
            ChannelRequirement(channel=TelemetryChannel.COMPACT_SCORING, preferred_hz=10,
                               required=True,
                               reason="timing source feeding VehicleSensors merges"),
        ]

    def on_load(self, context: PluginContext) -> None:
        super().on_load(context)
        self.config = context.get_typed_config(ExpectedTimingConfig)
        try:
            self.config.slot = HudSlot(self.config.slot)
        except (ValueError, TypeError):
            self.config.slot = HudSlot.BOTTOM_CENTER

    def save_config(self) -> None:
        if self.context:
            self.context.save_typed_config(self.config)

    # ITelemetrySubscriber — refresh the studio tab with merged sensors (same
    # pattern as OfficialCockpitHudPlugin; tab object owns its widgets).
    def on_telemetry_frame(self, sensors: VehicleSensors) -> None:
        if self._active_tab is not None and self._active_tab.isVisible():
            updater = getattr(self._active_tab, "update_sensors", None)
            if updater is not None:
                updater(sensors)

    # ------------------------------- studio tab -----------------------------
    def get_tab_title(self) -> str:
        return "Timing Inspector"

    def get_tab_icon(self) -> str:
        return "⏱️"

    def create_tab_widget(self, parent: Optional[QWidget] = None) -> QWidget:
        from simpulse.builtin_plugins.expected_timing.tab_widget import ExpectedTimingTabWidget
        tab = ExpectedTimingTabWidget(self, parent)
        self._active_tab = tab
        return tab

    # ------------------------------- overlay -------------------------------
    @property
    def preferred_slot(self) -> HudSlot:
        return self.config.slot

    def get_hud_size(self) -> QSize:
        h = 178
        if not self.config.show_sectors:
            h -= 40
        if self.config.show_references:
            h += 30
        return QSize(max(330, int(470 * self.config.scale)),
                     max(120, int(h * self.config.scale)))

    def is_hud_visible(self) -> bool:
        return bool(self.config.hud_enabled)

    def paint_hud(self, painter: QPainter, width: float, height: float, sensors: VehicleSensors) -> None:
        s = self.config.scale
        pad = 12 * s
        gap = 6 * s

        # ---- card ----
        painter.setPen(QPen(QColor(0, 210, 255, 110), 1.3))
        painter.setBrush(QBrush(QColor(12, 17, 24, 226)))
        painter.drawRoundedRect(QRectF(0, 0, width, height), 9 * s, 9 * s)

        def F(px: float, bold: bool = False) -> QFont:
            f = QFont("Segoe UI", int(max(7, px * s)))
            f.setBold(bold)
            return f

        top = 10 * s
        y = top

        # ---------- EXPECTED (large, session-scoped token colour) ----------
        # Read the real merged values as-is; the engine/bus decide semantics
        # (expected_status is already `invalid`/`white` when no active reference).
        est = sensors.estimated_lap_time_str
        tok = sensors.expected_status
        is_pr = bool(sensors.time_status.lap.is_personal_record_target)

        painter.setFont(F(9, True))
        painter.setPen(QColor(0, 210, 255))
        painter.drawText(QRectF(pad, y, width - 2 * pad, 12 * s),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "EXPECTED")
        if is_pr:
            painter.setFont(F(9, True))
            painter.setPen(_PR_COLOR)
            painter.drawText(QRectF(pad, y, width - 2 * pad, 12 * s),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "PR")

        # big time value right side
        box = QRectF(pad, y + 6 * s, width - 2 * pad, 30 * s)
        painter.setFont(F(24, True))
        painter.setPen(_col(tok))
        painter.drawText(box, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, est)

        # delta chip on left of the big value
        if sensors.has_delta_reference:
            d = sensors.delta_time
            d_txt = f"{d:+.3f} s" if abs(d) > 0.0005 else "±0.000 s"
            painter.setFont(F(10, True))
            painter.setPen(QColor(148, 163, 184))
            painter.drawText(QRectF(pad + 74 * s, y + 6 * s, width - 2 * pad - 74 * s - 130 * s, 12 * s),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, d_txt)
        y += 44 * s

        # thin divider
        painter.setPen(QPen(QColor(0, 210, 255, 60), 1))
        painter.drawLine(int(pad), int(y), int(width - pad), int(y))
        y += gap

        # ---------- S1 / S2 / S3 EXPECTED (three boxes, status-coloured borders) ----------
        # NOT the raw completed-split time: the *projected* sector time
        # (reference split + live splitN delta), same "no pink, PR tag" rule
        # as EXPECTED above.
        if self.config.show_sectors:
            ts = sensors.time_status
            cells = [
                ("S1", ts.sector1.expected_time_str, _TARGET_TOKEN[ts.sector1.target], ts.sector1.is_personal_record_target),
                ("S2", ts.sector2.expected_time_str, _TARGET_TOKEN[ts.sector2.target], ts.sector2.is_personal_record_target),
                ("S3", ts.sector3.expected_time_str, _TARGET_TOKEN[ts.sector3.target], ts.sector3.is_personal_record_target),
            ]
            cw = (width - 2 * pad - 2 * gap) / 3.0
            for i, (label, t_v, st_tok, sec_pr) in enumerate(cells):
                x0 = pad + i * (cw + gap)
                r = QRectF(x0, y, cw, 34 * s)
                painter.setPen(QPen(_col(st_tok), 1.6))
                painter.setBrush(QBrush(QColor(255, 255, 255, 20)))
                painter.drawRoundedRect(r, 4 * s, 4 * s)
                painter.setFont(F(8, True))
                painter.setPen(QColor(18, 24, 32))
                painter.drawText(QRectF(x0 + 4 * s, y + 2 * s, cw - 8 * s, 10 * s),
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
                if sec_pr:
                    painter.setFont(F(8, True))
                    painter.setPen(_PR_COLOR)
                    painter.drawText(QRectF(x0 + 4 * s, y + 2 * s, cw - 8 * s, 10 * s),
                                     Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "PR")
                painter.setFont(F(13, True))
                painter.setPen(QColor(245, 250, 255))
                painter.drawText(QRectF(x0 + 4 * s, y + 9 * s, cw - 8 * s, 20 * s),
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                 t_v if t_v not in ("", "--") else "--")
            y += 40 * s

        # ---------- reference times row ----------
        if self.config.show_references:
            painter.setPen(QPen(QColor(0, 210, 255, 60), 1))
            painter.drawLine(int(pad), int(y), int(width - pad), int(y))
            y += gap
            wof = sensors.time_status.wall_of_fame
            refs = [
                ("MY SESSION BEST", wof.my_best_session.total_str),
                ("PADDOCK BEST", wof.paddock_session_best.total_str),
                ("MY ALL-TIME BEST", _all_time_best_str(sensors)),
            ]
            rw = (width - 2 * pad - (len(refs) - 1) * gap) / len(refs)
            for i, (label, t_v) in enumerate(refs):
                x0 = pad + i * (rw + gap)
                painter.setFont(F(7, True))
                painter.setPen(QColor(120, 135, 155))
                painter.drawText(QRectF(x0, y, rw, 10 * s),
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
                painter.setFont(F(11, True))
                painter.setPen(QColor(210, 220, 230))
                painter.drawText(QRectF(x0, y + 9 * s, rw, 16 * s),
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, t_v)
            y += 26 * s

        # ---------- small state line ----------
        painter.setFont(F(7))
        painter.setPen(QColor(120, 135, 155))
        note = f"sector in-run {sensors.current_sector} | status: {tok}"
        if not sensors.has_delta_reference:
            note += " | no active reference (expected invalid/white until a timed lap)"
        painter.drawText(QRectF(pad, y, width - 2 * pad, 12 * s),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, note)
