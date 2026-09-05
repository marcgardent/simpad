# SimPulse Haptics SDK

Contracts and data models for multi-channel haptic feedback and XInput dual-motor vibration.

## Provided Contracts
- `HapticController`: Abstract interface for haptic feedback hardware controllers.
- `BaseHapticSubplugin` / `IHapticSubplugin`: Abstract base contract for haptic effect generators.
- `IHapticChannelMapper`: Abstract interface for channel mapping to rumble motors.

## Provided Models
- `HapticMotorOutput`: 4-channel rumble intensities (left_low, left_high, right_low, right_high) with XInput dual-motor mapping.
- `WaveformShape`: Enumeration of standard time-modulated haptic waveform shapes.
