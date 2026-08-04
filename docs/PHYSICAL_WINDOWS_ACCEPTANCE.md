# Physical Windows acceptance

`Invoke-GodotLabPhysicalAcceptance.ps1` is the canonical operator command for
the first complete machine-level acceptance on Greg's logged-in Windows desktop.
It derives the exact Lab and target SHAs, creates a strict external estate
manifest, and delegates to the governed host and estate commands.

The command requires two different clean Git repositories:

- one pure GDScript project for exact validation;
- one C# project for exact validation, a real visible native journey, and a
  deterministic bot campaign.

This fixed first-run shape satisfies the aggregate requirement for both Godot
project families and both gameplay-evidence lanes without hand-authoring JSON.

## Prerequisites

The target repositories must already contain reviewed, tracked profiles in the
C# repository, for example:

```text
.evavo/godot-lab-native.json
.evavo/godot-lab-bot.json
```

Both repositories and the Test Lab must be completely clean, including untracked
files. `repositoryPath` values must identify each Git top-level directory.
Evidence and managed-engine roots must remain outside the Lab and every allowed
target root.

Docker Desktop is optional. It must already be running in Linux-container mode
only when `-PrepareLinuxSandboxImages` is requested.

## One-command setup and acceptance

Run from a normal PowerShell terminal in Greg's logged-in desktop session:

```powershell
Set-Location C:\GitRepos\godot-game-test-lab
git pull --ff-only origin main

.\scripts\Invoke-GodotLabPhysicalAcceptance.ps1 `
  -GdscriptRepositoryPath "C:\GitRepos\epochbound" `
  -CSharpRepositoryPath "C:\GitRepos\Brass_Brine" `
  -NativeProfilePath ".evavo\godot-lab-native.json" `
  -BotProfilePath ".evavo\godot-lab-bot.json" `
  -AllowedTargetRoots @("C:\GitRepos") `
  -ExpectedLabSha (git rev-parse HEAD) `
  -InitializeHost
```

When `-InitializeHost` is present, the initializer installs the governed host,
registers and starts the scheduled MCP worker, and completes live protocol
acceptance once. The physical operator then reuses that same scheduled worker
for the estate. It deliberately does not stop, replace, or start it again before
the first target. This removes a redundant worker restart between successful
host acceptance and target execution.

Without `-InitializeHost`, `-RegisterWorker` and `-StartWorker` control the first
estate target. Set either Boolean explicitly to `$false` when reusing an already
prepared host through the lower-level path.

Add `-PrepareLinuxSandboxImages` only when Docker Desktop is ready. Add
`-EngineOffline` only after the governed Standard and .NET editors, templates,
.NET SDK and media tools have already been provisioned.

For repositories beneath more than one estate root:

```powershell
.\scripts\Invoke-GodotLabPhysicalAcceptance.ps1 `
  -GdscriptRepositoryPath "D:\GodotProjects\epochbound" `
  -CSharpRepositoryPath "C:\GitRepos\Brass_Brine" `
  -NativeProfilePath ".evavo\godot-lab-native.json" `
  -BotProfilePath ".evavo\godot-lab-bot.json" `
  -AllowedTargetRoots @("C:\GitRepos", "D:\GodotProjects") `
  -ExpectedLabSha (git rev-parse HEAD) `
  -InitializeHost
```

The installer now validates the Lab, every allowed target root, the evidence
root, and the managed-engine root before it creates either managed directory.
All allowed roots are carried into the environment file, MCP configuration,
worker registration, protocol acceptance, and estate preparation. When
`-PrepareEstate` is active, each root receives its own retained preparation
report rather than only the first root being scanned.

`-EngineOffline` is also propagated into managed-editor bootstrap, every estate
preparation command, the generated MCP configuration, and the scheduled worker's
no-auto-provision policy. It controls managed-engine network access; prerequisite
package installation should already be complete when a fully disconnected run is
required.

The wrapper creates one create-only manifest beneath:

```text
C:\GodotLabEvidence\estate-manifests\
```

Its two targets are intentionally fixed to:

```text
gdscript-game  expectedProjectKind=gdscript  acceptanceMode=validate
csharp-game    expectedProjectKind=csharp    acceptanceMode=all
```

The C# target owns both tracked profile paths. The underlying estate preflight
rechecks exact project kinds, canonical project subpaths, profile tracking,
profile SHA-256 identities, target SHAs and complete source cleanliness after the
Global machine lease has been acquired.

## Expected evidence

A successful run retains at least:

```text
estate-acceptance.json schema 1.3
host-acceptance.json schema 1.1 for each target
mcp-worker-acceptance.json for each target
native-validation-receipt.json
native-agent-summary.json
bot-agent-summary.json
hardware.json
screenshots and checkpoints
gameplay movies and synchronized audio
waveform and spectrogram evidence
state graphs and exact replay traces
final Lab and target sourceChecks
```

Every target independently proves the live MCP worker through protocol
initialization, tool listing and exact capability roots. The aggregate receipt
uses deterministic target-owned `HostRunRoot` paths and does not discover
receipts by scanning a shared tree.

## Completion boundary

A green GitHub source run cannot complete this command. The authoritative run
requires Greg's actual non-Session-0 Windows desktop, Explorer in the same
session, installed GPU and sound drivers, real clean game checkouts, and the
local scheduled MCP worker.

Synthetic gamepad input proves Godot event routing and InputMap handling; it does
not certify physical USB or Bluetooth enumeration, Steam Input, rumble or device
latency. Automated media evidence does not replace human game-feel,
accessibility, art-direction or final-mix approval.
