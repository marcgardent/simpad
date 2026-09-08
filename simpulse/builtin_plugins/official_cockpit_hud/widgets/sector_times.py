"""
Sector Times Widget — 3-sector time boxes (S1, S2, S3) positioned below Delta timer in compact canvas.
"""

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QBrush
from simpulse_sdk import TimeTarget, format_sector_time
from .base_widget import BaseQtHudWidget, CockpitWidgetContext, format_signed_delta
from .display_cache import HudTimeWindowAverage
from .hud_smoothing_logger import record_passthrough, record_smoothing


# IHM-only presentation: the model may deliver the same frozen split under either
# '38.437' (parser seconds form) or '00:38.437' (delta engine). Both mean the same
# time. The model is not forced to a format; the widget canonicalises the drawn
# string itself so a frozen box never changes width for the same value.
_EMPTY_TIME_VALUES = ("", "--", "--:--.---")


def _present_split_time(value: str) -> str:
    """Paint helper: render a frozen sector split time in MM:ss.mmm form."""
    raw = (value or "").strip()
    if raw in _EMPTY_TIME_VALUES:
        return "--" if raw in ("", "--") else raw
    # Already in an M:ss.mmm or MM:ss.mmm spelling (minutes present) -> unchanged,
    # this spelling is stable beween both authors.
    if ":" in raw:
        try:
            head, _, tail = raw.partition(":")
            float(tail)
            int(head)
            return raw
        except ValueError:
            pass
    # Pure seconds "ss.mmm" (LMUParser compact form) -> present as MM:ss.mmm.
    try:
        total = float(raw)
    except ValueError:
        return raw  # unknown literal: pass through untouched (no width guarantee)
    if total <= 0.0:
        return "--"
    mins = int(total // 60)
    rest = total % 60.0
    if mins > 0:
        return f"{mins}:{rest:06.3f}"
    return f"00:{rest:06.3f}"


class QtSectorTimesWidget(BaseQtHudWidget):
    """
    Lap Sectors S1, S2, S3 (Positioned below Delta and Gear).

    Colour is aligned with the Delta Timer widget above it — SESSION-scoped
    only, sourced from sensors.time_status.sectorN.target (never the sign of
    the live delta, never pink):
        * Purple (TimeTarget.PADDOCK — beats paddock / other cars this session)
        * Green  (TimeTarget.SESSION — beats my session best for this sector)
        * Yellow (TimeTarget.BEHIND — valid, slower than my session)
        * Grey   (TimeTarget.NONE — no reference; invalid has its own
                  indicator elsewhere, never hidden behind `target`)
    Beating my all-time-best split ("ever") is a " PR" marker appended into
    the box's own time text, not a colour — see
    sensors.time_status.sectorN.is_personal_record_target. It is baked into
    the string rather than drawn as a separate tag above the box because
    that floating tag collided with the Gear digits widget drawn in the same
    screen region.

    Each box's live (in-progress) text shows either the live Delta or the
    projected Expected split time — same user-selectable
    CockpitWidgetContext.delta_display_mode as the Delta Timer above, applied
    per-box here too — as a simple moving average over the last
    ``hud_smoothing_window_s`` seconds of GAME time (HudTimeWindowAverage —
    see display_cache.py and QtDeltaTimerWidget's docstring): it's a
    projection either way, not raw telemetry, so smoothing it for
    readability is fine. The frozen split text (once a sector is done) is
    left unaveraged — it only changes once per lap crossing, nothing to
    smooth, and averaging it in would just delay showing the fresh result.

    Per-box visibility follows TIME_STATUS_SPEC.md's rule to the letter (a
    sector's box is one of exactly three states, never a fourth "leftover
    previous lap" one):
      * currently being driven          -> live delta (averaged, see above).
      * already completed THIS lap      -> that split's time, frozen.
      * not reached yet THIS lap        -> empty box, no time, no colour —
        UNLESS the finish-line freeze window is active (is_lap_freeze_active,
        DeltaEngine.freeze_duration), in which case every box shows the
        just-completed lap's actual split time instead (freeze takes
        priority over "is_current", since crossing the line immediately
        makes the new lap's S1 the current sector).
    A box never carries a PREVIOUS lap's split forward outside that freeze
    window — see DeltaEngine._handle_lap_transition (freeze) vs
    SectorEngine.reset_lap_capture (new-lap reset).
    """

    def __init__(self, font_family: str = "Anta"):
        self.font_family = font_family
        self._last_rendered_sector: int = -1
        self._delta_avgs = [HudTimeWindowAverage(), HudTimeWindowAverage(), HudTimeWindowAverage()]
        self._was_current = [False, False, False]

    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        context: CockpitWidgetContext,
    ) -> None:
        sensors = context.sensors
        sectors = sensors.sectors_list

        _cap_text: list = []   # exact strings painted, per box 0..2 (diagnostic)
        _cap_mode: list = []   # 'live' | 'frozen' per box (diagnostic)
        _cap_bg: list = []     # (r,g,b) background painted per box (diagnostic)

        curr_sec = sensors.current_sector
        if curr_sec != self._last_rendered_sector:
            try:
                from simpulse.core.telemetry.overlay_anomaly_logger import OverlayAnomalyLogger
                OverlayAnomalyLogger.get_instance().check_sector_update(
                    current_sector=curr_sec,
                    raw_sector=curr_sec,
                    source="QtSectorTimesWidget",
                    s1_time=sectors[0].time,
                    s2_time=sectors[1].time,
                    s3_time=sectors[2].time,
                    s1_delta=sectors[0].delta,
                    s2_delta=sectors[1].delta,
                    s3_delta=sectors[2].delta,
                    lap_dist=sensors.lap_dist if hasattr(sensors, "lap_dist") else 0.0,
                    speed_kmh=sensors.vehicle_speed * 3.6,
                )
            except Exception:
                pass
            self._last_rendered_sector = curr_sec

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0
        center_x = canvas_w / 2.0

        sector_w = 90.0 * scale_x
        sector_h = 24.0 * scale_y
        sector_spacing = 8.0 * scale_x

        total_width = (sector_w * 3.0) + (sector_spacing * 2.0)
        start_x = center_x - (total_width / 2.0)
        sector_y = 198.0 * scale_y

        font_size = max(9, int(round(13.0 * scale_y)))
        font = QFont(self.font_family)
        font.setPixelSize(font_size)
        font.setBold(True)
        painter.setFont(font)

        time_status_sectors = sensors.time_status.sectors
        is_freeze = sensors.is_lap_freeze_active

        for i in range(min(3, len(sectors))):
            s_x = start_x + (i * (sector_w + sector_spacing))
            sec = sectors[i]
            s_time = sec.time
            is_current = sec.is_current
            delta_str = sec.delta_str
            box_num = i + 1
            label = f"sector{box_num}"

            # Colour is aligned with the Delta Timer above: SESSION-scoped
            # time_status.sectorN.target only (purple/green/yellow/grey), the
            # same field whether the sector is still live or already frozen.
            target = time_status_sectors[i].target
            is_pr = time_status_sectors[i].is_personal_record_target

            # Exactly one of three states per box — see class docstring.
            # "Not reached yet this lap" never carries the previous lap's
            # split forward; only the finish-line freeze window (checked
            # first, ahead of is_current — see docstring) does.
            if is_freeze:
                mode = "frozen"
            elif is_current and delta_str != "--":
                mode = "live"
            elif box_num < curr_sec:
                mode = "frozen"
            else:
                mode = "empty"

            if mode == "live":
                # Same user-selectable Delta vs Expected choice as the Delta
                # Timer above (CockpitWidgetContext.delta_display_mode) —
                # applies here too, not just to the lap badge.
                if context.delta_display_mode == "expected":
                    raw_value = time_status_sectors[i].expected_time
                    raw_text = time_status_sectors[i].expected_time_str
                else:
                    raw_value = sec.delta
                    raw_text = delta_str
                self._delta_avgs[i].window_s = context.hud_smoothing_window_s
                averaged = self._delta_avgs[i].sample(raw_value, raw_text, context.game_time_s)
                if averaged is None:
                    disp_text = raw_text
                    record_passthrough(label, raw_text, context.hud_smoothing_window_s, context.game_time_s)
                else:
                    if context.delta_display_mode == "expected":
                        disp_text = format_sector_time(averaged)
                    else:
                        disp_text = format_signed_delta(averaged)
                    record_smoothing(
                        label, raw_value, raw_text, averaged, disp_text,
                        context.hud_smoothing_window_s, context.game_time_s,
                    )
            else:
                if self._was_current[i]:
                    # Just stopped being the current sector: start the next
                    # lap's averaging window fresh, don't carry this box's
                    # last live samples forward.
                    self._delta_avgs[i].reset()
                disp_text = "--" if mode == "empty" else _present_split_time(s_time)
            self._was_current[i] = (mode == "live")

            if mode == "empty":
                # Empty box: no time, no colour, no PR tag (TIME_STATUS_SPEC.md
                # — a sector not yet reached this lap is not "white/none", it's
                # simply not drawn as a fact yet).
                target = TimeTarget.NONE
                is_pr = False

            if is_pr:
                # All-time-best beaten for this sector: baked into the box's
                # own text (see class docstring), not a separate floating tag.
                disp_text = f"{disp_text} PR"

            if target == TimeTarget.PADDOCK:
                bg_color = QColor(147, 51, 234, 255)
                border_color = QColor(168, 85, 247, 255)
            elif target == TimeTarget.SESSION:
                bg_color = QColor(22, 163, 74, 255)
                border_color = QColor(34, 197, 94, 255)
            elif target == TimeTarget.BEHIND:
                # Egg-yolk yellow fill — same colour as the "no improvement /
                # slower" text on the Delta Timer above, not a muddy brown.
                bg_color = QColor(234, 179, 8, 255)
                border_color = QColor(234, 179, 8, 255)
            else:  # TimeTarget.NONE — no reference (invalid has its own indicator elsewhere)
                bg_color = QColor(15, 23, 42, 255)
                border_color = QColor(51, 65, 85, 255)

            # Marked white border for current active sector
            _cap_text.append(disp_text)
            _cap_mode.append(mode)
            _cap_bg.append((int(bg_color.red()), int(bg_color.green()), int(bg_color.blue())))
            if is_current and mode == "live":
                border_color = QColor(255, 255, 255, 255)
                pen_width = 2
            else:
                pen_width = 1

            # Box background
            rect = QRectF(s_x, sector_y, sector_w, sector_h)
            painter.setBrush(QBrush(bg_color))
            painter.setPen(QPen(border_color, pen_width))
            painter.drawRect(rect)

            # Time text — dark ink on the bright egg-yolk BEHIND fill (kept
            # white on every other, darker background) for readable contrast.
            text_color = QColor(41, 27, 2, 255) if target == TimeTarget.BEHIND else QColor(255, 255, 255, 255)
            painter.setPen(QPen(text_color))
            if is_pr:
                # The appended " PR" makes the string longer than the
                # normal split/delta text — shrink the font a touch so it
                # still fits the box instead of overflowing it.
                pr_font = QFont(self.font_family)
                pr_font.setPixelSize(max(8, font_size - 2))
                pr_font.setBold(True)
                painter.setFont(pr_font)
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, disp_text)
                painter.setFont(font)
            else:
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, disp_text)

        # --- diagnostic paint logger (opt-in, no behaviour change) ---
        try:
            if _cap_text:
                from simpulse.builtin_plugins.official_cockpit_hud.widgets.sector_paint_recorder import record
                record(int(sensors.current_sector), tuple(_cap_text), tuple(_cap_mode), tuple(_cap_bg))
        except Exception:
            pass
