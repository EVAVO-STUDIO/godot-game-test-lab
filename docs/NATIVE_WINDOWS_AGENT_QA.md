# Native Windows Agent QA

The native worker runs a Godot game from any exact Git checkout on Greg's logged-in Windows desktop. The test lab and game can remain in separate repositories. The game repository owns its journey profile; the lab owns execution, evidence and truth boundaries.

## Why this lane exists

Headless import, bounded boot and Linux Xvfb/Mesa runs are useful compatibility evidence, but they do not prove the real Windows display session, graphics driver, selected GPU, window focus or native presentation. This lane adds those native facts while preserving exact-SHA and read-only target-source guarantees.

A normal Windows service runs in Session 0 and cannot be treated as visible-desktop evidence. Run the self-hosted runner or local worker in the logged-in user session. The worker fails closed when an interactive desktop is required but unavailable.

## Install

```powershell
Set-Location C:\GitRepos\godot-game-test-lab

git pull --ff-only origin main
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --disable-pip-version-check ".[dev]"

godot-lab doctor
```

Install the standard and .NET Godot editors when both GDScript and C# games are present. Install FFmpeg and FFprobe for screenshots, contact sheets and media metadata. `nvidia-smi`, `vulkaninfo` and `nvcc` are optional diagnostic probes, not proof of the rendered adapter.

## Target-owned profile

Copy `examples/native-agent-qa.profile.json` into the game, normally as:

```text
<game>/.evavo/godot-lab-native.json
```

Commit the profile. Every native run binds it to the exact target SHA. Schema: `schemas/native-agent-qa-profile.schema.json`.

Journeys use the same Godot `InputEvent` harness as the governed Linux lane. Supported steps include waits, InputMap actions, physical key codes, mouse motion/buttons, synthetic joypad buttons/axes and checkpoints. Synthetic joypad events prove event routing and state assertions only; they do not certify a physical controller.

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
    -WindowPosition "32,32"
```

For a monorepository, `TargetRepositoryPath` is the Git root and `ProjectSubpath` selects the directory containing `project.godot`.

## Automation sequence

The worker performs this sequence:

1. Validate exact lab and target SHAs.
2. Require the journey profile to be tracked by the target commit.
3. Require evidence beneath an explicitly allowed root and outside both source checkouts.
4. Capture the target Git state.
5. Create a bounded, link-free `git archive` working copy.
6. Run static integrity, C# build where required, authoritative import, recovery diagnosis and bounded boot.
7. Verify Godot visual command capabilities from `--help`.
8. Capture Windows session, adapter, NVIDIA, Vulkan and CUDA-adjacent diagnostics.
9. Run each required journey using native Godot Movie Maker and the repository-authored input harness.
10. Extract FFprobe metadata, screenshots and a contact sheet.
11. Hash retained evidence and confirm that the target checkout did not change.

A requested scene is loaded by the journey harness. Direct `godot-lab run` and `record` scene selectors are centrally converted to Godot's positional scene argument before process execution. The lab never passes an invented `--scene` engine option.

## Evidence

```text
<native-run>/
  native-agent-summary.json
  hardware.json
  profile.normalized.json
  validation/
    report.json
    integrity-report.json
    engine-logs/
  journeys/<id>/
    journey.normalized.json
    journey-report.json
    gameplay.avi
    ffprobe.json
    contact-sheet.png
    screenshots/
    checkpoints/
  logs/
```

The summary records exact SHAs, profile hash, project subpath, validation state, journey commands, requested renderer/driver/GPU index, process results, findings, evidence hashes and target mutation state.

## Truth boundaries

- A static audit is diagnostic; matching-editor import is authoritative for engine parsing/import.
- Recovery success isolates a disabled import-time surface but does not identify the root cause by itself.
- Requested GPU index plus adapter logs is stronger evidence than a generic probe, but the retained Godot log and rendered journey remain the primary facts.
- CUDA is optional auxiliary compute capability. Godot renders through its selected rendering and display drivers.
- Synthetic input is not physical-controller certification.
- Screenshots and movies are not complete gameplay, accessibility, game-feel or human art-direction approval.
- The lab does not edit, commit, push, deploy, sign or publish the target game.
