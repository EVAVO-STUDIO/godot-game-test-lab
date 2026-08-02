# Native Windows runner contract

The native runner is the execution authority for Godot projects that cannot be proven through browser or generic hosted-runner checks. It is intentionally separate from Development Studio planning and Godot Web Runtime browser evidence.

## Required GitHub runner labels

The approved runner must advertise all of these labels:

```text
self-hosted
Windows
X64
evavo-godot-lab
```

The workflow is manual `workflow_dispatch` only. Pull requests, pushes, schedules, repository dispatches and deployment events must never start native validation automatically.

## Required installed tools

The runner must provide:

- PowerShell 7 as `pwsh`;
- Git;
- Python 3.11 through `py -3.11`;
- the checksum-verified managed Godot Standard editor;
- the checksum-verified managed Godot .NET editor for C# projects;
- .NET SDK 8 for C# targets;
- matching Godot export templates only when an export command is explicitly requested.

Recommended environment variables:

```powershell
$env:GODOT_BIN = "C:\Tools\Godot\Godot_v4.6.2-stable_win64_console.exe"
$env:GODOT_MONO_BIN = "C:\Tools\GodotMono\Godot_v4.6.2-stable_mono_win64_console.exe"
$env:DOTNET_BIN = "C:\Program Files\dotnet\dotnet.exe"
```

Tool paths are runner configuration. They must not be committed as credentials or copied into game repositories.

## Filesystem boundary

Target Git roots must resolve beneath one of the explicit `AllowedTargetRoots`
values, normally:

```text
C:\GitRepos
```

The target must:

- contain `project.godot`;
- belong to a Git repository beneath the same root;
- not be the test-lab repository itself.

The target must be completely clean before validation. Godot executes against the
selected project while all retained evidence is written beneath a unique external
`AllowedArtifactRoot`. The target SHA and complete tracked/untracked status are
checked afterward; any difference fails the run.

The wrapper has no commit, push, branch, pull-request, deployment, migration or repository-reset operation.

## Exact-SHA boundary

The operator supplies:

- the exact 40-character Godot Game Test Lab `main` SHA;
- the absolute target Git root and explicit `projectSubpath`;
- the exact 40-character target game repository SHA;
- the minimum Godot version, normally `4.6.2`;
- `request_source=evavo-development-studio`.

The workflow checks out the exact lab SHA and proves that it belongs to `origin/main`. The native wrapper resolves the target Git root and refuses to run unless its current `HEAD` exactly matches `expected_target_sha`.

The workflow never checks out, resets, pulls, merges or otherwise selects a target game revision. Development Studio must prepare the intended target checkout and record the same SHA before requesting validation.

## Validation order

The native wrapper runs:

1. exact test-lab SHA verification;
2. exact target game SHA verification;
3. canonical root and reparse-point validation;
4. target clean-status verification;
5. repository toolchain validation;
6. Python source compilation, Ruff, and pytest;
7. managed Godot and .NET doctor probe;
8. target project inventory and static integrity audit;
9. `.NET` build when required;
10. authoritative headless Godot import and recovery diagnosis;
11. bounded main-scene boot;
12. complete target SHA/status comparison;
13. atomic external JSON receipt and logs.

A successful import or bounded boot is not a visual-quality approval. Windowed play, recording, screenshots and human/gameplay review remain separate evidence lanes.

## Evidence and retention

The workflow uploads only the bounded `artifacts/native` directory and retains it for 14 days. Evidence can include:

- doctor report;
- validation report;
- command stdout/stderr;
- exact lab SHA;
- exact target game SHA;
- target path and Git root;
- minimum Godot version;
- tracked status before and after;
- pass/fail classification.

Do not place secrets, provider tokens, private keys, game source archives or user data in the artifact directory.

## Local execution

From an exact test-lab checkout and an exact prepared target checkout:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\scripts\Invoke-GodotLabNativeValidation.ps1 `
  -TargetRepositoryPath "C:\GitRepos\Brass_Brine" `
  -ProjectSubpath "." `
  -AllowedTargetRoots @("C:\GitRepos") `
  -ExpectedLabSha (git rev-parse HEAD) `
  -ExpectedTargetSha (git -C "C:\GitRepos\Brass_Brine" rev-parse HEAD) `
  -ArtifactPath "C:\GodotLabEvidence\Brass_Brine\validation-001" `
  -AllowedArtifactRoot "C:\GodotLabEvidence" `
  -PythonExecutable ".\.venv\Scripts\python.exe" `
  -MinimumGodotVersion "4.6.2"
```

Local execution follows the same revision, path, version, test and mutation boundaries as the GitHub workflow.

## Interactive agent host acceptance

Use `scripts/Initialize-GodotLabAgentHost.ps1` for one-command installation, MCP
worker registration, startup, and acceptance. Use
`scripts/Test-GodotLabAgentHost.ps1` to repeat host acceptance or include a real
validation, authored journey, or deterministic bot run. The full contract is in
`docs/WINDOWS_AGENT_HOST_ACCEPTANCE.md`.
