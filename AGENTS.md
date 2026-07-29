# Godot Game Test Lab Agent Instructions

This repository is the canonical EVAVO native Godot execution worker. Development Studio owns incident classification, repair authority and repository effects. Godot Web Runtime owns browser-hosted interaction evidence.

## Mainline rules

- Automated work commits directly to `main`; do not create branches or pull requests.
- Start from a clean checkout, pull `origin/main` with `--ff-only`, never force-push and push each validated coherent commit immediately.
- Preserve unrelated work and skip dirty repositories.
- Do not create another Godot QA repository or duplicate these capabilities elsewhere.

## Required checks

```powershell
python -m compileall src tests
python -m ruff check src tests
python -m pytest
```

For a real project, also run `godot-lab doctor` and `godot-lab validate <repo> --artifacts <path>` on the correct Windows runner.

## Runtime rules

- Detect C# from `.csproj` files.
- C# requires Godot Mono and `.NET`; a standard Godot binary is invalid.
- GDScript uses the standard Godot binary unless the repository profile says otherwise.
- Require Godot 4.6.2 or the repository-declared compatible later version.
- Run `.NET` build before Godot import for C# projects.
- Preserve command, exit code, duration, stdout, stderr, timeout and artifact evidence.
- A headless pass is not visual quality evidence.
- A movie is not an interactive playthrough.
- Use Godot Web Runtime for real browser input and semantic gameplay observations when a compatible web export exists.

The worker must never edit, commit, push or deploy a target game repository without a separate governed Development Studio execution grant.
