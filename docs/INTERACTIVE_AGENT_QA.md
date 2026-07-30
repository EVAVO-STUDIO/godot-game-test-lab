# Interactive Godot Agent QA

## Purpose

The interactive agent lane extends the canonical Linux build, import, boot, render and export worker with bounded, repository-authored input journeys. It gives automated development and repair agents repeatable evidence that a real Godot scene accepted keyboard, mouse or controller-style input and reached expected state without duplicating test-lab runtime code inside every game.

Development Studio remains the portfolio orchestrator and repair authority. A game repository owns its profile and expected journey. Godot Game Test Lab owns execution, evidence and fail-closed validation. Godot Web Runtime remains the browser interaction authority for compatible web exports.

## Profile schema

Interactive journeys require `.evavo/godot-lab-linux.json` schema `2.0`. Schema `1.0` remains supported for baseline build/import/export/render evidence.

A profile may declare up to four journeys. Each journey is bounded by a maximum frame count and may include:

- action press, release or tap events;
- physical keyboard key events;
- mouse movement, button and click events;
- synthetic joypad button and axis events;
- waits and named screenshot checkpoints;
- required InputMap actions and device categories;
- scene, node, visibility, focus and metadata assertions;
- visual and UX thresholds.

Example:

```json
{
  "schemaVersion": "2.0",
  "projectSubpath": ".",
  "minimumGodotVersion": "4.6.2",
  "engineFlavor": "standard",
  "visual": {
    "required": true,
    "scene": "res://main.tscn",
    "frames": 180,
    "fps": 30,
    "width": 1280,
    "height": 720,
    "renderingMethod": "gl_compatibility",
    "userArguments": []
  },
  "export": {
    "required": false,
    "preset": ""
  },
  "journeys": [
    {
      "id": "menu-keyboard",
      "required": true,
      "device": "keyboard_mouse",
      "maxFrames": 360,
      "requiredActions": [
        {"name": "ui_accept", "devices": ["keyboard"]}
      ],
      "steps": [
        {"type": "action_tap", "action": "ui_accept"},
        {"type": "wait", "frames": 30},
        {"type": "checkpoint", "id": "menu-accepted"}
      ],
      "assertions": [
        {"type": "scene_loaded"}
      ],
      "ux": {
        "maximumOutOfBoundsInteractive": 0,
        "requireFocusOwner": true,
        "failOnBlackFrame": true
      }
    }
  ]
}
```

## Input execution

The harness injects Godot `InputEvent` objects through `Input.parse_input_event()`. This exercises Godot's own input dispatch path and therefore reaches `_input`, `_shortcut_input`, `_unhandled_key_input`, `_unhandled_input`, GUI input and InputMap action handling according to the target scene.

The harness supports semantic `InputEventAction` events as well as concrete key, mouse and joypad events. Concrete events are preferred when the journey must prove that a repository mapping exists for a particular device class.

### Controller truth boundary

Joypad events are synthetic Godot events. They prove that:

- the InputMap contains the required gamepad mapping;
- the running scene accepts the corresponding joypad button or axis event;
- the expected state or presentation follows from that event.

They do not prove USB enumeration, SDL mapping for a particular physical controller, wireless latency, rumble, platform overlays, Steam Input or hardware-specific dead zones. The retained report always marks `syntheticInput: true` and `hardwareGamepadClaimed: false`. Physical controller certification remains a separate fresh native-runner or human-device boundary.

## Runtime isolation

The target repository checkout is immutable and read-only. The harness script and normalized journey JSON are copied only into the ephemeral working project. The sandbox retains the existing controls:

- no network;
- non-root execution;
- read-only root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges`;
- bounded CPU, memory, swap, process count, open files and wall time;
- no Docker socket, `/dev/uinput`, privileged mode or repository credentials.

The target checkout SHA and clean status are rechecked after execution.

## UX and layout telemetry

At the end of each journey, the harness inventories visible Godot `Control` nodes and records:

- viewport dimensions;
- visible and interactive control counts;
- GUI focus owner;
- mouse mode;
- interactive controls outside the viewport;
- controls below the governed minimum target size;
- intersecting interactive-control pairs;
- an optional bounded control-tree inventory.

This catches many deterministic UI regressions, including clipped buttons, missing keyboard/gamepad focus, tiny targets and overlapping interactive regions. It does not replace subjective art direction, readability review, accessibility testing or game-feel review.

## Visual evidence

Every interactive journey can retain:

- deterministic `gameplay.avi` output;
- `ffprobe.json` stream metadata;
- up to eight individual screenshots;
- a contact sheet;
- named checkpoint PNGs captured by the Godot harness;
- black-segment and frozen-segment diagnostics;
- `journey-report.json` with steps, assertions, InputMap and UI telemetry;
- `visual-ux-review.json` with objective visual findings and truth boundaries;
- stdout and stderr logs.

Required journey failures fail the repository workflow. Optional journey failures are retained as findings without replacing required build/import/export acceptance.

## Repository adoption

Each active Godot repository should commit:

1. `.evavo/godot-lab-linux.json`, owned by the game and pinned to its real scene, arguments, export preset and journey expectations.
2. `.github/workflows/godot-linux-agent-qa.yml`, calling the reusable lab workflow at an exact lab commit SHA and passing the exact caller SHA.
3. A reliability or agent note stating that build/import/export and journey evidence must be reviewed before a repair is declared complete.

The caller workflow runs in the game repository's GitHub security context and needs only `contents: read`. No standing cross-repository private-repository token is required for the standard caller path.

## Development Studio integration

Development Studio should maintain an inventory of adopted projects and consume the retained `agent-summary.json` and per-journey review files. It may classify failures, compare evidence, propose bounded repairs and dispatch reruns. It must not duplicate Godot installation, rendering or input execution logic, and it may not write to a game repository without that repository's governed mainline grant.

## Acceptance boundary

A green interactive lane proves the declared project revision:

- builds where applicable;
- imports and boots under the selected Godot runtime;
- optionally exports through the declared preset;
- renders under Xvfb and Mesa software rendering;
- accepts the declared synthetic input sequence;
- satisfies the declared machine-checkable state and UI assertions.

It does not prove complete gameplay, physical controller behavior, native GPU performance, final visual quality or human UX approval. Those limitations are included in every agent summary so an automated repair system cannot overstate the evidence.
