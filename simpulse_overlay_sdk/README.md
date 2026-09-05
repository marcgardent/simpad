# SimPulse Overlay SDK (`simpulse-overlay-sdk`)

Contracts for third-party HUD overlay widgets in the SimPulse ecosystem.

## What's in this SDK

- **`BaseHudWidget`**: Abstract base class for creating custom HUD widgets.
  - `preferred_slot`: Where to position on screen (`HudSlot.TOP_CENTER`, etc.)
  - `get_hud_size()`: Desired widget dimensions `(width, height)`
  - `paint_hud(painter, width, height, sensors)`: Rendering callback
  - `is_hud_visible()`: Visibility toggle
  - `on_overlay_show()` / `on_overlay_hide()`: Lifecycle hooks

## Re-exported for convenience

- `HudSlot` — Screen position enum from `simpulse_sdk`
- `HudLayoutSpec` — Layout geometry from `simpulse_sdk`
- `VehicleSensors` — Telemetry data from `simpulse_sdk`

## Usage

```python
from simpulse_overlay_sdk import BaseHudWidget, HudSlot, VehicleSensors

class MyDeltaBar(BaseHudWidget):
    @property
    def preferred_slot(self) -> HudSlot:
        return HudSlot.TOP_CENTER

    def get_hud_size(self):
        return (400, 60)

    def paint_hud(self, painter, width, height, sensors: VehicleSensors):
        # Custom rendering logic here
        ...
```
