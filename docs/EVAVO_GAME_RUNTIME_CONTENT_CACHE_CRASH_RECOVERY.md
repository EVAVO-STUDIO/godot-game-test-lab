# EVAVO Game Runtime Content Cache Crash Recovery

This suite verifies the runtime’s deterministic content-cache fault plan and restart-reconciliation harness from outside the runtime repository.

## Scenarios

The local suite runs three gates:

1. dependency-free contract and source validation;
2. Godot headless import and complete GDScript parsing;
3. executable interruption, corruption-hook, restart, stale-generation and delay behavior.

Every receipt records the exact runtime and Test Lab Git SHAs, the Godot version, working-tree cleanliness, per-scenario logs and the final outcome.

## Truth boundaries

The suite preserves the following as false:

```text
simulated interruption is a real process crash
restart receipt grants content availability
reconciliation grants scene activation
reconciliation grants simulation authority
```

The in-process harness makes checkpoint order deterministic. It does not replace later exported-build process-kill tests on Steam, browser, Android or iOS targets.

## Validate integration

```powershell
python .\scripts\validate-evavo-game-runtime-content-cache-crash-recovery.py `
    --runtime-repo C:\GitRepos\evavo-game-runtime
```

## Run the suite

```powershell
.\scripts\run-evavo-game-runtime-content-cache-crash-recovery.ps1 `
    -RuntimeRepo C:\GitRepos\evavo-game-runtime `
    -GodotPath $env:GODOT_BIN
```

Receipts and logs are written beneath:

```text
artifacts/evavo-game-runtime-content-cache-crash-recovery/
```
