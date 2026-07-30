# Godot Game Test Lab

Canonical native Godot build, runtime, interaction, evidence and QA worker for EVAVO Studio repositories.

Development Studio owns repository inventory, triage, policy, incident state, repair decisions and publication authority. Godot Game Test Lab owns native Godot execution on freshly probed Windows runners and isolated Linux evidence workers. Godot Web Runtime owns browser-hosted loading, Playwright interaction, screenshots, traces and semantic browser observations.

## Current working surface

Version 0.4.0 provides:

- project discovery and inventory;
- GDScript versus C# workload detection;
- standard Godot versus Godot .NET selection;
- minimum Godot version enforcement, defaulting to 4.6.2;
- `.NET` discovery and `dotnet build` for C# projects;
- headless Godot import and parser evidence;
- bounded headless boot evidence;
- bounded native windowed or headless runs;
- command-line debug and release export;
- deterministic Movie Maker recording with fixed FPS and bounded frames;
- an isolated Ubuntu 24.04 Linux sandbox with Xvfb and Mesa software rendering;
- a read-only target mount and ephemeral writable project copy;
- repository-authored keyboard, mouse and synthetic joypad journeys;
- InputMap device-coverage evidence;
- scene, node, focus, visibility and metadata assertions;
- named journey checkpoints, screenshots, video and contact sheets;
- deterministic UI geometry, clipping, focus, target-size and overlap telemetry;
- black-segment and frozen-segment video diagnostics;
- JSON reports and separate stdout/stderr evidence logs;
- dependency-free runtime code with pinned pytest and Ruff development gates.

## Installation

```powershell
Set-Location C:\GitRepos\godot-game-test-lab
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip --version
python -m pip install -e ".[dev]"
```

Set the native tools explicitly when they are not on `PATH`:

```powershell
$env:GODOT_BIN = "C:\Tools\Godot\Godot_v4.6.2-stable_win64_console.exe"
$env:GODOT_MONO_BIN = "C:\Tools\GodotMono\Godot_v4.6.2-stable_mono_win64_console.exe"
$env:DOTNET_BIN = "C:\Program Files\dotnet\dotnet.exe"
```

## Agent entrypoints

Inspect runner tools:

```powershell
godot-lab doctor
```

Inspect a project without executing it:

```powershell
godot-lab inspect C:\GitRepos\Brass_Brine
```

Run the canonical native validation pipeline and retain evidence:

```powershell
godot-lab validate C:\GitRepos\Brass_Brine `
  --artifacts C:\GitRepos\Brass_Brine\.qa\latest
```

The native validation order is:

1. project inventory;
2. exact Godot identity and version;
3. Godot .NET requirement for C# projects;
4. `.NET` identity and `dotnet build` where required;
5. Godot headless editor import;
6. bounded headless main-scene boot;
7. JSON report plus command logs.

Launch a bounded run:

```powershell
godot-lab run C:\GitRepos\epochbound --frames 600
```

Record deterministic native visual evidence:

```powershell
godot-lab record C:\GitRepos\epochbound `
  --output C:\GitRepos\epochbound\.qa\epochbound-smoke.avi `
  --frames 300 `
  --fps 30
```

Export a declared preset:

```powershell
godot-lab export C:\GitRepos\epochbound `
  --preset "Windows Desktop" `
  --output C:\GitRepos\epochbound\dist\epochbound.exe
```

## Reusable Linux agent QA

Each active Godot repository should call `.github/workflows/reusable-godot-linux-sandbox.yml` from its own repository context. The game commits `.evavo/godot-lab-linux.json` and pins the lab workflow to an exact lab commit SHA.

Caller example:

```yaml
name: Godot Linux Agent QA

on:
  push:
    branches: [main]
    paths-ignore:
      - "docs/**"
      - "**/*.md"
  workflow_dispatch:

permissions:
  contents: read

jobs:
  linux-agent-qa:
    uses: EVAVO-STUDIO/godot-game-test-lab/.github/workflows/reusable-godot-linux-sandbox.yml@LAB_SHA
    with:
      lab_sha: LAB_SHA
      target_sha: ${{ github.sha }}
      profile_path: .evavo/godot-lab-linux.json
      retention_days: 14
```

The standard caller path:

- checks out the exact caller commit with Git LFS content;
- verifies it is a clean ancestor of the caller repository's actual default branch;
- checks out the exact public lab commit;
- reads and normalizes the repository-owned profile;
- builds a manifest-verified Godot image;
- runs without network or repository credentials;
- performs import, build, boot, optional export, baseline rendering and declared journeys;
- verifies that the caller checkout remains unchanged;
- uploads bounded agent-readable evidence.

It uses the caller repository's normal read context and does **not** require a standing cross-repository private-repository token. The separate administrative dispatcher workflow remains available only for centrally initiated legacy/manual jobs and is not the estate adoption standard.

## Interactive journey profile

Profile schema `2.0` adds bounded journeys. A journey can send Godot action, key, mouse and joypad events; wait; capture checkpoints; require InputMap device coverage; and assert scene, node, focus, visibility or metadata state.

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

See `docs/INTERACTIVE_AGENT_QA.md` for the full contract and evidence boundary.

## Isolated Linux worker

The Linux image:

- starts from a dated Ubuntu 24.04 image pinned by exact digest;
- verifies official Godot editor and export-template archives against the release SHA-512 manifest;
- automatically selects standard Godot or the .NET editor from the target workload;
- includes .NET SDK 8 for C# compilation;
- mounts target source read-only and performs all imports/builds in an ephemeral copy;
- runs as a non-root user with no network, capabilities or elevated privileges;
- uses a read-only root filesystem, bounded resources and temporary filesystems;
- renders through Xvfb X11 and Mesa llvmpipe;
- never receives repository, deployment, signing or store credentials.

## Evidence

A complete schema-2 run may contain:

- `dispatch.json` and the normalized profile;
- Docker build and image metadata;
- `sandbox-report.json` for import/build/boot/export stages;
- baseline `visual/gameplay.avi`, screenshots, contact sheet and `ffprobe.json`;
- one directory per journey;
- per-journey stdout and stderr;
- `journey-report.json` with steps, assertions, InputMap and UI telemetry;
- `visual-ux-review.json` with objective visual findings;
- named checkpoint PNGs;
- per-journey movie, screenshots, contact sheet and probe metadata;
- `agent-summary.json` with exact SHAs, commands, findings, truth boundaries, artifact byte counts and SHA-256 identities.

## Exact-SHA native automation

The repository includes `.github/workflows/evavo-native-godot-validation.yml` for approved self-hosted Windows validation.

The workflow:

- runs only through manual `workflow_dispatch`;
- requires an exact test-lab `main` SHA;
- requires the exact target game repository SHA;
- requires `request_source=evavo-development-studio`;
- accepts only target paths beneath `C:\GitRepos`;
- uses runner labels `self-hosted`, `Windows`, `X64`, and `evavo-godot-lab`;
- prepares an isolated Python 3.11 environment using pinned build and validation dependencies;
- refuses to run unless the target checkout `HEAD` matches `expected_target_sha`;
- runs compile, Ruff, pytest, doctor and the canonical Godot validation pipeline;
- compares tracked target-repository status before and after execution;
- fails if validation changes any tracked game source;
- uploads bounded evidence for 14 days;
- has no checkout reset, target commit, push, PR, deployment or publication authority.

Runner provisioning and local parity are defined in `docs/NATIVE_RUNNER_CONTRACT.md`.

## Truth boundaries

- A passing headless import is not proof of game feel or visual quality.
- A bounded boot proves startup only; it does not prove complete gameplay.
- A recorded movie or contact sheet is visual evidence, not a complete playthrough.
- Synthetic keyboard and mouse events prove the declared Godot event path, not real-device latency.
- Synthetic joypad events prove InputMap coverage and event handling, not physical USB enumeration or controller certification.
- Xvfb with Mesa software rendering does not prove hardware-specific Vulkan behavior or performance.
- Deterministic layout telemetry catches objective clipping, focus, overlap and target-size defects but does not replace human art direction or accessibility review.
- Browser interaction should use Godot Web Runtime when the project supports a GDScript Compatibility-renderer web export.
- Godot 4 C# projects cannot use the browser-export path and must be tested natively.
- Export commands require valid project export presets and installed export templates.
- The lab never edits tracked game source, creates a target branch, commits, pushes or deploys by itself. Development Studio grants and records those effects.

## Development checks

```powershell
python -m compileall src scripts tests
python -m ruff check src scripts tests
bash -n scripts/*.sh
python -m pytest
```

Source tests validate the Python, shell, workflow and policy contract without claiming a real Godot or Docker run. Actual import, build, boot, export, rendered journey and input evidence exists only after the exact-SHA workflow or equivalent local sandbox execution completes.

## Mainline policy

Automated work is committed directly to `main` only after relevant checks pass. No automated feature or repair branches are created. Force-push is forbidden. See `AGENTS.md`, `CLAUDE.md` and `evavo.reliability.json`.
