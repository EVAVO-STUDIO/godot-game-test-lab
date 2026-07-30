# Godot Game Test Lab

Canonical native Godot build, runtime, evidence and QA worker for EVAVO Studio repositories.

Development Studio owns repository triage, policy, incident state and repair decisions. Godot Game Test Lab owns native Godot execution on a freshly probed Windows runner. Godot Web Runtime owns browser-hosted loading, Playwright interaction, screenshots, traces and semantic gameplay observations.

## Current working surface

Version 0.2.0 provides:

- project discovery and inventory;
- GDScript versus C# workload detection;
- standard Godot versus Godot Mono selection;
- minimum Godot version enforcement, defaulting to 4.6.2;
- `.NET` discovery and `dotnet build` for C# projects;
- headless Godot import and parser evidence;
- bounded headless boot evidence;
- bounded native windowed or headless runs;
- command-line debug and release export;
- deterministic Movie Maker recording with fixed FPS and bounded frames;
- JSON reports and separate stdout/stderr evidence logs;
- dependency-free runtime code with pytest and Ruff development gates.

## Installation

```powershell
Set-Location C:\GitRepos\godot-game-test-lab
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
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
3. Godot Mono requirement for C# projects;
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

## Exact-SHA native automation

The repository now includes `.github/workflows/evavo-native-godot-validation.yml` for approved self-hosted Windows validation.

The workflow:

- runs only through manual `workflow_dispatch`;
- requires an exact test-lab `main` SHA;
- requires `request_source=evavo-development-studio`;
- accepts only target paths beneath `C:\GitRepos`;
- uses runner labels `self-hosted`, `Windows`, `X64`, and `evavo-godot-lab`;
- prepares an isolated Python 3.11 environment;
- runs compile, Ruff, pytest, doctor and the canonical Godot validation pipeline;
- compares tracked target-repository status before and after execution;
- fails if validation changes any tracked game source;
- uploads bounded evidence for 14 days;
- has no commit, push, branch, pull-request, deployment or repository-reset operation.

Runner provisioning and local parity are defined in `docs/NATIVE_RUNNER_CONTRACT.md`.

A native run also requires Development Studio to record the exact target game SHA separately. The lab validates the selected working tree but never chooses or updates a game revision itself.

## Truth boundaries

- A passing headless import is not proof of game feel or visual quality.
- A bounded boot proves startup only; it does not prove complete gameplay.
- A recorded movie is visual evidence, not an interactive playthrough.
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

The initial 0.2.0 pipeline and CLI tests were executed against Python 3.13 in a clean fixture environment: four tests passed. A real Godot 4.6.2 Windows runner is still required for native tool, import, boot, export and movie evidence.

## Mainline policy

Automated work is committed directly to `main` only after tests pass. No automated feature or repair branches are created. Force-push is forbidden. See `AGENTS.md`, `CLAUDE.md` and `evavo.reliability.json`.
