"""
SimPad Qt6 HUD Slot Compositor.
Uses strongly-typed HudLayoutSpec dataclasses for overlay layout geometry.
"""

from PySide6.QtCore import QRectF, QSize
from simpad_qt.plugins.contracts import HudSlot, HudLayoutSpec


class HudSlotCompositor:
    """
    Calculates target bounding boxes on screen for any given HudSlot and widget desired size.
    Returns strongly-typed HudLayoutSpec.
    """

    @staticmethod
    def calculate_slot_layout(
        slot: HudSlot,
        screen_w: float,
        screen_h: float,
        desired_size: QSize,
        margin: float = 24.0,
        z_index: int = 0,
    ) -> HudLayoutSpec:
        w = float(desired_size.width())
        h = float(desired_size.height())

        if slot == HudSlot.TOP_LEFT:
            x = margin
            y = margin
        elif slot == HudSlot.TOP_CENTER:
            x = (screen_w - w) / 2.0
            y = margin
        elif slot == HudSlot.TOP_RIGHT:
            x = screen_w - w - margin
            y = margin
        elif slot == HudSlot.CENTER:
            x = (screen_w - w) / 2.0
            y = (screen_h - h) / 2.0
        elif slot == HudSlot.COCKPIT_CENTER:
            x = (screen_w - w) / 2.0
            y = screen_h * 0.58
        elif slot == HudSlot.BOTTOM_LEFT:
            x = margin
            y = screen_h - h - margin
        elif slot == HudSlot.BOTTOM_CENTER:
            x = (screen_w - w) / 2.0
            y = screen_h - h - margin
        elif slot == HudSlot.BOTTOM_RIGHT:
            x = screen_w - w - margin
            y = screen_h - h - margin
        else:  # CUSTOM / Default
            x = (screen_w - w) / 2.0
            y = (screen_h - h) / 2.0

        rect = QRectF(x, y, w, h)
        return HudLayoutSpec(
            slot=slot,
            target_size=desired_size,
            allocated_rect=rect,
            z_index=z_index
        )
