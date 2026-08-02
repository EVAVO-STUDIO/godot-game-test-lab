# Managed Godot engines

Godot Game Test Lab provisions its own portable Godot editors for Windows and
Linux. The repository does **not** commit multi-hundred-megabyte platform
binaries to Git. Instead, every agent entrypoint can install an official stable
archive on first use, verify it against the release's `SHA512-SUMS.txt`, and
reuse the verified installation thereafter.

This gives ChatGPT, Claude, Development Studio, local shells, CI workers, and
self-hosted runners the same deterministic engine-selection contract without
requiring each game repository to carry Godot.

## Governed versions

`src/godot_game_test_lab/godot-engine-lock.json` is the source of truth:

- minimum accepted editor: Godot 4.6.2;
- default 4.6 editor: Godot 4.6.3;
- default 4.7 editor: Godot 4.7.1;
- default flavours: Standard and .NET/Mono;
- matching export templates: installed by default;
- editor mode: self-contained and writable outside source repositories.

A project declaring the `4.6` feature branch receives 4.6.3. A project declaring
`4.7` receives 4.7.1. A project containing a `.csproj` receives the .NET editor;
a GDScript-only project receives the Standard editor. An explicit compatible
version can override the branch mapping.

## Installation locations

The managed root defaults to:

```text
Windows: %LOCALAPPDATA%\EVAVO\GodotGameTestLab\engines
Linux:   ${XDG_CACHE_HOME:-~/.cache}/evavo/godot-game-test-lab/engines
```

Override it with `EVAVO_GODOT_HOME` or `--root`. The root must remain outside the
Test Lab checkout, every target-game checkout, and retained evidence.

Each installation contains:

```text
Godot_v<version>-stable[_mono]_<platform>/
  Godot executable and runtime payload
  _sc_ or ._sc_
  editor_data/
    export_templates/<version>.stable/
  engine-installation.json
```

The self-contained marker causes Godot editor data, settings, cache, and export
templates to stay beside that managed editor. A target game therefore does not
need a machine-global Godot installation and one Lab run does not pollute another
editor installation.

## Windows one-command setup

From an ordinary PowerShell session:

```powershell
Set-Location C:\GitRepos\godot-game-test-lab
.\scripts\Install-GodotLab.ps1 `
  -PrepareEstate `
  -PrepareLinuxSandboxImages `
  -InstallPrerequisites `
  -RequireFullMediaToolchain
```

The installer:

1. creates the Python 3.11 virtual environment;
2. installs the CLI and optional MCP bridge;
3. downloads Standard and .NET Godot 4.6.3 plus matching export templates;
4. validates official SHA-512 identities and the extracted payload;
5. creates portable self-contained editors;
6. writes user environment variables and an environment script;
7. optionally scans `C:\GitRepos` and prewarms every required branch/flavour;
8. runs `godot-lab doctor` and the MCP server self-test;
9. writes an installation receipt under `C:\GodotLabEvidence`.

No administrator rights are required for the managed editors. The optional
`-InstallPrerequisites` path uses WinGet for .NET SDK 8 and FFmpeg/FFprobe; a
system-wide .NET installation may request elevation. `-RequireFullMediaToolchain`
fails setup if C# or synchronized audio dependencies remain unavailable.

## Linux one-command setup

```bash
cd ~/GitRepos/godot-game-test-lab
PREPARE_ESTATE=1 ./scripts/install-godot-lab.sh
source ~/.local/share/EVAVO/GodotLabEvidence/godot-lab-env.sh
```

The Linux sandbox image separately embeds a checksum-verified Godot editor,
matching export templates, .NET SDK 8, FFmpeg, Xvfb, Mesa, and required runtime
libraries. Native Linux agents can use the managed host editor; isolated CI
journeys use the sandbox image.

## Managed local Linux sandbox images

The local Docker lane is a separate cache from the native host editors. It uses
the same governed Godot branch mapping and builds either a Standard or Mono
image containing:

```text
checksum-verified official Godot editor
matching export templates
.NET SDK 8
FFmpeg and FFprobe
Xvfb
Mesa llvmpipe and Vulkan software drivers
```

Build or inspect images:

```powershell
godot-lab sandbox status
godot-lab sandbox image --version 4.6.3 --flavor standard
godot-lab sandbox image --version 4.6.3 --flavor mono
```

The image build requires network access only when the governed image is not
already cached. A game run uses `--network none`, a read-only container root,
dropped capabilities, no-new-privileges, a read-only source mount and bounded
resources. Docker Desktop on Windows or Docker Engine on Linux must already be
installed and running; the Lab does not silently start or elevate the container
engine.

Run an external clean repository with:

```powershell
godot-lab sandbox run C:\GitRepos\SomeGame `
  --profile .evavo\godot-lab-linux.json `
  --artifacts C:\GodotLabEvidence\SomeGame\linux-latest `
  --allowed-root C:\GitRepos
```

The image tag includes the Godot version, flavor and Lab SHA so source and engine
changes do not accidentally reuse the wrong worker image.

## Project-level automatic provisioning

These commands provision the required editor automatically when `--godot` is not
supplied:

```powershell
godot-lab validate C:\GitRepos\SomeGame --artifacts C:\GodotLabEvidence\SomeGame\validate
godot-lab run C:\GitRepos\SomeGame --frames 300
godot-lab record C:\GitRepos\SomeGame --output C:\GodotLabEvidence\SomeGame\run.avi
godot-lab export C:\GitRepos\SomeGame --preset "Windows Desktop" --output C:\Builds\SomeGame.exe
```

Disable network-backed provisioning with `--no-auto-provision-engine`, or use
`--offline-engine --engine-source-dir <release-directory>`.

## Explicit engine commands

```text
godot-lab engine status
godot-lab engine install --version 4.6.3 --flavor standard
godot-lab engine ensure C:\GitRepos\SomeGame
godot-lab engine bootstrap --version 4.6.3 --flavors standard,mono
godot-lab engine prepare C:\GitRepos
godot-lab engine env --format powershell
godot-lab engine mirror D:\GodotOfflineMirror
```

`engine prepare` scans a bounded repository estate, detects every Godot project,
deduplicates version/flavour requirements, and preinstalls only the necessary
editors. `engine mirror` downloads and verifies official Windows/Linux Standard
and .NET assets for disconnected workers.

## Offline operation

Create an offline mirror on a networked machine:

```powershell
godot-lab engine mirror D:\GodotOfflineMirror `
  --versions 4.6.3,4.7.1 `
  --platforms windows-x86_64,linux-x86_64 `
  --flavors standard,mono
```

Copy the relevant `<version>-stable` directory to the worker, then install:

```powershell
godot-lab engine bootstrap `
  --version 4.6.3 `
  --source-dir D:\GodotOfflineMirror\4.6.3-stable `
  --offline
```

Offline mode fails closed if the official checksum manifest or any required
asset is missing.

## Agent and MCP behaviour

The MCP bridge exposes `godot_ensure_engine`. Validation, authored QA, and bot QA
also auto-provision unless the server starts with `--no-auto-provision`.

A typical model workflow is:

```text
godot_inspect
  -> godot_audit
  -> godot_ensure_engine
  -> godot_validate
  -> godot_run_bot_qa or godot_run_native_qa
  -> godot_view_image / godot_hear_audio
  -> godot_review_run
```

The MCP server has no arbitrary shell tool. It may download governed engine
assets and write its managed-engine/evidence roots, but it cannot edit, commit,
push, deploy, sign, or publish a target game.

## Integrity and recovery

Engine installation fails closed on:

- unsupported platform, architecture, version, or flavour;
- missing or ambiguous official checksum entries;
- SHA-512 mismatch;
- oversized downloads or expanded archives;
- absolute, traversing, colliding, Unicode-colliding, or NUL-containing paths;
- archive symlinks or special files;
- missing or mismatched export-template `version.txt`;
- executable identity mismatch;
- extracted payload digest mismatch;
- interrupted atomic replacement;
- concurrent installation lock timeout.

A corrupt managed installation is reported by `engine status` and replaced
atomically on the next `install`, `ensure`, or automatic-provisioning request.

## Truth boundaries

A successful managed installation proves that the selected official archive was
checksum-verified, safely extracted, and executable on the current host. It does
not prove that a target game imports, builds, renders, sounds correct, performs
well, or is enjoyable. Those claims require the subsequent validation, visual,
audio, performance, bot, and human-review evidence lanes.
