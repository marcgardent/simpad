# SimPulse Race Engineer SDK

Contracts and data models for creating modular virtual race engineer roles and spotters.

## Provided Contracts
- `BaseRole` / `BaseEngineerSubplugin`: Abstract base class for race engineer roles.
- `AudioEngineProtocol`: Protocol for vocal phrase playback engines.

## Provided Models
- `RoleStatus`: Enum indicating whether a role is `IDLE` or `BUSY`.
- `EngineerMessage`: Strongly-typed callout message emitted by an active role.
- `RoleMetadata`: Registration metadata describing a role.
- `EngineerContext`: Evaluation context passed to roles on each telemetry tick.
