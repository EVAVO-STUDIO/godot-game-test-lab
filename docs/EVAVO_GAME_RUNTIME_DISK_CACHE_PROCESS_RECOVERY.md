# EVAVO Game Runtime Disk Cache Process Recovery

This Test Lab suite validates the persistent package cache added to `evavo-game-runtime`.

It combines four distinct scenarios:

```text
dependency_free_validators
headless_import_parse
disk_host_behavior
actual_process_kill_matrix
```

## Disk-host behavior

The Godot behavior test installs package version 1, promotes version 2, deliberately corrupts the current payload, creates a fresh host and verifies that restart reconciliation restores the previous known-good version. It also proves that a partially received version 3 candidate resumes from verified chunk files after a fresh host instance.

## Actual process-kill matrix

The matrix launches Godot as a real operating-system child process. The child blocks after emitting a checkpoint receipt containing its process ID. The parent verifies that process ID, force-terminates the child, launches a new Godot process and reconciles the same cache directory.

The required checkpoints are:

```text
after_chunk_promote
after_staged_payload_flush
after_rotate_known_good
after_promote_before_cleanup
```

Expected recovery is the previous known-good generation for the first three checkpoints and the new generation after staged-to-current promotion.

The matrix records child PIDs, non-clean termination return codes, expected and selected package versions, selected SHA-256 values and per-scenario logs.

## Exact identity

The final Test Lab receipt records:

- exact runtime Git SHA;
- exact Test Lab Git SHA;
- Godot version;
- runtime and Test Lab clean-state evidence;
- every scenario exit code;
- pass-marker observation;
- artifact and log paths.

## Truth boundaries

A checkpoint marker is not process termination. Test Lab independently kills the matching child and verifies non-clean exit.

Restart reconciliation does not grant content availability.

Restart reconciliation does not grant scene activation.

Restart reconciliation does not grant simulation authority.

A headless desktop process test does not prove exported Steam, browser, Android or iOS device behavior.

## Run

```powershell
python .\scripts\validate-evavo-game-runtime-disk-cache-process-recovery.py `
    --runtime-repo C:\GitRepos\evavo-game-runtime

.\scripts\run-evavo-game-runtime-disk-cache-process-recovery.ps1 `
    -RuntimeRepo C:\GitRepos\evavo-game-runtime `
    -GodotPath $env:GODOT_BIN
```
