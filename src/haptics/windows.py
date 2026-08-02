from src.haptics.sdl3_controller import SDL3HapticController


class WindowsHapticController(SDL3HapticController):
    """
    Windows haptic implementation via SDL3/GameInput.

    XInput (Xbox 360 driver) exposes two physical zones:
      - low_frequency_rumble  → left  motor (heavy/slow)  → our "low"  channel
      - high_frequency_rumble → right motor (light/fast)  → our "high" channel

    Fix: route low signals exclusively to lf, high signals exclusively to hf,
    so the two motor textures remain perceptually distinct.
    Left/right spatial separation is deferred until Linux migration.
    """

    def set_vibration(
        self,
        left_low:    float = 0.0,
        left_high:   float = 0.0,
        right_low:   float = 0.0,
        right_high:  float = 0.0,
        duration_ms: int   = 0,
    ) -> None:
        # Unify L/R into a single global intensity per frequency band
        unified_low  = max(left_low,  right_low)
        unified_high = max(left_high, right_high)

        # Route low  → left_low  only  (lf = l_low + l_high → lf = unified_low)
        # Route high → right_high only (hf = r_low + r_high → hf = unified_high)
        # This keeps the two motor textures perceptually separate.
        super().set_vibration(
            left_low=unified_low,
            left_high=0.0,
            right_low=0.0,
            right_high=unified_high,
            duration_ms=duration_ms,
        )
