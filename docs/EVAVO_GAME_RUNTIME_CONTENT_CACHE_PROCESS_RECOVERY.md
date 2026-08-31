# EVAVO Game Runtime Content Cache Process Recovery

This Test Lab suite validates EVAVO Game Runtime's persistent disk-backed package cache across actual child-process termination boundaries.

## What is tested

The suite runs four layers:

```text
dependency-free source and contract validation
        ↓
Godot 4.6.2 headless project import and parse
        ↓
disk-backed cache behavior smoke
        ↓
real child process kill and restart matrix
```

The process matrix starts Godot as a separate operating-system process, waits for a persistence checkpoint containing that child's PID, verifies the PID, force-kills the process, then starts another Godot process against the same cache directory.

The required checkpoints are:

```text
after_chunk_promote
after_staged_payload_flush
after_rotate_known_good
after_promote_before_cleanup
```

Expected recovery is intentionally different at the final checkpoint. The first three retain or restore the prior known-good package. Once the complete new package has been atomically promoted, a process death before cleanup must retain the verified new generation.

## Evidence

The Test Lab receipt records:

- exact runtime Git SHA;
- exact Test Lab Git SHA;
- Godot version;
- clean-state evidence for both repositories;
- every scenario's exit code and log path;
- the nested runtime process-matrix receipt;
- every force-killed child PID;
- expected and selected package versions;
- all required truth-boundary claims.

## Truth boundaries

The suite uses a real child process kill, not the runtime's deterministic in-process interruption harness.

The tested Godot process is still a headless editor binary, not an exported game build.

Restart reconciliation does not grant content availability.

Restart reconciliation does not grant scene activation.

Restart reconciliation does not grant simulation authority.

This suite does not claim storefront SDK, browser service-worker, Android lifecycle, iOS lifecycle, physical-device, sudden-power-loss or storage-controller durability evidence.

## Run

```powershell
.\scripts\run-evavo-game-runtime-content-cache-process-recovery.ps1 `
    -RuntimeRepo C:\GitRepos\evavo-game-runtime `
    -GodotPath $env:GODOT_BIN
```

Validate integration without starting Godot:

```powershell
python .\scripts\validate-evavo-game-runtime-content-cache-process-recovery.py `
    --runtime-repo C:\GitRepos\evavo-game-runtime
```
