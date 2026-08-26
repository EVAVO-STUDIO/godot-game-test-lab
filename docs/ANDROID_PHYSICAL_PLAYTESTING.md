# Android physical playtesting ownership

Godot Game Test Lab does not own a second raw ADB automation stack.

## Canonical layers

1. **EVAVO Android Device Bridge** owns Android transport, package install/update, launch/stop, foreground checks, screenshots, diagnostics, health, package-bound UIAutomator actions, and normalized game-surface input.
2. **EVAVO Automated Testing** owns worker leases, registered targets, evidence ingestion, exploratory campaigns and physical gameplay journeys.
3. **Godot Game Test Lab** owns game-aware semantic state/actions through the debug-only loopback semantic driver and game-specific assertions.
4. **EVAVO Development Studio** may orchestrate these layers, but must not bypass them with arbitrary `adb shell` or raw device coordinates.

## UI vs rendered-game interaction

Normal Android views should use the Device Bridge governed app-test plan contract. Selectors are resolved privately against package-owned UI nodes. Ambiguous or dangerous controls fail closed. Screenshot checkpoints are private evidence.

Godot `SurfaceView`/rendered gameplay should use the registered gameplay journey/semantic-driver path. Normalized tap/swipe/key inputs are allowed only through registered, bounded gameplay authority. Raw caller-supplied device coordinates are not a general automation API.

## Required physical evidence

A physical playtest should establish at minimum:

- expected package installed and running;
- expected package in foreground before interaction;
- bounded input/action plan;
- screenshot checkpoints;
- fresh crash/ANR/native-crash diagnostics;
- package-scoped runtime health;
- final running/foreground state;
- no raw ADB serial retained in the public receipt.

## Prohibited shortcuts

Do not add a generic arbitrary ADB shell endpoint, system-UI clicking, unrestricted coordinate tapping, purchase/account actions, permission-dialog automation, or unregistered destructive game actions simply to make a test pass.
