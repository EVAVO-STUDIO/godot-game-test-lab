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
- Godot 4.6.2 or newer standard console executable;
- Godot 4.6.2 or newer Mono console executable for C# projects;
- a compatible .NET SDK for the target project;
- matching Godot export templates only when an export command is explicitly requested.

Recommended environment variables:

```powershell
$env:GODOT_BIN = "C:\Tools\Godot\Godot_v4.6.2-stable_win64_console.exe"
$env:GODOT_MONO_BIN = "C:\Tools\GodotMono\Godot_v4.6.2-stable_mono_win64_console.exe"
$env:DOTNET_BIN = "C:\Program Files\dotnet\dotnet.exe"
```

Tool paths are runner configuration. They must not be committed as credentials or copied into game repositories.

## Filesystem boundary

Target projects must resolve beneath:

```text
C:\GitRepos
```

The target must:

- contain `project.godot`;
- belong to a Git repository beneath the same root;
- not be the test-lab repository itself.

Validation may create normal ignored Godot import caches and bounded QA artifacts. The tracked Git status is captured before and after validation. Any changed tracked file fails the run.

The wrapper has no commit, push, branch, pull-request, deployment, migration or repository-reset operation.

## Exact-SHA boundary

The operator supplies:

- the exact 40-character Godot Game Test Lab `main` SHA;
- the absolute target project path;
- the minimum Godot version, normally `4.6.2`;
- `request_source=evavo-development-studio`.

The workflow checks out the exact lab SHA and proves that it belongs to `origin/main`. It does not select or mutate a target repository revision. Development Studio must separately record the target repository SHA before requesting validation.

## Validation order

The native wrapper runs:

1. Python source compilation;
2. Ruff;
3. pytest;
4. Godot and .NET doctor probe;
5. target project inventory;
6. exact Godot/Mono compatibility checks;
7. `.NET` build when required;
8. headless Godot import;
9. bounded main-scene boot;
10. tracked-source mutation comparison;
11. bounded JSON receipt and logs.

A successful import or bounded boot is not a visual-quality approval. Windowed play, recording, screenshots and human/gameplay review remain separate evidence lanes.

## Evidence and retention

The workflow uploads only the bounded `artifacts/native` directory and retains it for 14 days. Evidence can include:

- doctor report;
- validation report;
- command stdout/stderr;
- exact lab SHA;
- target path and Git root;
- minimum Godot version;
- tracked status before and after;
- pass/fail classification.

Do not place secrets, provider tokens, private keys, game source archives or user data in the artifact directory.

## Local execution

From an exact test-lab checkout:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\scripts\Invoke-GodotLabNativeValidation.ps1 `
  -TargetRepositoryPath "C:\GitRepos\Brass_Brine" `
  -ExpectedLabSha (git rev-parse HEAD) `
  -ArtifactPath ".\artifacts\native" `
  -PythonExecutable ".\.venv\Scripts\python.exe" `
  -MinimumGodotVersion "4.6.2"
```

Local execution follows the same path, version, test and mutation boundaries as the GitHub workflow.
