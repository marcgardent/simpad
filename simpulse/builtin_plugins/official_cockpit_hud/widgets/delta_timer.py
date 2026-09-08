"""
Delta Timer Widget — Display expected lap delta time positioned below gear in compact canvas.
"""

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QPen
from simpulse_sdk import TimeTarget, VehicleSensors, format_lap_time
from .base_widget import BaseQtHudWidget, CockpitWidgetContext, format_signed_delta
from .display_cache import HudTimeWindowAverage
from .hud_smoothing_logger import record_passthrough, record_smoothing


def _live_delta_text(sensors: VehicleSensors) -> str:
    """Same gating as VehicleSensors.delta_time_str, EXCEPT it does not go
    blank just because the current lap is invalidated for record-keeping
    (lap_flag != 2, e.g. a track-limits cut) — requested explicitly, more
    than once: the driver already has a separate visual and audio indicator
    for an invalid lap elsewhere, so hiding the live number too is a
    redundant, unwanted second one. Still hidden with no reference at all,
    during an actual pit in/out lap, or when telemetry isn't live — none of
    those have a meaningful delta to show regardless of validity."""
    if not sensors.has_delta_reference or sensors.is_pit_lap or not sensors.in_realtime:
        return "--"
    return format_signed_delta(sensors.delta_time)


class QtDeltaTimerWidget(BaseQtHudWidget):
    """
    Delta Timer / Lap Time (Positioned below Gear).
    - On track: Displays either the live Delta (e.g. '-0.150') or the
      projected Expected finish time (MM:ss.mmm) — user-selectable via
      CockpitWidgetContext.delta_display_mode (OfficialCockpitHudConfig.
      delta_display_mode).
    - Line crossing: Displays Completed Lap Time (format MM:ss.mmm)

    The on-track value is a simple moving average over the last
    ``hud_smoothing_window_s`` seconds of GAME time (HudTimeWindowAverage —
    see display_cache.py), not the raw reading repainted every 100Hz frame:
    both Delta and Expected are projections, not a physical telemetry
    channel, so smoothing them for readability introduces no new error worth
    caring about (unrelated to why gauge `lerp` animation is a different,
    telemetry-only concern).

    Colour is SESSION-scoped only — no pink:
        * Purple (Session / paddock best)
        * Green  (Personal / my-session best)
        * Yellow (No improvement / slower)
        * Grey   (Invalid lap)
    Beating my all-time best ("ever") is never a colour: a " PR" marker is
    appended directly into the value text instead — same convention as the
    sector boxes below and simpulse.builtin_plugins.expected_timing. It is
    baked into the string (not a separately-positioned overlay) because a
    floating tag above the value collided with the Gear digits widget drawn
    in that same screen region.
    """

    def __init__(self, font_family: str = "Anta"):
        self.font_family = font_family
        self._value_avg = HudTimeWindowAverage()
        self._was_freeze = False

    def paint(
        self,
        painter: QPainter,
        canvas_w: float,
        canvas_h: float,
        context: CockpitWidgetContext,
    ) -> None:
        sensors = context.sensors
        is_freeze = sensors.is_lap_freeze_active
        lap_flag = sensors.lap_flag
        lap_time_str = sensors.last_lap_time_str

        if not is_freeze and self._was_freeze:
            # Freeze window just ended (new lap started): drop the averaging
            # window so the new lap's first live samples aren't averaged
            # together with the previous lap's final readings.
            self._value_avg.reset()
        self._was_freeze = is_freeze

        is_pr = False

        if is_freeze:
            # Line crossing mode: Completed Lap Time (MM:ss.mmm). target here
            # is DeltaEngine's FROZEN resolution of the just-completed lap
            # (against WallOfFameTimes as it stood BEFORE this lap) — never
            # the live projection, which would self-compare during this same
            # window. See DeltaEngine._handle_lap_transition.
            disp_str = lap_time_str if lap_time_str not in ("", "--") else "--:--.---"
            target = sensors.time_status.lap.target
            is_pr = sensors.time_status.lap.is_personal_record_target

            if lap_flag == 0 or target == TimeTarget.NONE:
                # Invalid lap / no reference -> Grey
                text_color = QColor(156, 163, 175, 255)
            elif target == TimeTarget.PADDOCK:
                # Session / paddock best -> Purple
                text_color = QColor(168, 85, 247, 255)
            elif target == TimeTarget.SESSION:
                # Personal improvement -> Green
                text_color = QColor(34, 197, 94, 255)
            elif target == TimeTarget.BEHIND:
                # No improvement / slower -> Yellow
                text_color = QColor(234, 179, 8, 255)
            else:
                text_color = QColor(255, 255, 255, 255)
        else:
            # On-track mode: user-selectable Live Delta or Expected finish
            # time (context.delta_display_mode) — colour follows the
            # EXPECTED-lap decision (projection vs paddock/my-session)
            # regardless of which number is shown: it answers "am I on a
            # good pace", independent of the delta-seconds vs projected-time
            # framing. Session-scoped only: beating my all-time-best ("ever")
            # is never a colour here, it's the
            # time_status.lap.is_personal_record_target flag below (-> "PR" tag).
            if context.delta_display_mode == "expected":
                raw_value, raw_text = sensors.estimated_lap_time, sensors.estimated_lap_time_str
            else:
                raw_value, raw_text = sensors.delta_time, _live_delta_text(sensors)
            self._value_avg.window_s = context.hud_smoothing_window_s
            averaged = self._value_avg.sample(raw_value, raw_text, context.game_time_s)
            if averaged is None:
                disp_str = raw_text
                record_passthrough("delta_timer", raw_text, context.hud_smoothing_window_s, context.game_time_s)
            else:
                if context.delta_display_mode == "expected":
                    disp_str = format_lap_time(averaged)
                else:
                    disp_str = format_signed_delta(averaged)
                record_smoothing(
                    "delta_timer", raw_value, raw_text, averaged, disp_str,
                    context.hud_smoothing_window_s, context.game_time_s,
                )
            expected_tok = sensors.expected_status.strip()
            is_pr = sensors.time_status.lap.is_personal_record_target

            if lap_flag == 0 or expected_tok == "invalid":
                # Invalid lap -> Grey
                text_color = QColor(156, 163, 175, 255)
            elif expected_tok == "purple":
                # PROJ < paddock best (other cars)
                text_color = QColor(168, 85, 247, 255)
            elif expected_tok == "green":
                # PROJ < my session best
                text_color = QColor(34, 197, 94, 255)
            elif expected_tok == "yellow":
                # PROJ slower than my session
                text_color = QColor(234, 179, 8, 255)
            else:
                # No usable reference yet (white) -> neutral, never red/green by
                # sign. Purple/green/yellow/grey is the ONE colour scale for
                # every delta display (lap or sector) — no other tier exists.
                text_color = QColor(255, 255, 255, 255)

        if is_pr:
            # All-time-best beaten: baked into the value text (see class
            # docstring) rather than a separate tag floating above it — that
            # used to overlap the Gear digits widget drawn in this region.
            disp_str = f"{disp_str} PR"

        scale_x = canvas_w / 800.0
        scale_y = canvas_h / 600.0

        font_size = max(14, int(round(28.0 * scale_y)))
        y_pos = 166.0 * scale_y

        font = QFont(self.font_family)
        font.setPixelSize(font_size)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(text_color))
        painter.drawText(
            QRectF(0, y_pos, canvas_w, font_size + 10 * scale_y),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            disp_str,
        )
