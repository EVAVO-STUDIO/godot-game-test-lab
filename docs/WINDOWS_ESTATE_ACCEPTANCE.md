# Windows game-estate acceptance

`Invoke-GodotLabEstateAcceptance.ps1` performs the final source-preserving
acceptance across multiple real Godot repositories on one logged-in Windows
desktop. It is intentionally stricter than running an individual target: the
manifest must include at least one pure GDScript project, at least one C#
project, at least one native visible journey, and at least one deterministic bot
journey.

The command verifies exact Lab and target SHAs, complete tracked and untracked
cleanliness, allowed-root confinement, project type, target-owned journey
profiles, MCP worker protocol identity, managed Standard and .NET editors,
native validation, retained media, and post-run mutation state. Every target
performs a live MCP protocol probe. Host receipts are admitted only as
target-bound evidence when their nested validation and journey summaries bind
the exact target SHA and project. It writes one aggregate
`estate-acceptance.json` plus the individual `host-acceptance.json`,
`mcp-worker-acceptance.json`, validation, native, bot, image, movie, audio,
state-graph, and trace evidence beneath the external evidence root.

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

Docker Desktop must already be running in Linux-container mode when sandbox
images are requested.

## Manifest

Save the manifest outside the Lab and every game repository, for example
`C:\GodotLabEvidence\estate-manifest.json`. The manifest is bounded to 1 MiB,
must be strict UTF-8 without a BOM, must contain no duplicate JSON property
names, and must contain exactly `schemaVersion` and `targets`. Every target must
declare exactly the documented fields.

Profile paths must be tracked repository-relative files. Absolute paths,
traversal, untracked profiles, extra target fields, ambiguous project paths and
noncanonical project subpaths fail before any target process starts. Manifest
objects, arrays, strings, booleans and integers must also use their exact JSON
types. Authority-bearing values are not converted from strings, numbers or other
truthy PowerShell values.

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

Replace the example SHAs with the exact output of
`git -C <repository> rev-parse HEAD`. A pure GDScript target must have tracked
`.gd` files and no tracked `.csproj` or `.cs` files. A C# target must have
tracked `.csproj` and `.cs` files. At least one target must use `native` or
`all`, and at least one must use `bot` or `all`.

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

After managed editors and templates are already cached, add `-EngineOffline` to
prove that worker and host acceptance preserve the no-download policy.

## Evidence admission and finalization

Every target performs the real MCP protocol probe and receives its own full
host, toolchain, engine, hardware, validation, journey, media, and
source-mutation receipt. Each retained JSON evidence file is read through one
stable open file descriptor. The parser compares the path identity with the
opened descriptor before and after the bounded read, rejects replacement or
size/metadata drift, then parses and SHA-256 hashes those exact admitted bytes.
Duplicate names, invalid UTF-8, BOMs, negative zero, non-finite numbers,
excessive nesting, symbolic links and oversized evidence fail closed.

Receipt admission requires exact JSON types before any comparison. In
particular, strings such as `"false"` cannot satisfy boolean fields, numeric
strings cannot satisfy integer fields, arrays cannot substitute for objects, and
closed authority records reject missing or additional properties. This applies
to the host, worker, native validation, source-check and authority-bearing native
and bot summary fields.

The aggregate runner uses
`Global\EVAVO.GodotLab.EstateAcceptance`, a machine-wide Windows named mutex, so
separate interactive sessions cannot run competing estate admissions. The
machine-wide lease is acquired before manifest and target preflight, and remains
held through target execution, evidence admission, final source verification and
aggregate receipt publication. The first target may register or start the
worker; every target must independently prove the same complete worker roots,
interactive policy, engine policy and required MCP tool set.

Each manifest target receives one explicit target-owned host run root:

```text
estate-acceptance/<stamp>/targets/<ordinal>-<target-id>-<sha-prefix>/host
```

The directory component combines the target ordinal, stable target ID and the
first 12 characters of the exact target SHA. This avoids Windows device-name and
trailing-dot collisions while remaining deterministic and reviewable. The estate
runner passes the resulting absolute non-existing path through `HostRunRoot`.

The host command requires its parent to exist, requires the path to remain
strictly beneath `EvidenceRoot`, rejects reparse points and existing paths, and
creates the run directory and receipts without overwrite. Aggregate admission
therefore reads the one exact `host-acceptance.json` path it assigned; it does
not scan the shared host receipt tree or infer ownership from timestamps.

Each `host-acceptance.json` schema 1.1 receipt contains final Lab and target
`sourceChecks`. A passing host receipt must prove both repositories still have
the exact expected SHA and an empty complete Git status after worker, validation,
native and bot work. These checks run on every host exit path before the receipt
is written.

Host, worker, validation, native and bot evidence is admitted only when exact
Lab, repository, target SHA, `projectSubpath`, profile SHA-256, stage set,
interactive desktop state, source-mutation state and required journey/campaign
outcomes agree. Unrelated standalone host receipts cannot enter the target's
admission path.

`estate-acceptance.json` schema 1.3 records:

- `hostReceiptPolicy: explicit-target-root-v1`;
- `strictJsonProfile: bounded-utf8-unique-names-stable-file-v2`;
- `receiptTypePolicy: closed-authority-types-v1`;
- `preflightLeasePolicy: global-before-preflight-v1`;
- manifest and admitted evidence hashes;
- exact target identities and profile hashes; and
- final `sourceChecks` for the Lab and every target.

The legacy `ignoredConcurrentHostReceipts` field remains an empty array for
consumer compatibility because no shared receipt scan occurs. Aggregate source
checks run on every exit path, including host failure and receipt-admission
failure. The named mutex is released even if preflight, execution or final
receipt publication fails.

## Acceptance boundary

This workflow proves only the actual retained Windows session, installed GPU and
sound-device inventory, exact game checkouts, Godot input routing, recorded
evidence, and accepted local MCP worker represented by the receipts. Synthetic
gamepad input is not physical controller enumeration, Steam Input, rumble, or
latency certification. Automated media analysis is not human game-feel,
accessibility, art-direction, or final mix approval.
