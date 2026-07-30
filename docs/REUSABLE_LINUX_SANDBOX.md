# Reusable Linux Godot Sandbox

## Purpose

The reusable workflow lets each Godot repository run Linux import, build, export and software-rendered visual evidence in its own GitHub security context. Private target repositories do not need to grant a standing cross-repository token to the public test-lab repository.

The caller owns its exact target revision and profile. Godot Game Test Lab supplies the pinned container, validator and evidence worker. The container cannot write to the caller checkout and receives no GitHub, deployment, signing or store credentials.

## Caller contract

A target repository commits `.evavo/godot-lab-linux.json`:

```json
{
  "schemaVersion": "1.0",
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
  }
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
```

The workflow rejects a target SHA different from the caller workflow SHA. Both checkouts must be exact clean ancestors of `main`.

## Isolation

The target checkout is mounted read-only. Godot and .NET operate on an ephemeral copy. The container runs non-root with:

- no network;
- a read-only root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges`;
- bounded CPU, memory, swap, processes, file descriptors and runtime;
- no Docker socket or privileged mode;
- temporary home and `/tmp` filesystems;
- no repository or deployment credentials.

Godot editor and export-template archives are checked against the release SHA-512 manifest before installation.

## Evidence

The artifact bundle contains:

- normalized caller profile and dispatch identity;
- Docker build and image metadata;
- canonical import, build, boot and optional export report;
- profiled rendered-journey stdout and stderr;
- `gameplay.avi`;
- `ffprobe.json`;
- up to six individual screenshots;
- a 3x2 contact sheet;
- `agent-summary.json` with status, exact SHAs, scene, arguments, findings, sandbox controls and SHA-256/byte metadata for every retained artifact.

## Lab self-test

`.github/workflows/linux-sandbox-smoke.yml` calls the same reusable workflow against `fixtures/linux-smoke` at the exact lab commit. It is triggered by changes to the container, entrypoint, Linux runner, profile parser, fixture, contract tests or reusable workflow.

The smoke run must build the real image, verify the Godot archives, import and boot the fixture, record 180 rendered X11 frames, probe the movie, extract screenshots and upload the evidence bundle. Source tests alone are not sufficient acceptance for a change to the sandbox execution path.

## Truth boundary

This lane proves Linux compatibility under the selected Godot version and Xvfb/Mesa software renderer. It does not prove real GPU performance, input correctness, game feel, complete gameplay or final art quality. Those remain separate native hardware, browser, automated interaction and human-review boundaries.
