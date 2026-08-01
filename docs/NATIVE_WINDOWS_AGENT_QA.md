# Native Windows Agent QA

The native worker runs a Godot project from any exact Git checkout on Greg's
logged-in Windows desktop. The Lab and game remain separate repositories. The
game owns the tracked journey profile; the Lab owns bounded execution and
retained evidence; Development Studio owns selection, repair authority, and
publication.

## Evidence boundary

Headless import, bounded boot, and Linux Xvfb/Mesa runs are useful compatibility
checks, but they do not prove the visible Windows session, native display driver,
selected GPU, window presentation, or target-owned native journey. This lane
adds those facts without granting the Lab target-source write access.

A normal Windows service usually runs in Session 0. The native worker therefore
requires all of the following before it makes a desktop-evidence claim:

- Windows rather than a hosted Linux worker;
- a nonzero process session;
- `explorer.exe` running in the same session;
- the approved runner launched in Greg's logged-in account;
- the single Godot Lab desktop mutex acquired by this run.

RDP is usable only while Explorer and the worker remain in the same active
session. The public noninteractive switch exists for contract testing and never
creates native desktop evidence.

## Workstation setup

```powershell
Set-Location C:\GitRepos\godot-game-test-lab

git pull --ff-only origin main
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --disable-pip-version-check -e ".[dev]"

godot-lab capabilities
godot-lab doctor
godot-lab-native-qa --help
```

Install:

- standard Godot 4.6.2 or a compatible later 4.x editor for GDScript;
- Godot .NET plus .NET 8 for C# games;
- FFmpeg and FFprobe for media evidence;
- the appropriate Vulkan, Direct3D 12, or OpenGL driver.

`nvidia-smi`, `vulkaninfo`, and `nvcc` are optional environment probes. CUDA is
not Godot's renderer.

## Exact clean source

The Lab and target checkouts must both be at the requested exact commit and have
no tracked or untracked changes. This is deliberate: a dirty checkout cannot be
truthfully represented by its `HEAD` SHA. Ignored caches such as `.godot`, a
virtual environment, and generated `*.egg-info` remain outside the claim.

The exact archive lane currently rejects Git submodules rather than silently
omitting their content. Repositories with submodules require a separately
materialized and governed source contract before native QA.

## Target-owned profile

Commit a profile such as:

```text
<game>\.evavo\godot-lab-native.json
```

Start from `examples/native-agent-qa.profile.json`. The authoritative input
schema is `schemas/native-agent-qa-profile.schema.json`. Schema 1.0 is accepted
for migration, but every retained profile is normalized to schema 2.0.

The profile owns:

- required and optional journeys;
- the scene to load, or the configured main scene;
- keyboard, mouse, action, and synthetic gamepad steps;
- InputMap requirements and state assertions;
- rendering method and rendering driver;
- requested GPU index for Forward+ or Mobile;
- resolution, FPS, frame budget, checkpoints, and visual policies.

Renderer and GPU choices are committed profile data, not ad hoc PowerShell
arguments.

## Local invocation

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

For a monorepository, `TargetRepositoryPath` is the Git root and
`ProjectSubpath` identifies the directory containing `project.godot`.

## Execution sequence

1. Resolve disjoint Lab, target, allowed-evidence, and run-specific paths.
2. Verify exact clean Lab and target SHAs.
3. Verify the target profile is a tracked regular file.
4. Strictly normalize fields, types, IDs, steps, assertions, and bounds.
5. Acquire the cross-process native desktop lease.
6. Capture session, Explorer, adapter, NVIDIA, Vulkan, FFmpeg, and CUDA-adjacent
   environment evidence.
7. Create a link-free, special-file-free, Windows-portable exact `git archive`
   working copy with file and expanded-byte limits.
8. Verify the archived profile hash equals the source profile hash.
9. Run the canonical `godot-lab validate` command as a supervised subprocess.
10. Enforce a whole-validation watchdog and evidence budget around that
    subprocess.
11. Run target-owned visual journeys only after validation passes.
12. Bound process output while it is produced and terminate process trees on
    timeout or evidence overflow.
13. Retain Godot logs, journey reports, checkpoints, movies, screenshots,
    FFprobe data, black/freeze diagnostics, and process logs.
14. Remove the ephemeral source copy.
15. Recheck the original target checkout and fail if any change appeared.
16. Hash and inventory retained evidence before writing the final summary.

## Bounded profiles

The normalizer rejects:

- unknown profile, journey, step, assertion, or UX fields;
- duplicate journey, required-action, or checkpoint IDs;
- unsafe checkpoint names and path-like IDs;
- non-finite or incorrectly typed values;
- user arguments that override worker-owned Godot lifecycle options;
- incompatible rendering method/driver combinations;
- journey steps whose estimated frame use exceeds `maxFrames`;
- per-journey or total resolution-by-frame budgets that are too large.

Current primary bounds are 16 journeys, 256 steps, 128 assertions, 32
checkpoints, 600 seconds of represented journey duration, 3840×2160, and 60
FPS. The worker also has explicit total time and artifact-byte limits.

## Scene execution

The native journey harness loads the requested scene inside the ephemeral game
copy. Direct `godot-lab run` and `godot-lab record` calls validate their
user-facing `--scene` value and convert it to Godot's positional project
argument. The Lab never treats an invented or silently ignored engine option as
proof that a scene ran.

## Evidence layout

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

The summary keeps compact process receipts while full bounded stdout and stderr
remain separate files. The artifact list records byte sizes and SHA-256 hashes.
Evidence symlinks, special entries, changing files, file-count overflow, and
byte overflow fail closed.

Black and frozen segments are always diagnosed when FFmpeg is available. They
fail a journey only when the profile explicitly enables `failOnBlackFrame` or
`failOnFrozenVideo`, allowing intentional fades and static screens to remain
valid when the game declares them.

## Failure handling

A blocked or interrupted run attempts to retain a non-pass
`native-agent-summary.json` when the artifact destination is safe and belongs
to the current run. It does not overwrite an unrelated pre-existing evidence
directory. Source-copy cleanup and target mutation checks execute on every exit
path.

## Truth boundaries

- Static integrity is diagnostic; matching-editor import is authoritative.
- Recovery-mode success isolates a disabled import-time surface but not the
  exact root cause.
- A requested GPU index, adapter inventory, and engine output are useful facts,
  but do not automatically prove thermals, frame pacing, or subsystem affinity.
- Synthetic input is not physical-controller certification.
- Movies and screenshots are not complete gameplay, accessibility, game-feel,
  or human art-direction approval.
- The Lab cannot repair or publish a target without a separate Development
  Studio grant and the target repository's own exclusive mainline lease.
