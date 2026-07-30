# Reusable Linux Godot Sandbox

## Purpose

The reusable workflow lets each Godot repository run Linux import, build, export, software-rendered visual evidence and governed input journeys in its own GitHub security context. Private target repositories do not grant a standing cross-repository token to the public test-lab repository.

The caller owns its exact target revision and profile. Godot Game Test Lab supplies the pinned container, validator, interaction harness and evidence worker. The container cannot write to the caller checkout and receives no GitHub, deployment, signing or store credentials.

## Caller contract

A target repository commits `.evavo/godot-lab-linux.json`. Schema `1.0` covers baseline build/import/export/render evidence. Schema `2.0` adds interactive journeys:

```json
{
  "schemaVersion": "2.0",
  "projectSubpath": ".",
  "minimumGodotVersion": "4.6.2",
  "engineFlavor": "standard",
  "visual": {
    "required": true,
    "scene": "res://main.tscn",
    "frames": 360,
    "fps": 30,
    "width": 1280,
    "height": 720,
    "renderingMethod": "gl_compatibility",
    "userArguments": ["--compiled-level=bunker_01"]
  },
  "export": {
    "required": true,
    "preset": "Linux Desktop"
  },
  "journeys": [
    {
      "id": "gameplay-keyboard",
      "required": true,
      "device": "keyboard_mouse",
      "requiredActions": [
        {"name": "move_forward", "devices": ["keyboard"]}
      ],
      "steps": [
        {"type": "action", "action": "move_forward", "pressed": true},
        {"type": "wait", "frames": 30},
        {"type": "action", "action": "move_forward", "pressed": false},
        {"type": "checkpoint", "id": "moved-forward"}
      ],
      "assertions": [
        {"type": "scene_loaded"}
      ],
      "ux": {
        "maximumOutOfBoundsInteractive": 0,
        "failOnBlackFrame": true
      }
    }
  ]
}
```

The caller pins the reusable workflow by exact commit SHA and passes the same SHA as `lab_sha`:

```yaml
jobs:
  linux-godot:
    uses: EVAVO-STUDIO/godot-game-test-lab/.github/workflows/reusable-godot-linux-sandbox.yml@LAB_SHA
    with:
      lab_sha: LAB_SHA
      target_sha: ${{ github.sha }}
      profile_path: .evavo/godot-lab-linux.json
```

The workflow rejects a target SHA different from the caller workflow SHA. Both checkouts must be exact and clean. The target revision must belong to the caller repository's actual default branch, so repositories using either `main` or `master` remain supported without weakening the branch boundary.

## Isolation

The target checkout and normalized profile are mounted read-only. Godot, .NET and the input harness operate on an ephemeral copy. The container runs non-root with:

- no network;
- a read-only root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges`;
- bounded CPU, memory, swap, processes, file descriptors and runtime;
- no Docker socket, privileged mode or `/dev/uinput`;
- temporary home and `/tmp` filesystems;
- no repository or deployment credentials.

Godot editor and export-template archives are checked against the release SHA-512 manifest before installation.

## Interaction

Schema-2 journeys use Godot `InputEvent` objects sent through `Input.parse_input_event()`. The worker supports action, physical key, mouse and synthetic joypad events, named checkpoints and bounded assertions.

The worker records whether a physical joypad is connected, but synthetic joypad events are never described as physical hardware certification. They prove InputMap device coverage and the declared Godot event path only.

## Evidence

The artifact bundle contains:

- normalized caller profile and dispatch identity;
- Docker build and image metadata;
- canonical import, build, boot and optional export report;
- baseline rendered-journey stdout and stderr;
- baseline movie, probe metadata, screenshots and contact sheet;
- per-journey normalized input contract;
- per-journey stdout and stderr;
- `journey-report.json` with steps, assertions, InputMap and UI telemetry;
- `visual-ux-review.json` with objective visual diagnostics and truth boundaries;
- per-journey movie, `ffprobe.json`, screenshots, contact sheet and named checkpoint PNGs;
- `agent-summary.json` with status, exact SHAs, scenes, findings, sandbox controls, quality boundaries and SHA-256/byte metadata for retained artifacts.

## Lab self-test

`.github/workflows/linux-sandbox-smoke.yml` calls the same reusable workflow against `fixtures/linux-smoke` at the exact lab commit. It is triggered by changes to the container, entrypoint, Linux runner, input harness, profile parser, fixture, contract tests or reusable workflow.

The smoke run must build the real image, verify the Godot archives, import and boot the fixture, record the baseline X11 movie and complete three required journeys:

1. a physical-keycode event mapped through InputMap;
2. a mouse move and click on a real Godot `Button`;
3. a synthetic joypad button mapped through InputMap.

Each journey must change live scene metadata, retain a checkpoint image and satisfy the governed UI focus/layout rules. Source tests alone are not sufficient acceptance for a change to the execution path.

## Truth boundary

This lane proves Linux compatibility under the selected Godot version and Xvfb/Mesa software renderer. It can prove declared synthetic input paths and machine-checkable UI invariants. It does not prove native GPU performance, physical controller enumeration, complete gameplay, game feel, final art quality, accessibility conformance or human UX approval.
