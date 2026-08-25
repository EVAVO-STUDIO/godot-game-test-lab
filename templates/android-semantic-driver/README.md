# EVAVO Android Semantic Driver Template

This template lets Godot Game Test Lab exercise a **debug Android export** through named `InputMap` actions while the game is running on a real Android device.

It exists because Android `uiautomator` cannot meaningfully see most Godot canvas gameplay. The driver does not add raw coordinates or arbitrary Android input to `evavo-android-device-bridge`; instead, the target game opts into a small semantic contract.

## Install in a target game

1. Copy `EVAVOAndroidSemanticDriver.gd` into a tracked target-game path such as `res://addons/evavo_test_driver/EVAVOAndroidSemanticDriver.gd`.
2. Add it as an Autoload named `EVAVOAndroidSemanticDriver`.
3. Add these project settings to `project.godot`:

```ini
[evavo]

test_driver/enabled=true
test_driver/port=43821
test_driver/allowed_actions=PackedStringArray("move_left", "move_right", "jump", "attack", "pause")
```

Use only actions the physical-device QA campaign actually needs. The driver rejects actions that are not present in both this list and Godot's `InputMap`.

`android_export_admission` verifies the selected Android preset has `permissions/internet=true`, the `EVAVOAndroidSemanticDriver` autoload exists, the driver is enabled, its script exists, and 1..128 actions are declared before a physical semantic journey is allowed to export.

## Project-owned checkpoint state

Input delivery alone is not enough to prove gameplay. A target game may expose a **small, read-only semantic state dictionary** by adding one or more nodes to the `evavo_test_state_provider` group and implementing `evavo_test_state()`.

Example:

```gdscript
extends Node

func _ready() -> void:
    add_to_group("evavo_test_state_provider")

func evavo_test_state() -> Dictionary:
    return {
        "checkpoint": current_checkpoint_id,
        "alive": not player_is_dead,
        "inventory_open": inventory_panel.visible,
        "coins": coin_count,
    }
```

The driver accepts at most 32 unique state keys. Keys use the same bounded identifier alphabet as action names and values must be null, boolean, integer, float, or a string no longer than 128 characters. Nested objects, arrays, node paths, resources and arbitrary property reads are not exposed.

A journey can then prove an outcome:

```json
{
  "schema": "evavo.godot.android-semantic-journey.v1",
  "steps": [
    { "type": "press", "action": "move_right" },
    { "type": "wait", "milliseconds": 600 },
    { "type": "pulse", "action": "jump", "durationMs": 100 },
    { "type": "wait", "milliseconds": 500 },
    { "type": "release", "action": "move_right" },
    { "type": "assert-state", "expected": { "checkpoint": "ledge_2", "alive": true } }
  ]
}
```

`assert-state` compares only the explicitly named expected keys. Other project state may exist without affecting the assertion. A missing or unequal key fails the journey.

## Safety and release behaviour

The server starts only when all of these are true:

- the build has Godot's `debug` feature;
- `evavo/test_driver/enabled` is true;
- at least one valid allowed action is configured;
- every configured action exists in `InputMap`;
- the configured port is in the non-privileged range.

The listener binds only to `127.0.0.1` on the Android device. Host access is expected to use an explicitly confirmed ADB `forward` mapping owned by `evavo-android-device-bridge`.

The protocol deliberately exposes only:

- `hello`: protocol/session negotiation and action allow-list;
- `state`: bounded current-scene/process/input state plus target-owned bounded `projectState`;
- `action`: allow-listed `press`, `release` or bounded `pulse` through `Input.action_press()` / `Input.action_release()`.

It does **not** expose arbitrary method calls from the host, caller-selected node paths, property mutation, file access, Android shell, text input, keycodes, coordinates, system UI, permissions, network destinations or release-build control.

## Physical Android flow

1. Export and launch a **debug** Android APK with `scripts/Invoke-GodotLabAndroidDevice.ps1`.
2. Create a bridge forward from a host loopback port to the same device loopback port.
3. Connect the Lab's `AndroidSemanticDriverClient` to `127.0.0.1:<host-port>`.
4. Read `hello`, verify the target-declared allow-list, then execute a bounded journey with project-state assertions where useful.
5. Capture bridge screenshots/logcat and Lab journey evidence around checkpoints.
6. Remove the ADB forward after the run, including failure paths.

A semantic-driver pass with assertions proves that the real Android build accepted the declared Godot actions and reached the target game states explicitly asserted by the journey. It does not prove physical Bluetooth controller enumeration, touchscreen ergonomics, release-signing behaviour or subjective game feel by itself.
