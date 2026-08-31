# EVAVO Game Runtime Content Cache Process Recovery

This Test Lab suite validates EVAVO Game Runtime's persistent, content-addressed disk package cache across actual child-process termination boundaries.

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
after_ready_promote_before_index
after_index_write_before_candidate_cleanup
```

## Content-addressed expectations

Package cache keys include package ID, package version and complete SHA-256. The old and new package versions therefore remain separate immutable entries.

The matrix expects:

```text
after_chunk_promote
    old entry ready
    new entry not ready
    new candidate resumable

after_staged_payload_flush
    old entry ready
    verified new staged entry recovered to ready
    stale candidate removed

after_ready_promote_before_index
    old entry ready
    new entry ready
    derivative index rebuilt

after_index_write_before_candidate_cleanup
    old entry ready
    new entry ready
    stale candidate removed during restart reconciliation
```

The cache does not select the active release and does not perform release rollback. Those decisions remain in the trusted release ledger and transactional release-activation layer.

## Evidence

The Test Lab receipt records:

- exact runtime Git SHA;
- exact Test Lab Git SHA;
- Godot version;
- clean-state evidence for both repositories;
- every scenario's exit code and log path;
- the nested runtime process-matrix receipt;
- every force-killed child PID;
- old-entry readiness;
- expected and observed new-entry readiness;
- expected and observed candidate-resume state;
- all required truth-boundary claims.

## Truth boundaries

The suite uses a real child process kill, not the runtime's deterministic in-process interruption harness.

The tested Godot process is still a headless editor binary, not an exported game build.

Restart reconciliation does not grant content availability.

Restart reconciliation does not grant scene activation.

Restart reconciliation does not grant simulation authority.

Cache reconciliation does not select the active release.

Cache reconciliation does not perform release rollback.

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
