# Godot Game Test Lab

Godot Game Test Lab is EVAVO Studio's reusable build, runtime, sandbox,
interaction, visual, audio and QA worker for Godot repositories. The Lab lives
in its own repository and can inspect and exercise a game stored in a completely
separate Git repository.

It is designed for local ChatGPT, Claude, Development Studio workers, shell
agents and CI. It can provision the required Godot editor, detect project and
scene corruption, compile C# projects, import and boot the game, drive declared
keyboard, mouse and synthetic gamepad journeys, explore UI states, record video
and audio, and return retained evidence to an MCP-capable model.

The Lab does not receive authority to edit, commit, push, sign, deploy or publish
a target game. Target repair remains a separate, explicit Development Studio or
repository workflow.

## Execution lanes

The Lab intentionally separates three evidence lanes:

| Lane | Purpose | What it proves |
|---|---|---|
| Native Windows | Real editor, window, driver, GPU, audio and interactive desktop | Behaviour on Greg's actual Windows machine |
| Local or CI Linux sandbox | No-network, read-only, software-rendered compatibility QA | Reproducible import, build, input and rendered compatibility |
| Source-only CI | Python, policy, schemas, commands and packaging | The automation contract, not game execution |

A Linux Mesa/Xvfb pass is not a native Windows GPU pass. Synthetic controller
events verify Godot `InputMap` routing, not physical USB/Bluetooth enumeration,
Steam Input, latency or rumble.

## Core capabilities

- Finds exactly one `project.godot`, including explicit monorepo subpaths.
- Detects GDScript versus C# and selects Standard versus Godot .NET.
- Supports Godot 4.6.2 or newer through governed same-branch maintenance builds.
- Downloads official portable Godot archives and verifies release SHA-512 data.
- Installs matching export templates in a self-contained editor installation.
- Supports Windows x86-64/ARM64 and Linux x86-64/ARM64 managed host editors.
- Audits projects, scenes, resources, paths, Git, LFS and common binary assets.
- Runs authoritative editor import and recovery-mode differential diagnosis.
- Builds C# projects with `dotnet build` before trusting Godot import results.
- Performs bounded startup, export and Movie Maker recording.
- Drives target-owned keyboard, mouse, semantic-action and synthetic-gamepad QA.
- Builds deterministic UI state graphs and exact replay traces.
- Captures screenshots, checkpoints, contact sheets, movies and engine logs.
- Detects black or frozen video when the target policy enables those failures.
- Measures UI clipping, focus, overlaps, target sizes and bounded performance data.
- Analyses retained audio for stream presence, silence, loudness, clipping and drift.
- Returns bounded PNG and WAV evidence through an MCP server.
- Runs external repositories in a no-network, read-only Linux Docker sandbox.
- Preserves exact Lab and target SHAs in machine-readable evidence.

## Repository and evidence layout

The Lab, target games, managed engines and retained evidence remain separate:

```text
C:\GitRepos\godot-game-test-lab
C:\GitRepos\Brass_Brine
C:\GitRepos\another-game
%LOCALAPPDATA%\EVAVO\GodotGameTestLab\engines
C:\GodotLabEvidence\<game>\<run-id>
```

Linux defaults are:

```text
~/GitRepos/godot-game-test-lab
~/GitRepos/<game>
~/.cache/evavo/godot-game-test-lab/engines
~/.local/share/EVAVO/GodotLabEvidence/<game>/<run-id>
```

Evidence must remain outside both source checkouts. Exact-SHA native and sandbox
runs reject dirty Lab or target repositories. Git submodules currently fail
closed rather than being silently omitted from an exact source archive.

## Windows one-command setup

Run from a normal PowerShell terminal in Greg's logged-in Windows session:

```powershell
Set-Location C:\GitRepos\godot-game-test-lab

git pull --ff-only origin main

.\scripts\Install-GodotLab.ps1 `
  -PrepareEstate `
  -PrepareLinuxSandboxImages `
  -InstallPrerequisites `
  -RequireFullMediaToolchain
```

The installer creates a Python 3.11 virtual environment, installs the CLI and MCP
bridge, provisions both Standard and .NET Godot editors, installs matching export
templates, optionally installs .NET SDK 8 and FFmpeg/FFprobe with WinGet, scans
`C:\GitRepos`, tests the MCP bridge, and optionally builds governed Standard and
Mono Linux sandbox images through Docker Desktop.

Docker Desktop must already be installed and running with Linux containers when
`-PrepareLinuxSandboxImages` is used. The installer does not silently enable
privileged virtualization or Docker services.

Managed editors default to:

```text
%LOCALAPPDATA%\EVAVO\GodotGameTestLab\engines
```

The installer writes:

```text
C:\GodotLabEvidence\godot-lab-installation.json
C:\GodotLabEvidence\godot-lab-env.ps1
C:\GodotLabEvidence\godot-lab-mcp.json
```

## Linux one-command setup

```bash
cd "$HOME/GitRepos/godot-game-test-lab"
git pull --ff-only origin main

PREPARE_ESTATE=1 \
PREPARE_SANDBOX_IMAGES=1 \
./scripts/install-godot-lab.sh

source "$HOME/.local/share/EVAVO/GodotLabEvidence/godot-lab-env.sh"
```

`PREPARE_SANDBOX_IMAGES=1` requires a working Docker Engine. The native Linux
installer provisions portable Standard and .NET editors. The sandbox image also
contains .NET SDK 8, FFmpeg/FFprobe, Xvfb, Mesa llvmpipe and Vulkan software
drivers.

## Managed Godot engines

Godot binaries are not committed to Git. The governed engine lock is:

```text
src/godot_game_test_lab/godot-engine-lock.json
```

Current policy:

```text
Minimum accepted version: 4.6.2
Default 4.6 maintenance version: 4.6.3
Default 4.7 maintenance version: 4.7.1
Flavours: standard, mono
Export templates: installed by default
Mode: self-contained portable editor
```

Useful commands:

```powershell
godot-lab engine status
godot-lab engine install --version 4.6.3 --flavor standard
godot-lab engine ensure C:\GitRepos\SomeGame
godot-lab engine bootstrap --version 4.6.3 --flavors standard,mono
godot-lab engine prepare C:\GitRepos
godot-lab engine env --format powershell
godot-lab engine mirror D:\GodotOfflineMirror
```

`engine ensure` inspects the selected external project. A project on the 4.6
feature branch receives the governed 4.6 maintenance editor. A project containing
a `.csproj`, C# script or C# feature receives Godot .NET.

Each managed installation has an `_sc_` or `._sc_` marker, isolated `editor_data`,
a payload hash and `engine-installation.json` receipt. Corrupt archives,
checksum mismatches, traversal, links, special files, case/Unicode collisions,
altered payloads and inconsistent receipts fail closed.

## Inspect, audit and validate another repository

```powershell
$Game = "C:\GitRepos\Brass_Brine"
$Evidence = "C:\GodotLabEvidence\Brass_Brine\$(Get-Date -Format yyyyMMdd-HHmmss)"

New-Item -ItemType Directory -Force -Path $Evidence | Out-Null

godot-lab engine ensure $Game
godot-lab inspect $Game
godot-lab audit $Game --output "$Evidence\integrity-report.json"
godot-lab validate $Game --artifacts "$Evidence\validation"
```

Validation order:

1. bounded static integrity audit;
2. engine identity, version, flavour and CLI capability verification;
3. `.NET` identity and `dotnet build` for C# projects;
4. authoritative normal editor import;
5. recovery-mode import after a normal import failure;
6. bounded headless startup after clean import;
7. separate JSON, stdout, stderr and engine-log evidence.

Static findings are diagnostics. The matching Godot editor remains authoritative
for engine parsing and importing.

## Corruption and build diagnostics

The audit detects, among other failures:

- invalid UTF-8, NUL bytes and empty source files;
- unresolved merge markers and unmerged Git index entries;
- unmaterialised Git LFS pointers;
- missing main scenes, autoloads, plugins and resources;
- path traversal, symlink ambiguity and Windows portability collisions;
- malformed TSCN, TRES and ESCN descriptors;
- invalid, duplicated or unresolved external/internal resource IDs;
- missing, multiple or incorrectly ordered scene roots;
- invalid or duplicated Godot UIDs;
- invalid JSON, XML, TOML and export presets;
- empty or signature-invalid common image, audio, model, font and pack assets;
- C# compiler failures, GDScript parser errors and importer failures;
- normal-import failures isolated by recovery mode;
- runtime crashes, timeouts and error markers in engine logs.

## Local Linux sandbox

Check Docker readiness and cached governed images:

```powershell
godot-lab sandbox status
```

Build a checksum-verified image explicitly:

```powershell
godot-lab sandbox image `
  --lab-root C:\GitRepos\godot-game-test-lab `
  --version 4.6.3 `
  --flavor standard
```

Run a clean external repository:

```powershell
$Lab = "C:\GitRepos\godot-game-test-lab"
$Game = "C:\GitRepos\Brass_Brine"
$Evidence = "C:\GodotLabEvidence\Brass_Brine\linux-$(Get-Date -Format yyyyMMdd-HHmmss)"

godot-lab sandbox run $Game `
  --lab-root $Lab `
  --profile .evavo\godot-lab-linux.json `
  --artifacts $Evidence `
  --allowed-root C:\GitRepos `
  --expected-lab-sha (git -C $Lab rev-parse HEAD) `
  --expected-target-sha (git -C $Game rev-parse HEAD)
```

Convenience wrappers:

```text
scripts\Invoke-GodotLabLinuxSandbox.ps1
scripts/run-godot-lab-linux-sandbox.sh
```

The image build can access the network only to obtain official, manifest-verified
Godot assets and Ubuntu packages. The game run uses:

```text
--network none
--read-only
--cap-drop ALL
--security-opt no-new-privileges
```

It also applies CPU, RAM, swap, PID, file-descriptor, shared-memory, runtime and
artifact limits. The target and normalized profile are mounted read-only; only an
ephemeral work directory and the external evidence directory are writable.

## Native authored QA

A game owns a tracked profile, normally:

```text
<game>\.evavo\godot-lab-native.json
```

Run it with:

```powershell
.\scripts\Invoke-GodotLabNativeAgentQA.ps1 `
  -TargetRepositoryPath C:\GitRepos\Brass_Brine `
  -ProjectSubpath . `
  -ProfilePath .evavo\godot-lab-native.json `
  -ExpectedLabSha (git rev-parse HEAD) `
  -ExpectedTargetSha (git -C C:\GitRepos\Brass_Brine rev-parse HEAD) `
  -ArtifactPath C:\GodotLabEvidence\Brass_Brine\native-latest `
  -AllowedArtifactRoot C:\GodotLabEvidence `
  -PythonExecutable .\.venv\Scripts\python.exe
```

Native visible-desktop evidence requires Greg's logged-in Windows session. A
normal Windows service in Session 0 is rejected. Only one worker may hold the
native desktop lease at a time.

## Deterministic bot QA

Generate a strict starter profile inside a game:

```powershell
godot-lab-init-qa C:\GitRepos\Brass_Brine `
  --output .evavo\godot-lab-bot.json `
  --report .evavo\godot-lab-bot.discovery.json
```

Run bounded autonomous exploration:

```powershell
.\scripts\Invoke-GodotLabBotQA.ps1 `
  -TargetRepositoryPath C:\GitRepos\Brass_Brine `
  -ProjectSubpath . `
  -ProfilePath .evavo\godot-lab-bot.json `
  -ExpectedLabSha (git rev-parse HEAD) `
  -ExpectedTargetSha (git -C C:\GitRepos\Brass_Brine rev-parse HEAD) `
  -ArtifactPath C:\GodotLabEvidence\Brass_Brine\bot-latest `
  -AllowedArtifactRoot C:\GodotLabEvidence
```

The bot surveys controls and `InputMap`, filters denied/destructive candidates,
replays traces in fresh processes with isolated user data, captures transitions,
and retains deterministic state fingerprints and exact reproduction traces.

## MCP bridge for ChatGPT and Claude

The installers create an MCP configuration. On Windows it can be regenerated:

```powershell
.\scripts\Write-GodotLabMcpConfig.ps1 `
  -LabRoot C:\GitRepos\godot-game-test-lab `
  -AllowedTargetRoots C:\GitRepos `
  -EvidenceRoot C:\GodotLabEvidence `
  -EngineRoot "$env:LOCALAPPDATA\EVAVO\GodotGameTestLab\engines" `
  -PythonExecutable C:\GitRepos\godot-game-test-lab\.venv\Scripts\python.exe
```

The server supports local stdio and loopback Streamable HTTP. It exposes governed
tools such as:

```text
godot_capabilities
godot_doctor
godot_ensure_engine
godot_inspect
godot_audit
godot_validate
godot_propose_bot_profile
godot_run_bot_qa
godot_run_native_qa
godot_run_linux_sandbox
godot_analyze_run_media
godot_view_image
godot_hear_audio
```

`godot_view_image` returns retained PNG data and `godot_hear_audio` returns a
bounded WAV preview, allowing a capable model to assess evidence rather than only
receiving local filenames.

The MCP server is restricted to configured target, evidence and managed-engine
roots. It does not expose an arbitrary shell.

## Retained evidence

Depending on the lane, a run can retain:

```text
report.json
integrity-report.json
native-agent-summary.json
bot-agent-summary.json
local-sandbox-dispatch.json
local-sandbox-summary.json
run-context.json
source-archive.json
profile.normalized.json
hardware.json
engine logs
stdout and stderr logs
state graphs and exact traces
screenshots and checkpoints
contact sheets and gameplay movies
ffprobe.json
media-report.json
audio.wav and audio-preview.wav
waveform.png and spectrogram.png
```

Every authoritative run binds evidence to exact Lab and target SHAs and verifies
that the original target checkout remains unchanged.

## Offline engine mirror

Create a verified multi-platform mirror while online:

```powershell
godot-lab engine mirror D:\GodotOfflineMirror `
  --versions 4.6.3,4.7.1 `
  --platforms windows-x86_64,linux-x86_64 `
  --flavors standard,mono
```

Install from the matching release directory without network access:

```powershell
.\scripts\Install-GodotLab.ps1 `
  -OfflineSourceDir D:\GodotOfflineMirror\4.6.3-stable `
  -PrepareEstate
```

The local Docker image is independently cacheable. Once a governed image exists,
sandbox game execution remains no-network.

## Development validation

```powershell
python scripts/check_repository_toolchain.py
python scripts/test_repository_toolchain.py
python -m compileall -q src scripts tests
python -m ruff check src scripts tests
python -m pytest
python -m pip wheel --no-deps --wheel-dir dist .
```

Source validation proves the repository contract only. Native Godot, Windows
desktop, driver, GPU, target-game, visual and audio facts exist only after a real
worker run retains them.

## Truth boundaries

- A static audit does not replace matching-editor import.
- A bounded boot proves startup, not a complete playthrough.
- A screenshot or movie is evidence, not human art-direction approval.
- Synthetic input does not prove physical-device latency or certification.
- Software rendering does not prove native Vulkan/Direct3D performance.
- Requested GPU index and adapter logs do not by themselves prove frame pacing.
- CUDA is auxiliary compute capability, not Godot's rendering backend.
- Automated audio metrics do not replace human music, dialogue or mix judgment.
- A GitHub-only chat cannot control Greg's desktop; a local MCP or worker
  connection is required.
