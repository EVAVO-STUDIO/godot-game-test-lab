# Godot Game Test Lab Agent Instructions

This repository is the canonical EVAVO native Godot execution worker. Development Studio owns incident classification, repair authority, repository publication and target-repository effects. Godot Web Runtime owns browser-hosted interaction evidence.

## Mainline rules

- Automated work stays on `main`; do not create branches, pull requests or repositories.
- Publish this repository only through Development Studio `mainline-publish` with an explicit portfolio operation, exact repository path, coherent message and every changed path named exactly.
- Require `repository-main:EVAVO-STUDIO/godot-game-test-lab`, a clean current `main`, the committed `evavo.reliability.json` profile and no remote-head drift.
- Never force-push, broadly stage, bypass hooks or fall back to raw GitHub contents writes when the governed publisher is unavailable.
- Preserve unrelated work and stop on a dirty or drifting repository.
- Do not create another Godot QA repository or duplicate these capabilities elsewhere.

## Source checks

```powershell
python -m compileall src tests
python -m ruff check src tests
python -m pytest
```

The exact-SHA GitHub workflow proves only this Python worker contract. It does not prove a Windows runner, Godot executable, .NET SDK, target project, import, Boot, export, visual result or playthrough.

## Native acceptance

For a real project, use a freshly probed Windows x64 runner and supply an absolute target repository path plus an external evidence directory. Run `godot-lab doctor` before `godot-lab validate`, export or recording commands. Bind every run to the exact target `main` SHA and target reliability profile.

## Runtime rules

- Detect C# from `.csproj` files.
- C# requires Godot Mono and `.NET`; a standard Godot binary is invalid.
- GDScript uses the standard Godot binary unless the repository profile says otherwise.
- Require Godot 4.6.2 or the repository-declared compatible later version.
- Run `.NET` build before Godot import for C# projects.
- Preserve command, exit code, duration, stdout, stderr, timeout and artifact evidence.
- A headless pass is not visual quality evidence.
- A bounded Boot proves startup only.
- A movie is not an interactive playthrough.
- Use Godot Web Runtime for real browser input and semantic gameplay observations when a compatible GDScript web export exists.

The worker must never edit, commit, push, deploy or mutate a target game without a separate governed Development Studio execution grant and the target repository’s own exclusive mainline lease.
