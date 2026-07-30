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

## Native acceptance

For a real project, use a freshly probed Windows x64 runner and supply an absolute target repository path plus an external evidence directory. Run `godot-lab doctor` before `godot-lab validate`, export or recording commands. Bind every run to the exact target default-branch SHA and target reliability profile.

## Linux sandbox acceptance

- Use only `EVAVO-STUDIO/godot-game-test-lab` for reusable Linux Godot execution.
- Prefer the caller-context reusable workflow from each game repository; do not require a standing cross-repository private-repository token.
- Bind the run to the exact lab SHA, exact caller SHA and caller repository's actual default branch.
- Mount target source and the normalized profile read-only and perform all Godot and .NET writes in an ephemeral copy.
- Build Godot only from official release archives after release-manifest checksum verification.
- Run as a non-root user with no network, no Linux capabilities, `no-new-privileges`, a read-only root filesystem and bounded CPU, memory, swap, processes, file descriptors and runtime.
- Never mount the Docker socket, use privileged mode, expose `/dev/uinput`, or pass a GitHub token, deploy secret, signing key or target write credential into the container.
- Preserve report, stdout, stderr, movie, probe metadata, screenshots, contact sheets, journey checkpoints, InputMap evidence, UI telemetry and objective visual diagnostics.
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
- Preserve command, exit code, duration, stdout, stderr, timeout and artifact evidence.
- A headless pass is not visual quality evidence.
- A bounded boot proves startup only.
- A movie or contact sheet is not a complete interactive playthrough.
- Use Godot Web Runtime for browser input, DOM/browser traces and semantic web gameplay observations when a compatible export exists.

## Repair boundary

The worker may diagnose and retain evidence. It must never edit, commit, push, deploy or mutate a target game without a separate governed Development Studio execution grant and the target repository's own exclusive mainline lease. Every repair claim must cite the exact target SHA and the evidence boundary that actually passed.
