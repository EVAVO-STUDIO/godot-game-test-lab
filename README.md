# Godot Game Test Lab

Canonical native Godot build, runtime, evidence and QA worker for EVAVO Studio repositories.

Development Studio owns repository triage, policy, incident state and repair decisions. Godot Game Test Lab owns native Godot execution on freshly probed Windows runners and isolated Linux evidence workers. Godot Web Runtime owns browser-hosted loading, Playwright interaction, screenshots, traces and semantic gameplay observations.

## Current working surface

Version 0.3.0 provides:

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
- JSON reports and separate stdout/stderr evidence logs;
- an isolated Ubuntu 24.04 Linux sandbox with Xvfb and Mesa software rendering;
- a read-only target mount and ephemeral writable project copy;
- AVI, `ffprobe` and PNG contact-sheet visual evidence;
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

Run the canonical validation pipeline and retain evidence:

```powershell
godot-lab validate C:\GitRepos\Brass_Brine `
  --artifacts C:\GitRepos\Brass_Brine\.qa\latest
```

The validation order is:

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

## Isolated Linux agent runner

The canonical Docker-based Linux path is `scripts/Invoke-GodotLabLinuxSandbox.ps1` for a local Docker Desktop runner and `.github/workflows/evavo-linux-godot-sandbox.yml` for an exact-SHA GitHub-hosted run. The workflow supports both manual dispatch and reusable `workflow_call` execution from Development Studio, and a caller must pin the lab workflow by commit SHA.

Local example:

```powershell
$labSha = (git rev-parse HEAD).Trim()
$gameSha = (git -C C:\GitRepos\godot-462-retro-fps rev-parse HEAD).Trim()

.\scripts\Invoke-GodotLabLinuxSandbox.ps1 `
  -TargetRepositoryPath C:\GitRepos\godot-462-retro-fps `
  -ExpectedLabSha $labSha `
  -ExpectedTargetSha $gameSha `
  -ArtifactPath C:\GitRepos\godot-game-test-lab\artifacts\retro-fps-linux `
  -ProjectSubpath . `
  -EngineFlavor auto `
  -VisualFrames 180 `
  -ExportPreset "Linux Desktop"
```

The Linux worker:

- builds from the dated Ubuntu 24.04 base and verifies official Godot 4.6.2 editor/template archives with the release SHA-512 manifest;
- automatically selects standard Godot or the .NET editor from the target workload;
- installs .NET SDK 8 for C# compilation;
- mounts target source read-only and performs all imports/builds in an ephemeral copy;
- runs without network, capabilities or elevated privileges;
- performs import, bounded boot, Xvfb windowed rendering, Movie Maker capture and optional Linux export;
- emits `sandbox-report.json`, per-phase logs, `gameplay.avi`, `ffprobe.json` and `contact-sheet.png` when available;
- never receives a repository credential inside the container.

Private target repositories in the GitHub workflow require the repository-scoped read-only secret `EVAVO_GODOT_LAB_READ_TOKEN`. See `docs/LINUX_SANDBOX_CONTRACT.md`.

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
- has no checkout, reset, commit, push, branch, pull-request, deployment or repository-reset operation for the target game.

Runner provisioning and local parity are defined in `docs/NATIVE_RUNNER_CONTRACT.md`.

Development Studio prepares the intended target checkout and supplies the same exact target SHA. The lab verifies that revision but never chooses or updates it.

## Truth boundaries

- A passing headless import is not proof of game feel or visual quality.
- A bounded boot proves startup only; it does not prove complete gameplay.
- A recorded movie or Linux contact sheet is visual evidence, not an interactive playthrough.
- Xvfb with Mesa software rendering does not prove hardware-specific Vulkan behavior or performance.
- Browser interaction should use Godot Web Runtime when the project supports a GDScript Compatibility-renderer web export.
- Godot 4 C# projects cannot use the browser-export path and must be tested natively.
- Export commands require valid project export presets and installed export templates.
- The lab never edits tracked game source, creates a branch, commits, pushes or deploys by itself. Development Studio grants and records those effects.

## Development checks

```powershell
python -m compileall src tests
python -m ruff check src tests
python -m pytest
```

The 0.3.0 source tests validate the Linux sandbox path, source-copy isolation and policy markers without claiming a real Godot or Docker run. Actual import, boot, visual and export evidence exists only after the corresponding exact-SHA workflow or local Docker command completes.

## Mainline policy

Automated work is committed directly to `main` only after tests pass. No automated feature or repair branches are created. Force-push is forbidden. See `AGENTS.md`, `CLAUDE.md` and `evavo.reliability.json`.
