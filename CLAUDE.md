# Claude Contract for Godot Game Test Lab

Read `AGENTS.md`, `docs/INTERACTIVE_AGENT_QA.md`, `docs/PROJECT_INTEGRITY_AND_RECOVERY.md`, `docs/NATIVE_WINDOWS_AGENT_QA.md` and `evavo.reliability.json` before acting.

Work directly on `main`, preserve unrelated work and publish only through the governed Development Studio mainline process or an equivalent exact-scope direct-main operation. Do not create branches, pull requests or repositories. Require the Godot lab repository lease and stop when the remote head drifts.

Use this repository for cross-repository static project integrity, Windows native Godot inspection, isolated Linux Godot compatibility evidence, Godot .NET validation, bounded boot, export, rendered evidence and repository-authored input journeys. Use Godot Web Runtime for compatible browser playtesting. Never claim Windows, Linux container, Godot, visual or interactive proof from the Python source workflow or a static audit.

Run `godot-lab capabilities`, `godot-lab doctor`, `godot-lab inspect <repo>`, `godot-lab audit <repo>` and then `godot-lab validate <repo> --artifacts <external-path>`. Keep target source separate from the lab. Verify editor CLI flags before execution because Godot can silently ignore unknown arguments. Static findings diagnose likely corruption and reference defects; the matching Godot editor `--import` remains authoritative. Recovery-mode success after a normal import failure suspects an import-time editor extension but does not identify a proven root cause.

For native visual and input QA, use `godot-lab-native-qa` or `scripts/Invoke-GodotLabNativeAgentQA.ps1` with exact lab and target SHAs, a tracked target-owned profile, a project subpath and an external evidence root. Run in Greg's logged-in interactive Windows session, not Session 0. Preserve engine logs, movies, screenshots, checkpoints, requested rendering method/driver/GPU index and target mutation evidence. A requested scene must be a verified `res://` file passed to Godot positionally; never rely on an invented `--scene` option.

A real Windows target run requires a freshly probed Windows x64 runner, the exact target default-branch SHA, the target reliability profile, absolute target and external evidence paths, the correct standard or .NET Godot executable and `.NET` when C# is detected. CUDA evidence is auxiliary compute capability, not Godot renderer or GPU-journey proof.

A Linux caller run requires exact lab and target SHAs, the caller repository's actual default branch, a read-only target and normalized-profile mount, an ephemeral working copy, verified official Godot archives, a non-root no-network container, bounded resources, Xvfb and Mesa software rendering, and retained integrity/build/log/movie/screenshot/journey evidence. The standard reusable workflow runs in the caller context and must not require a standing cross-repository private-repository token.

Schema-2 journeys inject bounded Godot `InputEvent` objects through `Input.parse_input_event()`. Synthetic keyboard, mouse and joypad events may prove InputMap coverage, event routing and declared state changes. They do not prove physical controller enumeration, USB or wireless behavior, Steam Input, rumble, native GPU performance, complete gameplay, accessibility or human UX approval.

Never edit, commit, push, deploy or mutate a target game without a separate Development Studio execution grant and the target repository's own exclusive mainline lease. Every repair claim must identify the exact target SHA and the evidence boundary that actually passed.
