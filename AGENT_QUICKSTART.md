# Agent Quickstart

Godot Game Test Lab gives a local ChatGPT, Claude, Development Studio worker, or
shell agent a governed Godot runtime for games stored in other repositories.
Godot editor archives are not committed to Git. The setup commands download the
official portable Windows or Linux release, verify it against the release's
`SHA512-SUMS.txt`, create a self-contained installation, install matching export
templates, and retain an installation receipt.

## Windows workstation

Run once from a normal PowerShell terminal in Greg's logged-in Windows session:

```powershell
Set-Location C:\GitRepos\godot-game-test-lab

git pull --ff-only origin main
.\scripts\Install-GodotLab.ps1 `
  -PrepareEstate `
  -PrepareLinuxSandboxImages `
  -InstallPrerequisites `
  -RequireFullMediaToolchain
```

The installer provisions Python, FFmpeg/FFprobe, .NET SDK 8, export templates,
both managed Godot flavours, and optional checksum-verified Standard and Mono
Linux sandbox images. Docker Desktop must already be running with Linux
containers when `-PrepareLinuxSandboxImages` is requested. The managed editors
themselves do not require administrator rights; WinGet may request elevation for
the system-wide .NET SDK.

The installer prepares both:

- the standard Godot editor for GDScript games;
- the Godot .NET editor for C# games.

By default it installs the governed Godot 4.6 maintenance release and matching
export templates under:

```text
%LOCALAPPDATA%\EVAVO\GodotGameTestLab\engines
```

It also creates a Python 3.11 environment, installs the optional MCP bridge,
checks the editor identities, writes environment and installation receipts to
`C:\GodotLabEvidence`, and can scan `C:\GitRepos` to prewarm every required
Godot branch and flavour.

## Linux workstation

```bash
cd "$HOME/GitRepos/godot-game-test-lab"
git pull --ff-only origin main
PREPARE_ESTATE=1 PREPARE_SANDBOX_IMAGES=1 ./scripts/install-godot-lab.sh
```

The isolated Linux sandbox image already embeds a checksum-verified Godot editor,
matching export templates, .NET SDK 8, FFmpeg/FFprobe, Xvfb, Mesa and Vulkan
software drivers. The native Linux installer creates the same portable managed
engine cache for shell and MCP agents.

## Connect an MCP-capable agent

The Windows installer writes an MCP configuration file. It can also be regenerated:

```powershell
.\scripts\Write-GodotLabMcpConfig.ps1 `
  -LabRoot C:\GitRepos\godot-game-test-lab `
  -AllowedTargetRoots C:\GitRepos `
  -EvidenceRoot C:\GodotLabEvidence `
  -EngineRoot "$env:LOCALAPPDATA\EVAVO\GodotGameTestLab\engines" `
  -PythonExecutable C:\GitRepos\godot-game-test-lab\.venv\Scripts\python.exe
```

The connected agent can then use tools such as:

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

`godot_ensure_engine` inspects the selected external project, detects its Godot
feature branch and whether it uses C#, and returns the verified executable that
will be used. Normal `validate`, `run`, `record`, `export`, bot-QA and native-QA
commands perform the same provisioning automatically.

## Test another repository

```powershell
$Game = "C:\GitRepos\Brass_Brine"
$Evidence = "C:\GodotLabEvidence\Brass_Brine\$(Get-Date -Format yyyyMMdd-HHmmss)"

godot-lab engine ensure $Game
godot-lab audit $Game --output "$Evidence\integrity-report.json"
godot-lab validate $Game --artifacts "$Evidence\validation"
```

The Lab can then run repository-owned mouse, keyboard, semantic-action and
synthetic-gamepad journeys, build a deterministic state graph, retain exact
replay traces, capture screenshots and movies, and analyse synchronized audio.
The target checkout is not copied into this repository and is not granted commit,
push, signing, deployment or publication authority.

## Run a clean external repository in the local Linux sandbox

```powershell
$Lab = "C:\GitRepos\godot-game-test-lab"
$Game = "C:\GitRepos\Brass_Brine"
$Evidence = "C:\GodotLabEvidence\Brass_Brine\linux-latest"

godot-lab sandbox status

godot-lab sandbox run $Game `
  --lab-root $Lab `
  --profile .evavo\godot-lab-linux.json `
  --artifacts $Evidence `
  --allowed-root C:\GitRepos `
  --expected-lab-sha (git -C $Lab rev-parse HEAD) `
  --expected-target-sha (git -C $Game rev-parse HEAD)
```

The image contains Godot, matching export templates, .NET SDK 8,
FFmpeg/FFprobe, Xvfb and Mesa. Game execution uses no network, a read-only root
filesystem, dropped Linux capabilities, a read-only target mount and bounded
CPU, memory, PIDs, files, time and evidence.

## Offline and repeatable hosts

Create a verified Windows and Linux mirror while online:

```powershell
godot-lab engine mirror C:\GodotLabOffline `
  --platforms windows-x86_64,linux-x86_64 `
  --flavors standard,mono
```

Bootstrap an offline host from that mirror:

```powershell
.\scripts\Install-GodotLab.ps1 `
  -OfflineSourceDir C:\GodotLabOffline\4.6.3-stable `
  -PrepareEstate
```

Every installation is content-hashed after extraction. Corrupt archives,
checksum mismatches, path traversal, symlinks, special files, case/Unicode path
collisions, altered installed payloads and unsupported future project branches
fail closed instead of being silently trusted.

## Evidence boundary

A source-only GitHub chat cannot control Greg's desktop. Native playtesting,
visual review, sound review and GPU evidence require the local MCP server or
Development Studio worker to run inside Greg's interactive Windows session.
Linux sandbox results remain compatibility evidence and do not prove native
Windows GPU performance or physical-controller behaviour.
