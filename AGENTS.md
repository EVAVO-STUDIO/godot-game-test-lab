# Godot Game Test Lab Agent Instructions

This repository is the canonical EVAVO native Godot execution worker. Development Studio owns portfolio inventory, incident classification, repair authority, repository publication and target-repository effects. Godot Web Runtime owns browser-hosted interaction evidence.

## Mainline rules

- Automated work stays on `main`; do not create branches, pull requests or repositories.
- Publish this repository only through the governed Development Studio mainline process or an equivalent exact-scope direct-main operation.
- Require `repository-main:EVAVO-STUDIO/godot-game-test-lab`, a clean current `main`, the committed `evavo.reliability.json` profile and no remote-head drift.
- Never force-push, broadly stage, bypass hooks or overwrite concurrent work.
- Preserve unrelated work and stop on a dirty or drifting repository.
- Do not create another Godot QA repository or duplicate these capabilities elsewhere.

## Source checks

```powershell
python -m compileall src scripts tests
python -m ruff check src scripts tests
bash -n scripts/*.sh
python -m pytest
```

The exact-SHA GitHub source workflow proves only the Python, shell, workflow and policy contract. It does not prove a Windows runner, Linux container build, Godot executable, .NET SDK, target project, import, boot, export, rendered journey, physical controller or human review.

## Cross-repository integrity and recovery

Read `docs/PROJECT_INTEGRITY_AND_RECOVERY.md` before changing validation, project parsing, import, recovery, evidence, or Development Studio integration.

- Run `godot-lab capabilities` and `godot-lab doctor` before selecting an execution lane.
- Run `godot-lab audit <target>` before native run, recording, export, or repair diagnosis.
- Use an explicit external artifact directory; do not write retained evidence into tracked target source.
- Treat static scene/resource findings as diagnostics and Godot editor `--import` as authoritative engine validation.
- Verify required editor flags from `godot --help`; Godot may silently ignore unknown command-line arguments.
- If normal import fails, use the retained recovery-mode import as an isolation signal only. Recovery success suspects an editor plugin, `@tool` script, GDExtension, or another disabled import-time surface; it does not prove which surface caused the failure.
- Keep finding codes, categories, suggested repair actions, paths, lines, evidence and schema versions stable for Development Studio consumers.
- The Linux sandbox must retain the same `integrity-report.json` gate as native validation.
- Do not auto-edit a corrupt TSCN/TRES merely to make it parse. Prefer recovery from version control or a known-good authored file, then validate with the matching Godot editor.

## Native acceptance

Read `docs/NATIVE_WINDOWS_AGENT_QA.md` before changing native visual, GPU, window, Movie Maker, journey or interactive-session behavior.

- Use a freshly probed Windows x64 runner in Greg's logged-in interactive session, not Session 0.
- Bind every run to exact lab and target SHAs and a tracked target-owned journey profile.
- Use `godot-lab-native-qa` or `scripts/Invoke-GodotLabNativeAgentQA.ps1` for native visual and synthetic-input evidence.
- Keep native evidence beneath an explicitly allowed external root and outside both source checkouts.
- Verify all required Godot flags from `--help`; never rely on an unknown option being rejected.
- A scene selected by `godot-lab run` or `record` must become Godot's positional scene argument. Never pass an invented `--scene` engine option.
- Preserve Godot engine logs, Movie Maker output, FFprobe metadata, screenshots, contact sheets, checkpoints, hardware probes, requested renderer/driver/GPU index and target mutation evidence.
- CUDA visibility is auxiliary compute evidence, not Godot renderer or rendered-frame proof.

## Linux sandbox acceptance

- Use only `EVAVO-STUDIO/godot-game-test-lab` for reusable Linux Godot execution.
- Prefer the caller-context reusable workflow from each game repository; do not require a standing cross-repository private-repository token.
- Bind the run to the exact lab SHA, exact caller SHA and caller repository's actual default branch.
- Mount target source and the normalized profile read-only and perform all Godot and .NET writes in an ephemeral copy.
- Build Godot only from official release archives after release-manifest checksum verification.
- Run as a non-root user with no network, no Linux capabilities, `no-new-privileges`, a read-only root filesystem and bounded CPU, memory, swap, processes, file descriptors and runtime.
- Never mount the Docker socket, use privileged mode, expose `/dev/uinput`, or pass a GitHub token, deploy secret, signing key or target write credential into the container.
- Preserve report, integrity, stdout, stderr, movie, probe metadata, screenshots, contact sheets, journey checkpoints, InputMap evidence, UI telemetry and objective visual diagnostics.
- Treat Xvfb and Mesa llvmpipe as software-rendered Linux compatibility evidence, not GPU performance or final visual approval.
- Require the target checkout SHA and status to remain unchanged after the run.

## Interactive journey rules

- Schema `2.0` journeys must be bounded, deterministic and owned by the target game profile.
- Inject Godot `InputEvent` objects through `Input.parse_input_event()`; do not use shell automation to masquerade as engine input evidence.
- Concrete keyboard, mouse or joypad events are required when the journey claims device mapping coverage.
- Synthetic joypad events prove InputMap coverage and Godot event handling only. Never claim a physical controller pass, USB enumeration, Steam Input, rumble or device-specific latency from this lane.
- Required journeys fail closed. Optional journey failures remain visible findings and may not be silently discarded.
- Capture named checkpoints around meaningful transitions rather than relying only on a final frame.
- Use machine-checkable assertions where the game exposes stable node, metadata or focus contracts.
- UI geometry telemetry may identify clipping, overlap, focus and target-size defects; it is not human UX, accessibility or art-direction approval.
- Black and frozen video diagnostics are objective screen evidence only; allow intentional static or dark scenes through an explicit target-owned profile rule.

## Runtime rules

- Detect C# from `.csproj` files.
- C# requires Godot .NET and `.NET`; a standard Godot binary is invalid.
- GDScript uses the standard Godot binary unless the repository profile says otherwise.
- Require Godot 4.6.2 or the repository-declared compatible later version.
- Run `.NET` build before Godot import for C# projects.
- Preserve command, exit code, duration, bounded stdout, bounded stderr, timeout, engine log and artifact evidence.
- A headless pass is not visual quality evidence.
- A bounded boot proves startup only.
- A movie or contact sheet is not a complete interactive playthrough.
- Use Godot Web Runtime for browser input, DOM/browser traces and semantic web gameplay observations when a compatible export exists.

## Repair boundary

The worker may diagnose and retain evidence. It must never edit, commit, push, deploy or mutate a target game without a separate governed Development Studio execution grant and the target repository's own exclusive mainline lease. Every repair claim must cite the exact target SHA and the evidence boundary that actually passed.
