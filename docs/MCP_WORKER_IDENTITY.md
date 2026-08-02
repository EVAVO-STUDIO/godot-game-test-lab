# MCP worker identity and multi-root registration

The Windows MCP worker is a local execution boundary for ChatGPT, Claude, and
Development Studio. A listening TCP port is not sufficient proof that the
expected Godot Game Test Lab process is running. Another process could already
own the port, or a stale scheduled task could still be serving an older Lab
checkout or different target roots.

The governed worker path therefore uses three separate records:

```text
godot-lab-mcp-worker-config.json
godot-lab-mcp-worker.json
mcp-worker-acceptance.json
```

## Registration

Register and start one loopback-only worker:

```powershell
$Lab = "C:\GitRepos\godot-game-test-lab"

Set-Location $Lab

.\scripts\Register-GodotLabMcpWorker.ps1 `
  -LabRoot $Lab `
  -AllowedTargetRoots @(
    "C:\GitRepos",
    "D:\GodotProjects"
  ) `
  -EvidenceRoot "C:\GodotLabEvidence" `
  -EngineRoot "$env:LOCALAPPDATA\EVAVO\GodotGameTestLab\engines" `
  -TaskName "EVAVO Godot Game Test Lab MCP" `
  -Port 8765 `
  -StartNow
```

`-TargetRoot` remains an alias for `-AllowedTargetRoots` so existing
single-root commands continue to work.

Registration:

1. requires an exact clean Lab checkout;
2. rejects reparse-point traversal;
3. canonicalizes and deduplicates all allowed target roots;
4. keeps Lab, target, evidence, and engine roots disjoint;
5. stops the previous managed task before replacement;
6. refuses to continue if the loopback port remains occupied;
7. writes an atomic schema-2 worker configuration;
8. binds that configuration to the exact Lab SHA;
9. records the configuration SHA-256;
10. registers a limited interactive at-logon task.

The scheduled task receives only the configuration path. Target roots are not
lossily flattened into an ad hoc command-line string.

## Protocol acceptance

Prove the running server through the MCP protocol:

```powershell
.\scripts\Test-GodotLabMcpWorker.ps1 `
  -LabRoot $Lab `
  -AllowedTargetRoots @(
    "C:\GitRepos",
    "D:\GodotProjects"
  ) `
  -EvidenceRoot "C:\GodotLabEvidence" `
  -EngineRoot "$env:LOCALAPPDATA\EVAVO\GodotGameTestLab\engines" `
  -ExpectedLabSha (git -C $Lab rev-parse HEAD) `
  -TaskName "EVAVO Godot Game Test Lab MCP" `
  -Port 8765 `
  -RequireScheduledTask
```

The PowerShell acceptance script invokes:

```text
python -m godot_game_test_lab.mcp_probe
```

The probe uses the official MCP Streamable HTTP client. It initializes a real
MCP session, lists tools, calls `godot_capabilities`, and requires the returned
identity to match:

- bridge name `evavo-godot-lab-agent`;
- exact Lab root;
- exact allowed target-root set;
- exact evidence root;
- exact managed-engine root;
- interactive-desktop policy;
- managed-engine auto-provisioning policy;
- required inspection, audit, validation, native, bot, sandbox, media, image,
  and audio tools.

A bare TCP listener, HTTP status code, or scheduled-task state cannot satisfy
this acceptance.

## Offline workers

A worker that must never provision another editor from the network can be
registered with:

```powershell
.\scripts\Register-GodotLabMcpWorker.ps1 `
  -AllowedTargetRoots @("C:\GitRepos") `
  -EngineOffline `
  -StartNow
```

Probe it with the same `-EngineOffline` switch. The accepted capability record
must report `autoProvisionEngines: false`.

The managed editors must already exist in the configured engine root. Offline
mode does not disable game-network access by itself; individual native and
sandbox QA lanes retain their own network and external-service policies.

## One-command host initialization

`Initialize-GodotLabAgentHost.ps1` now performs registration and MCP protocol
acceptance before running the broader engine, hardware, and optional real-game
acceptance:

```powershell
.\scripts\Initialize-GodotLabAgentHost.ps1 `
  -TargetRoot "C:\GitRepos" `
  -AdditionalTargetRoots @("D:\GodotProjects") `
  -PrepareEstate `
  -InstallPrerequisites:$true `
  -RequireFullMediaToolchain
```

The primary `TargetRoot` is used for estate prewarming. Every primary and
additional root is passed to the MCP worker and its protocol acceptance.

## Truth boundary

A successful probe proves the process answering on the loopback endpoint is an
MCP server exposing the expected Godot Lab identity and configured roots at that
moment. It does not prove a game has run, rendered correctly, produced correct
audio, or passed a human review. Those claims require retained validation,
native journey, bot, visual, and media evidence from the target game.
