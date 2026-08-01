# Godot Game Test Lab Agent Instructions

This repository is the canonical EVAVO native Godot execution worker.
Development Studio owns portfolio inventory, incident classification, repair
authority, repository publication, and target-repository effects. Godot Web
Runtime owns browser-hosted interaction evidence.

## Mainline rules

- Automated work stays on `main`; do not create branches, pull requests, or
  replacement repositories.
- Publish only through the governed Development Studio process or an equivalent
  exact-scope, non-forced direct-main operation.
- Require `repository-main:EVAVO-STUDIO/godot-game-test-lab`, a current clean
  `main`, the committed `evavo.reliability.json`, and no remote-head drift.
- Never force-push, broadly stage, bypass hooks, or overwrite concurrent work.
- Preserve unrelated work and stop on a dirty or drifting repository.

## Source checks

```powershell
python scripts/check_repository_toolchain.py
python scripts/test_repository_toolchain.py
python -m compileall -q src scripts tests
python -m ruff check src scripts tests
python -m pytest
python -m pip wheel --no-deps --wheel-dir dist .
```

Hosted source validation proves the Python, shell, workflow, and policy contract
only. It does not prove a Windows session, Linux container, Godot executable,
.NET SDK, target game, import, boot, export, GPU, rendered journey, controller,
or human review.

## Cross-repository integrity and recovery

Read `docs/PROJECT_INTEGRITY_AND_RECOVERY.md` before changing validation,
project parsing, import, recovery, evidence, or Development Studio integration.

- Run `godot-lab capabilities` and `godot-lab doctor` before selecting a lane.
- Run `godot-lab audit <target>` before native execution or repair diagnosis.
- Use an explicit external artifact directory; retained evidence must not be
  written into tracked Lab or target source.
- Treat static scene/resource findings as diagnostics and matching-editor
  `--import` as authoritative engine validation.
- Verify required editor flags from `godot --help`; Godot may ignore unknown
  command-line arguments.
- Recovery success is an isolation signal, not a proven root cause.
- Keep finding codes, categories, paths, lines, repair actions, evidence, and
  schema versions stable for Development Studio consumers.
- Never auto-delete arbitrary TSCN/TRES sections to make a file parse.

## Native Windows agent QA

Read `docs/NATIVE_WINDOWS_AGENT_QA.md` before changing the native profile,
runner, process supervision, desktop session, graphics, or visual evidence.

- Require exact clean Lab and target SHAs. A dirty checkout cannot be represented
  by `HEAD`.
- Require the profile to be a tracked regular file and normalize it strictly.
- The exact archive lane fails closed on submodules until a governed
  materialization contract exists.
- Keep Lab, target, allowed evidence root, and run-specific evidence directory
  disjoint.
- Acquire the single native desktop lease before native visual execution.
- Require Explorer in the same nonzero Windows session for a desktop-evidence
  claim; Session 0 is invalid.
- Enforce whole-process time, output, artifact-byte, file-count, and
  resolution-by-frame budgets.
- Drain stdout/stderr while processes run and terminate the complete process
  tree on timeout or evidence overflow.
- Validate checkpoint IDs and all retained evidence paths; never follow evidence
  symlinks.
- Keep full logs separate from compact process receipts in the final summary.
- Recheck the original target checkout on every exit path.
- Black/freeze diagnostics are objective evidence. They become failures only
  through explicit target-owned profile policy.

## Linux sandbox acceptance

- Use only this repository for reusable Linux Godot execution.
- Prefer the caller-context reusable workflow from each game repository.
- Bind runs to exact Lab and caller SHAs and the caller's real default branch.
- Mount target source and normalized profile read-only; write only to an
  ephemeral copy and bounded artifact directory.
- Verify official Godot release archives against release manifests.
- Run non-root with no network, Linux capabilities, Docker socket, `/dev/uinput`,
  deployment secret, signing key, or target write credential.
- Preserve integrity, command, engine, movie, screenshot, checkpoint, InputMap,
  UI, and summary evidence.
- Treat Xvfb/Mesa llvmpipe as Linux compatibility evidence, not Windows GPU or
  final visual approval.

## Interactive journey rules

- Schema-2 journeys are bounded, deterministic, and owned by the target game.
- Inject Godot `InputEvent` objects through `Input.parse_input_event()`.
- Required journeys fail closed. Optional failures remain visible findings.
- Capture named checkpoints around meaningful transitions.
- Use machine-checkable assertions only where the game exposes stable
  contracts.
- Synthetic joypad events prove InputMap/event handling only, never physical
  controller enumeration, Steam Input, rumble, or latency.
- UI geometry telemetry is not human UX, accessibility, game-feel, or art
  approval.

## Runtime rules

- Detect C# from `.csproj` files.
- C# requires Godot .NET and `.NET`; a standard editor is invalid.
- Require Godot 4.6.2 or a repository-declared compatible later 4.x release.
- Run `.NET` build before Godot import for C# projects.
- Preserve command, exit, duration, bounded output, timeout, engine log, and
  artifact evidence.
- Convert the Lab CLI's `--scene` option to Godot's validated positional scene
  argument; do not pass an invented engine option.
- A bounded boot proves startup only. A movie is not a complete playthrough.

## Repair boundary

The worker may diagnose and retain evidence. It must never edit, commit, push,
deploy, sign, or publish a target game without a separate Development Studio
execution grant and the target repository's exclusive mainline lease. Every
repair claim must cite the exact target SHA and the evidence boundary that
actually passed.
