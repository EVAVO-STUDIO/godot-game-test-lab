# Godot Game Test Lab

Godot Game Test Lab is EVAVO Studio's reusable build, runtime, interaction,
visual-evidence, and QA worker for Godot repositories. The lab can inspect and
exercise a game in a completely separate Git repository. It does not need to be
copied into the game and it never receives authority to edit, commit, push,
sign, deploy, or publish the target game.

Development Studio is the control plane. It selects the exact target repository,
commit, project subpath, evidence lane, and repair authority. Godot Game Test Lab
performs native and isolated execution. Godot Web Runtime remains the browser
lane for compatible web exports.

## Capabilities

The current surface supports:

- bounded discovery of one `project.godot`, including explicit monorepo
  subpaths;
- GDScript versus C# workload detection;
- standard Godot versus Godot .NET editor selection;
- Godot 4.6.2 minimum-version enforcement with compatible later 4.x releases;
- `.NET` discovery and `dotnet build` before C# import;
- static project, scene, resource, path, Git, LFS, and common asset-integrity
  diagnosis;
- authoritative headless Godot import and recovery-mode isolation;
- bounded boot, debug/release export, and deterministic Movie Maker recording;
- safe explicit scene execution using Godot's positional project argument;
- repository-owned keyboard, mouse, semantic action, and synthetic gamepad
  journeys;
- InputMap coverage, scene/node/focus/visibility/metadata assertions;
- named checkpoints, screenshots, contact sheets, FFprobe metadata, black-video
  diagnostics, and frozen-video diagnostics;
- exact-SHA native Windows runs in Greg's logged-in interactive session;
- requested rendering method, rendering driver, and GPU index evidence;
- isolated Linux Xvfb/Mesa llvmpipe compatibility runs;
- bounded stdout/stderr, process-tree termination, evidence byte limits, exact
  source archives, and SHA-256 artifact inventories;
- a cross-process Windows desktop lease so concurrent agents cannot compete for
  the same interactive desktop.

## Repository layout

The lab and target remain separate:

```text
C:\GitRepos\godot-game-test-lab
C:\GitRepos\Brass_Brine
C:\GitRepos\another-game
D:\Prototypes\nested-monorepo
C:\GodotLabEvidence\<game>\<run-id>
```

Retained evidence must be outside both the lab checkout and the target checkout.
The exact native worker refuses dirty lab or target repositories because a dirty
working tree cannot truthfully be represented by a commit SHA. Git submodules
currently fail closed; the exact `git archive` worker does not silently omit
submodule content.

## Installation

```powershell
Set-Location C:\GitRepos\godot-game-test-lab

git pull --ff-only origin main
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip --version
python -m pip install --disable-pip-version-check -e ".[dev]"

godot-lab capabilities
godot-lab doctor
godot-lab-native-qa --help
```

Generated Python package metadata is ignored by Git, so an editable installation
does not invalidate the clean-checkout gate.

Set native tools explicitly when they are not discoverable:

```powershell
$env:GODOT_BIN = "C:\Tools\Godot\Godot_v4.6.2-stable_win64_console.exe"
$env:GODOT_MONO_BIN = `
  "C:\Tools\GodotMono\Godot_v4.6.2-stable_mono_win64_console.exe"
$env:DOTNET_BIN = "C:\Program Files\dotnet\dotnet.exe"
```

Install both standard and .NET Godot editors when the estate contains both
GDScript and C# games. FFmpeg and FFprobe are required for native screenshot,
contact-sheet, black-segment, freeze-segment, and media-metadata evidence.
`nvidia-smi`, `vulkaninfo`, and `nvcc` are optional environment probes.

## Cross-repository validation

```powershell
$Game = "C:\GitRepos\Brass_Brine"
$Evidence = "C:\GodotLabEvidence\Brass_Brine\validation-$(Get-Date -Format yyyyMMdd-HHmmss)"

godot-lab inspect $Game

godot-lab audit $Game `
  --output "$Evidence\integrity-report.json"

godot-lab validate $Game `
  --artifacts "$Evidence\validation"
```

The validation order is:

1. bounded project inventory and static integrity;
2. Godot identity, version, flavour, and CLI-capability verification;
3. `.NET` identity and `dotnet build` for C# projects;
4. authoritative Godot editor import;
5. recovery-mode import after normal-import failure;
6. bounded boot after clean import;
7. separate JSON, stdout, stderr, and engine-log evidence.

Static findings are diagnostics. The matching Godot editor remains authoritative
for parsing and import. Recovery success identifies a likely import-time
extension surface; it does not by itself identify which plugin, `@tool` script,
or GDExtension caused the failure.

## Explicit scene runs

The Lab CLI accepts a convenient `--scene` option, validates the resource, and
converts it to Godot's positional scene argument before execution:

```powershell
godot-lab run C:\GitRepos\Brass_Brine `
  --scene res://tests/native_smoke.tscn `
  --frames 300

godot-lab record C:\GitRepos\Brass_Brine `
  --scene res://tests/native_smoke.tscn `
  --output C:\GodotLabEvidence\Brass_Brine\native-smoke.avi `
  --frames 300 `
  --fps 30
```

The worker rejects traversal, missing scenes, symlinks, duplicate selectors, and
non-scene resources. An unknown Godot option being ignored is never accepted as
proof that a requested scene ran.

## Native Windows agent QA

A game owns a tracked profile, normally:

```text
<game>\.evavo\godot-lab-native.json
```

Start from `examples/native-agent-qa.profile.json` and validate it against
`schemas/native-agent-qa-profile.schema.json`. The worker accepts profile schema
1.0 for migration but normalizes every run to schema 2.0.

```powershell
$Lab = "C:\GitRepos\godot-game-test-lab"
$Game = "C:\GitRepos\Brass_Brine"
$EvidenceRoot = "C:\GodotLabEvidence"
$Run = Join-Path $EvidenceRoot "Brass_Brine\$(Get-Date -Format yyyyMMdd-HHmmss)"

Set-Location $Lab

.\scripts\Invoke-GodotLabNativeAgentQA.ps1 `
  -TargetRepositoryPath $Game `
  -ProjectSubpath "." `
  -ProfilePath ".evavo\godot-lab-native.json" `
  -ExpectedLabSha (git rev-parse HEAD) `
  -ExpectedTargetSha (git -C $Game rev-parse HEAD) `
  -ArtifactPath $Run `
  -AllowedArtifactRoot $EvidenceRoot `
  -PythonExecutable ".\.venv\Scripts\python.exe" `
  -MinimumGodotVersion "4.6.2" `
  -TimeoutSeconds 900 `
  -BootFrames 30 `
  -WindowPosition "32,32"
```

Renderer, rendering-driver, GPU-index, resolution, FPS, steps, assertions, and
visual policies belong in the tracked target profile. They are not ungoverned
wrapper overrides.

The native worker:

1. verifies exact clean lab and target SHAs;
2. verifies the profile is a tracked regular file;
3. acquires the single native-desktop lease;
4. confirms Explorer is in the worker's nonzero Windows session;
5. creates a bounded, link-free, Windows-portable exact `git archive` copy;
6. runs the canonical validation CLI behind a whole-process watchdog;
7. verifies visual CLI capabilities through `godot --help`;
8. runs target-owned deterministic journeys in the ephemeral copy;
9. limits total runtime, output retention, evidence bytes, files, and
   resolution-by-frame work;
10. captures process, Godot, hardware, media, checkpoint, and visual evidence;
11. verifies the original target checkout remains unchanged before returning.

A normal self-hosted runner installed as a Windows service is usually in Session
0 and is rejected for visible-desktop evidence. Launch the approved runner in
Greg's logged-in account. Only one native desktop run may hold the lease at a
time.

## Native profile bounds

Profiles fail closed on unknown fields, duplicate journey/action/checkpoint IDs,
non-finite numbers, lifecycle-argument overrides, unsafe checkpoint names, and
incompatible renderer/driver combinations. Current bounds include:

- 16 journeys per profile;
- 256 steps and 128 assertions per journey;
- 32 checkpoints per journey;
- 600 seconds maximum represented duration per journey;
- 3840×2160 maximum declared resolution;
- 60 FPS maximum;
- per-journey and whole-profile pixel-frame budgets;
- explicit total run-time and artifact-byte budgets at the worker boundary.

Black and frozen segments are always measured when FFmpeg is available. They
become failures only when the target profile explicitly enables the corresponding
policy, preventing intentional splash fades or static screens from becoming
false failures.

## Evidence

A native run may retain:

```text
<native-run>\
  native-agent-summary.json
  run-context.json
  source-archive.json
  profile.normalized.json
  hardware.json
  validation\
    report.json
    integrity-report.json
    engine-logs\
  journeys\<id>\
    journey.normalized.json
    journey-report.json
    godot.log
    gameplay.avi
    ffprobe.json
    contact-sheet.png
    screenshots\
    checkpoints\
  logs\
```

`native-agent-summary.json` records the exact SHAs, source/profile hashes,
project subpath, desktop lease, session state, validation result, requested
renderer/driver/GPU index, process receipts, findings, budget consumption,
target mutation state, and a SHA-256 inventory of retained evidence. Large
stdout, stderr, and engine logs are bounded while they are produced or read,
rather than being accumulated without limit first.

A blocked or interrupted run attempts to retain a bounded non-pass summary when
the requested evidence directory is safe and belongs to that run.

## Isolated Linux agent QA

Each game should call
`.github/workflows/reusable-godot-linux-sandbox.yml` from its own repository
context and pin an exact Lab SHA and exact caller SHA. The Linux lane mounts the
target read-only, works in an ephemeral copy, runs without network or repository
credentials, and renders through Xvfb and Mesa llvmpipe.

Linux software rendering is deterministic compatibility evidence. It is not
native Windows GPU, physical-controller, performance, or human visual evidence.
See `docs/REUSABLE_LINUX_SANDBOX.md`, `docs/INTERACTIVE_AGENT_QA.md`, and
`docs/LINUX_SANDBOX_CONTRACT.md`.

## Exact-SHA GitHub automation

`.github/workflows/evavo-native-godot-validation.yml` is the manual,
Development-Studio-dispatched Windows lane. It requires exact Lab and target
SHAs, an explicit project subpath, and the approved self-hosted labels:

```text
self-hosted, Windows, X64, evavo-godot-lab
```

Supplying a tracked native profile enables the native visual/input stage.
Without a profile, the workflow performs validation only. The workflow has no
target commit, push, branch, deployment, signing, or publication authority.

## Truth boundaries

- A static audit does not replace matching-editor import.
- A bounded boot proves startup only.
- A screenshot, movie, or contact sheet is not a complete playthrough.
- Synthetic keyboard/mouse events prove the declared Godot event path, not
  real-device latency.
- Synthetic joypad events do not certify a physical controller, Steam Input,
  rumble, wireless behaviour, or device-specific latency.
- Requested GPU index and adapter logs do not automatically prove performance,
  thermals, frame pacing, or that every subsystem executed on that adapter.
- CUDA is auxiliary compute capability, not Godot's rendering backend.
- UI geometry checks do not replace accessibility, game-feel, art-direction, or
  human QA review.
- The Lab diagnoses and retains evidence. Target repair and publication require
  a separate Development Studio grant and the target repository's own lease.

## Development checks

```powershell
python scripts/check_repository_toolchain.py
python scripts/test_repository_toolchain.py
python -m compileall -q src scripts tests
python -m ruff check src scripts tests
python -m pytest
python -m pip wheel --no-deps --wheel-dir dist .
```

Source tests prove the Python, shell, workflow, and policy contract only. Native
Godot, Windows desktop, driver, GPU, target-game, and visual facts exist only
after a real exact-SHA worker run retains them.

## Deterministic autonomous bot QA

Any Godot repository can generate a strict starter profile and run bounded runtime exploration:

```powershell
godot-lab-init-qa C:\GitRepos\Brass_Brine `
  --output .evavo\godot-lab-bot.json `
  --report .evavo\godot-lab-bot.discovery.json

.\scripts\Invoke-GodotLabBotQA.ps1 `
  -TargetRepositoryPath C:\GitRepos\Brass_Brine `
  -ProjectSubpath . `
  -ProfilePath .evavo\godot-lab-bot.json `
  -ExpectedLabSha (git rev-parse HEAD) `
  -ExpectedTargetSha (git -C C:\GitRepos\Brass_Brine rev-parse HEAD) `
  -ArtifactPath C:\GodotLabEvidence\Brass_Brine\bot-latest `
  -AllowedArtifactRoot C:\GodotLabEvidence
```

The bot runs canonical validation first, discovers runtime controls and InputMap events, replays mouse, keyboard, semantic and synthetic gamepad traces in fresh processes with isolated user data, records screenshots and representative movies, and retains a reproducible state graph. See `docs/AUTONOMOUS_BOT_QA.md`.
