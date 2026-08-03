# Windows agent host initialization and acceptance

Godot Game Test Lab can only let ChatGPT, Claude, or Development Studio genuinely
open, play, see, and hear a native Godot game after the local worker is installed
inside Greg's logged-in Windows session. Repository access alone cannot cross that
machine boundary.

The host workflow is intentionally split into two scripts:

```text
scripts/Initialize-GodotLabAgentHost.ps1
scripts/Test-GodotLabAgentHost.ps1
```

`Initialize-GodotLabAgentHost.ps1` is the one-command installer and registrar.
It calls the governed installer, provisions the managed Standard and .NET Godot
editors, installs the optional MCP bridge, registers the loopback worker as an
interactive at-logon scheduled task, starts it, and runs acceptance.

`Test-GodotLabAgentHost.ps1` is the repeatable acceptance check. It does not
install software unless `-RegisterWorker` is explicitly requested. It writes a
bounded machine-readable receipt outside all source repositories. Its
`worker-protocol-acceptance` stage is mandatory; neither host entrypoint exposes
a switch that can bypass the live protocol proof.

## One-command workstation setup

Run from a normal PowerShell terminal in Greg's logged-in desktop session:

```powershell
Set-Location C:\GitRepos\godot-game-test-lab

git pull --ff-only origin main

.\scripts\Initialize-GodotLabAgentHost.ps1 `
  -PrepareEstate `
  -PrepareLinuxSandboxImages `
  -InstallPrerequisites:$true `
  -RequireFullMediaToolchain
```

This path:

1. creates the Python 3.11 environment;
2. installs the Lab and `mcp==1.28.1` bridge;
3. provisions checksum-verified Godot Standard and .NET editors;
4. installs matching export templates;
5. checks .NET 8, FFmpeg, and FFprobe;
6. can prewarm every Godot project beneath `C:\GitRepos`;
7. can build governed Standard and Mono Linux sandbox images;
8. registers the loopback-only MCP worker at logon;
9. starts the worker in the current interactive session;
10. initializes a real Streamable HTTP MCP session, lists tools, matches the exact
    roots and provisioning policy, and verifies managed engines, doctor, hardware
    inventory, and the MCP self-test;
11. writes an acceptance receipt under
    `C:\GodotLabEvidence\host-acceptance\<run-id>`.

Docker Desktop must already be installed and running in Linux-container mode when
`-PrepareLinuxSandboxImages` is used. The initializer never silently installs,
starts, or elevates Docker.

## Accept one real game repository

A validation-only workstation acceptance can include a clean external game:

```powershell
$Lab = "C:\GitRepos\godot-game-test-lab"
$Game = "C:\GitRepos\Brass_Brine"

Set-Location $Lab

.\scripts\Test-GodotLabAgentHost.ps1 `
  -ExpectedLabSha (git -C $Lab rev-parse HEAD) `
  -AcceptanceRepositoryPath $Game `
  -ExpectedTargetSha (git -C $Game rev-parse HEAD) `
  -ProjectSubpath "." `
  -AcceptanceMode validate `
  -RegisterWorker `
  -StartWorker
```

The target repository must be completely clean. Validation executes through a
separate run directory under `C:\GodotLabEvidence`; the target checkout is not
used as an evidence directory and must have the same SHA and status afterward.

## Native authored journey acceptance

Use a tracked native profile to prove a real visible Windows journey:

```powershell
.\scripts\Test-GodotLabAgentHost.ps1 `
  -AcceptanceRepositoryPath C:\GitRepos\Brass_Brine `
  -ExpectedTargetSha (git -C C:\GitRepos\Brass_Brine rev-parse HEAD) `
  -ProjectSubpath "." `
  -AcceptanceMode native `
  -NativeProfilePath ".evavo\godot-lab-native.json" `
  -RegisterWorker `
  -StartWorker
```

This lane requires Explorer in the same nonzero Windows session as the worker.
It can retain checkpoints, screenshots, Godot Movie Maker video, synchronized
audio, engine logs, UI telemetry, renderer and driver requests, and bounded
performance samples.

## Autonomous bot acceptance

Use the tracked bot profile for bounded deterministic exploration:

```powershell
.\scripts\Test-GodotLabAgentHost.ps1 `
  -AcceptanceRepositoryPath C:\GitRepos\Brass_Brine `
  -ExpectedTargetSha (git -C C:\GitRepos\Brass_Brine rev-parse HEAD) `
  -ProjectSubpath "." `
  -AcceptanceMode bot `
  -BotProfilePath ".evavo\godot-lab-bot.json" `
  -RegisterWorker `
  -StartWorker
```

Use `-AcceptanceMode all` with both profile paths to run validation, authored
journeys, and bot exploration in one evidence bundle.

## Acceptance receipt

`host-acceptance.json` records:

- exact Lab and target SHAs;
- canonical Lab, target, engine, and evidence roots;
- Windows user and interactive session identity;
- Explorer session evidence;
- Standard and .NET managed-engine readiness;
- doctor and MCP self-test results;
- scheduled-task state and protocol-bound worker identity, roots, policy, and tools;
- Windows, video-controller, sound-device, and optional NVIDIA evidence;
- target validation, authored journey, and bot stages when requested;
- exact per-stage status, duration, and retained evidence paths.

The receipt does not contain environment-variable values, credentials, private
keys, raw user data, or arbitrary command output from the target.

## Security boundaries

The host acceptance path fails closed when:

- the Lab or target SHA does not match;
- tracked Lab files changed;
- the target checkout is not completely clean;
- a root traverses a reparse point;
- evidence or engine storage overlaps source repositories;
- the project subpath escapes the target Git root;
- the worker runs in Session 0 or without Explorer in the same session;
- Standard or .NET Godot is not ready;
- the MCP self-test or live protocol worker probe fails;
- the required scheduled task is absent;
- a target run changes or obscures the target repository.

The worker binds to `127.0.0.1` only. It does not expose arbitrary shell
execution and does not gain authority to edit, commit, push, release, deploy, or
sign a target game.

## Truth boundaries

A passing host receipt proves that the local worker, managed tools, loopback MCP
surface, and requested bounded journeys worked on that machine at the recorded
SHAs. It does not prove every game state, every physical controller, long-session
stability, accessibility, art direction, game feel, thermals, or final audio mix.
Those require the matching dedicated evidence lane and human review.
