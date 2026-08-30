# EVAVO Game Runtime World-Streaming Lane

This local Test Lab lane verifies the world-residency and authoritative-region
handoff behavior supplied by `EVAVO-STUDIO/evavo-game-runtime`.

It does not infer authority from screenshots, resource-load completion or
manifest memory estimates. It executes the runtime's Godot behavior smoke and
retains a receipt bound to the exact Test Lab and runtime Git commits.

## Run

```powershell
Set-Location C:\GitRepos\godot-game-test-lab

python .\scripts\validate-evavo-game-runtime-world-streaming.py

.\scripts\run-evavo-game-runtime-world-streaming.ps1 `
    -GodotPath $env:GODOT_BIN `
    -RuntimeRepo C:\GitRepos\evavo-game-runtime
```

Receipts are written outside both repositories by default:

```text
C:\GodotLabEvidence\evavo-game-runtime-world-streaming\<run-id>\
```

## Evidence

The lane verifies:

- deterministic region admission order;
- omission under a declared memory-admission budget;
- bounded concurrent load dispatch;
- generation-aware region activation fences;
- source and target preparation receipts;
- snapshot readiness;
- target-region activation readiness;
- no authority commit before the declared simulation tick;
- authority commit at the declared tick;
- authority epoch advancement;
- abort after the configured late-commit window;
- source authority preservation after an aborted handoff;
- explicit cancellation-drain acknowledgement.

The final receipt includes the exact runtime and Test Lab commit SHAs and embeds
the runtime's `EVAVO_WORLD_STREAMING_SMOKE` evidence.

## Boundaries

The lane does not claim that manifest `memory_mb` estimates equal live CPU or GPU
memory. Those values are deterministic admission inputs. Live memory must be
measured by the performance and native execution lanes.

The lane also does not claim that Godot threaded loading supports an immediate
hard cancel. It verifies the runtime's stop-dispatch, drain and acknowledge
semantics.

Spatial replication, prediction, physics and render partition evidence remain
separate lower-level responsibilities. This lane verifies game-runtime
orchestration and exact-tick authority receipts.
