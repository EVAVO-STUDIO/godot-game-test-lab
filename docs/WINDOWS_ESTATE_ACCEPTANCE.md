# Windows game-estate acceptance

`Invoke-GodotLabEstateAcceptance.ps1` performs the final source-preserving acceptance across multiple real Godot repositories on one logged-in Windows desktop. It is intentionally stricter than running an individual target: the manifest must include at least one pure GDScript project, at least one C# project, at least one native visible journey, and at least one deterministic bot journey.

The command verifies exact Lab and target SHAs, complete tracked and untracked cleanliness, allowed-root confinement, project type, target-owned journey profiles, MCP worker protocol identity, managed Standard and .NET editors, native validation, retained media, and post-run mutation state. It writes one aggregate `estate-acceptance.json` plus the individual `host-acceptance.json`, `mcp-worker-acceptance.json`, validation, native, bot, image, movie, audio, state-graph, and trace evidence beneath the external evidence root.

## Prerequisite

Initialize the governed host from the normal logged-in desktop session first:

```powershell
Set-Location C:\GitRepos\godot-game-test-lab
git pull --ff-only origin main

.\scripts\Initialize-GodotLabAgentHost.ps1 `
  -PrepareEstate `
  -PrepareLinuxSandboxImages `
  -InstallPrerequisites:$true `
  -RequireFullMediaToolchain
```

Docker Desktop must already be running in Linux-container mode when sandbox images are requested.

## Manifest

Save a target-owned manifest outside the Lab and game repositories, for example `C:\GodotLabEvidence\estate-manifest.json`. Every target must declare all fields. Profile paths are repository-relative and must remain inside that target checkout. Use an empty string for a profile that is not used by the selected mode.

```json
{
  "schemaVersion": "1.0",
  "targets": [
    {
      "id": "gdscript-game",
      "repositoryPath": "C:\\GitRepos\\epochbound",
      "expectedSha": "1111111111111111111111111111111111111111",
      "projectSubpath": ".",
      "expectedProjectKind": "gdscript",
      "acceptanceMode": "validate",
      "nativeProfilePath": "",
      "botProfilePath": ""
    },
    {
      "id": "csharp-game",
      "repositoryPath": "C:\\GitRepos\\Brass_Brine",
      "expectedSha": "2222222222222222222222222222222222222222",
      "projectSubpath": ".",
      "expectedProjectKind": "csharp",
      "acceptanceMode": "all",
      "nativeProfilePath": "qa\\windows-native.json",
      "botProfilePath": "qa\\deterministic-bot.json"
    }
  ]
}
```

Replace the example SHAs with the exact output of `git -C <repository> rev-parse HEAD`. A GDScript target must have tracked `.gd` files and no tracked `.csproj`; a C# target must have tracked `.csproj` and `.cs` files. At least one target must use `native` or `all`, and at least one must use `bot` or `all`.

## Run

```powershell
.\scripts\Invoke-GodotLabEstateAcceptance.ps1 `
  -ManifestPath "C:\GodotLabEvidence\estate-manifest.json" `
  -AllowedTargetRoots @("C:\GitRepos") `
  -ExpectedLabSha (git rev-parse HEAD)
```

To register and start the scheduled loopback worker as part of the first target:

```powershell
.\scripts\Invoke-GodotLabEstateAcceptance.ps1 `
  -ManifestPath "C:\GodotLabEvidence\estate-manifest.json" `
  -AllowedTargetRoots @("C:\GitRepos", "D:\GodotProjects") `
  -ExpectedLabSha (git rev-parse HEAD) `
  -RegisterWorker `
  -StartWorker
```

After managed editors and templates are already cached, add `-EngineOffline` to prove that worker and host acceptance preserve the no-download policy.

The first target always performs the real MCP protocol probe. Later targets may reuse that accepted worker in the same aggregate run, but each target still receives its own full host, toolchain, engine, hardware, validation, journey, media, and source-mutation receipt.

## Acceptance boundary

This workflow proves the actual Windows session, installed GPU and sound-device inventory, exact game checkouts, Godot input routing, recorded evidence, and the accepted local MCP worker. Synthetic gamepad input is not physical controller enumeration, Steam Input, rumble, or latency certification. Automated media analysis is not human game-feel, accessibility, art-direction, or final mix approval.
