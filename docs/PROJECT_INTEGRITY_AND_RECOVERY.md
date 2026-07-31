# Project Integrity, Recovery, and Cross-Repository QA

Godot Game Test Lab is a reusable execution and evidence worker. It is not copied into a game and it does not require the game to live in the same repository. Every command accepts an explicit path to a target Godot project or to a parent directory containing exactly one project.

```text
C:\GitRepos\godot-game-test-lab
C:\GitRepos\Brass_Brine
C:\GitRepos\epochbound
D:\Prototypes\another-godot-game
```

The lab discovers `project.godot`, keeps the target repository as the source of truth, writes evidence outside tracked game source, and never edits, commits, pushes, exports credentials, or deploys a target game by itself.

## Canonical automated sequence

Use the same sequence locally, from Development Studio, or in an exact-SHA worker:

```powershell
godot-lab capabilities
godot-lab doctor
godot-lab inspect C:\GitRepos\Brass_Brine
godot-lab audit C:\GitRepos\Brass_Brine `
  --output C:\GodotLabEvidence\Brass_Brine\integrity-report.json
godot-lab validate C:\GitRepos\Brass_Brine `
  --artifacts C:\GodotLabEvidence\Brass_Brine\validation
```

The validation order is intentionally fail-closed:

1. Resolve exactly one project without traversing generated Godot, build, IDE, or evidence directories.
2. Perform a bounded static integrity audit.
3. Refuse engine execution if the audit could not safely inspect the project tree.
4. Select the standard or .NET Godot editor from the target workload.
5. Verify the engine version and required editor CLI capabilities from `godot --help`.
6. Run `dotnet build` first for every detected C# project.
7. Run Godot's authoritative editor `--import` pass.
8. If normal import fails, repeat it in `--recovery-mode` to isolate import-time extensions.
9. Run a bounded headless boot only after a clean normal import.
10. Retain structured reports, separate stdout and stderr, and Godot engine logs.

Godot silently ignores some unknown command-line arguments. The capability probe is therefore required before relying on `--import`, `--recovery-mode`, Movie Maker, export, or graphics-diagnostic options.

## Static integrity coverage

The audit is dependency-free, deterministic, read-only, and bounded by file count, total bytes, text-file size, and finding count. Each finding contains:

- severity;
- stable machine code;
- category;
- human explanation;
- suggested repair action;
- relative path and line where available;
- bounded structured evidence.

The current audit covers these defect families:

| Area | Examples |
| --- | --- |
| Filesystem safety | symlinks, special files, unreadable directories or files, bounded-scan exhaustion |
| Cross-platform paths | Windows reserved names, invalid characters, trailing dots/spaces, case-fold and Unicode collisions, long-path risk |
| Source integrity | invalid UTF-8, NUL bytes, empty sources, merge conflict markers, non-finite JSON, malformed XML or TOML |
| Git materialization | unresolved index entries, Git LFS pointer files, tracked Godot export credentials |
| Godot project configuration | unsupported `config_version`, duplicate sections/settings, missing or unresolved main scene, missing autoloads and editor plugins |
| Text scene/resource structure | wrong descriptor, format other than 3, malformed or out-of-order sections, duplicate or unresolved ExtResource/SubResource IDs, missing external paths, path escapes, duplicate UIDs |
| Scene graph structure | no root, multiple roots, root not first, missing root type/instance, duplicate node paths or unique IDs, parent ordering, malformed connections |
| Resource roots | TRES files without exactly one `[resource]` section |
| Export configuration | duplicate preset sections/names, missing preset names or platforms |
| Asset sanity | empty files, common binary signature/terminator failures, GLB declared-length mismatch |
| Import-time execution surfaces | `@tool` scripts, GDExtension configuration, and enabled editor plugins |

Static parsing is deliberately conservative. Godot `--import` remains authoritative for the complete engine parser, importer, script language, ClassDB, plugin, native-extension, and dependency graph.

## Corrupt scene and resource diagnosis

A text scene or resource failure should be repaired from the most reliable source available, normally version control or a known-good authored file. Do not mechanically delete arbitrary sections merely to make parsing continue.

Typical diagnosis:

| Evidence | Likely boundary | Next action |
| --- | --- | --- |
| Static audit reports invalid descriptor, duplicate root, unresolved resource ID, or missing path | Source file structure or reference graph | Restore or repair the named file, then rerun audit and import |
| Static audit passes but normal import fails | Engine parser, importer, script, extension, project configuration, or asset semantics | Read retained Godot stdout, stderr, and engine log |
| Normal import fails but recovery import passes | Import-time editor plugin, `@tool` script, GDExtension, or another surface disabled by recovery mode is suspected | Disable or isolate surfaces one at a time; do not call the suspicion a proven root cause |
| Normal and recovery import both fail | Core source, imported asset, engine compatibility, or project configuration remains suspect | Start with the first deterministic engine error and its dependency chain |
| Import passes but bounded boot fails | Runtime startup, autoload, main scene, shader, renderer, or initialization code | Use the boot log and a native visual session |
| Linux software-rendered journey passes but Windows native run fails | Native driver, GPU, platform API, native extension, packaging, or Windows-specific behavior | Run the exact target SHA on the Windows GPU worker |

Binary `.scn` and `.res` files cannot be safely reconstructed by the static text parser. The lab detects empty or unmaterialized files and relies on the matching Godot editor import for authoritative binary validation.

## Unit, integration, and gameplay tests

The game repository owns its test code and declares which tests are required. This prevents the reusable worker from guessing plugin versions or silently running an unintended scene.

Supported patterns include:

- plain Godot test scenes that exit with an explicit process result;
- GUT for Godot 4 projects;
- GdUnit4 for GDScript, C#, and scene tests;
- C# test projects executed through the target repository's pinned .NET toolchain;
- schema-2 keyboard, mouse, and synthetic joypad journeys;
- deterministic state assertions exposed by the game;
- export-and-launch smoke tests;
- repository-specific save/load, migration, deterministic simulation, and content-validation suites.

Framework configuration, plugin source, test selection, timeout, and expected result files remain target-owned. The worker should preserve JUnit XML, HTML reports, process output, screenshots, movies, checkpoints, and exact command identity as evidence. A missing expected report is a failed or missing-evidence state, never an inferred pass.

## Visual, input, and GPU QA

Headless import and boot are not visual approval. Use the existing Linux journey worker for deterministic software-rendered compatibility evidence and the native Windows worker for the real desktop, graphics driver, GPU selection, input focus, screenshots, recordings, and performance diagnostics.

CUDA is optional auxiliary compute capability for image analysis or ML-assisted tooling. Godot itself renders through its selected display and rendering drivers. `nvidia-smi`, `nvcc`, and `vulkaninfo` evidence must not be presented as proof that a particular game frame used CUDA or that a native GPU journey passed.

A complete native acceptance record should identify:

- exact lab SHA and exact target SHA;
- Godot executable, version, flavor, rendering method, rendering driver, and requested GPU index;
- display adapter and driver evidence;
- import, build, boot, journey, export, and process-exit status;
- screenshots or movie checkpoints;
- engine, console, and crash logs;
- target Git state before and after;
- evidence hashes and truth boundaries.

## Development Studio delegation

Development Studio is the control plane. It should:

1. Discover the target repository and reliability profile.
2. Identify Godot GDScript versus Godot .NET.
3. Select `godot-native-test-lab` for native audit, import, build, boot, export, visual, and input evidence.
4. Select Godot Web Runtime only for compatible browser exports.
5. Bind every worker request to exact lab and target commits.
6. Store the resulting evidence and incident classification.
7. Grant any repair to the target repository separately, under that repository's exclusive mainline lease.
8. Re-run the same failed evidence lane after repair before claiming completion.

The lab may suggest repair actions, but suggestions are not permission to mutate a game. Development Studio owns repair authority, target effects, publication, and portfolio state.

## Evidence contract

Native validation writes:

```text
validation/
  report.json
  integrity-report.json
  command-01.stdout.log
  command-01.stderr.log
  ...
  engine-logs/
    godot-import.log
    godot-recovery-import.log
    godot-bounded-boot.log
```

The Linux worker also retains `integrity-report.json` beside `sandbox-report.json` and the existing movie, screenshot, checkpoint, telemetry, export, and agent-summary evidence.

A pass is valid only for the lane that actually ran. Static audit, headless import, bounded boot, software-rendered Linux, synthetic input, native Windows graphics, physical controller, export, and human visual review are separate evidence boundaries.

## Official references

- Godot command-line tutorial: <https://docs.godotengine.org/en/4.6/tutorials/editor/command_line_tutorial.html>
- Godot TSCN file format: <https://docs.godotengine.org/en/4.6/engine_details/file_formats/tscn.html>
- Exporting projects: <https://docs.godotengine.org/en/4.6/tutorials/export/exporting_projects.html>
- Godot C# basics: <https://docs.godotengine.org/en/4.6/tutorials/scripting/c_sharp/c_sharp_basics.html>
- GUT: <https://github.com/bitwes/Gut>
- GdUnit4: <https://github.com/MikeSchulze/gdUnit4>
