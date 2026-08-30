# EVAVO Game Runtime Region Content Delivery Validation

This suite validates the boundary between EVAVO world residency, package
delivery and per-region content activation. It is intentionally local and does
not use GitHub Actions, Vercel or another paid CI service.

## What the suite proves

The source checks validate:

- strict v2 content package declarations while preserving v1 compatibility;
- deterministic platform/profile variant selection;
- optional patch and entitlement-locked DLC policy;
- explicit activation blockers;
- package-to-world-region bindings;
- host-neutral delivery APIs;
- generation-aware install and cancellation state;
- one content-activation coordinator per streamed region;
- staged, ready, active, deactivated and unloaded region states;
- local scripts and reference fixtures.

When a local Godot 4.6.2 or newer executable is available, the executable checks
also perform:

- project import and GDScript parse;
- the deterministic in-memory delivery-session smoke;
- the real Godot threaded resource-load, warm-up, activation-fence,
  deactivation/reactivation and unload smoke for the region driver.

## What the suite does not prove

The in-memory delivery host is synthetic test infrastructure. It does not prove:

- a real Steam, Microsoft, Google Play or Apple storefront install;
- a real CDN or network transfer;
- measured downloaded bytes or measured installed disk bytes;
- immediate hard cancellation of a Godot threaded load;
- simulation authority granted by package or resource completion.

The generated receipt fixes all of these claims to `false`. Declared package
byte sizes remain planning metadata. Synthetic progress is labelled as such.
Threaded cancellation remains in a draining state until the host reports a
terminal result.

## SHA-bound evidence

Every receipt records:

- the exact `evavo-game-runtime` runtime SHA;
- the exact `godot-game-test-lab` Test Lab SHA;
- both checked-out branches;
- the local Godot version, when available;
- one status, exit code, log and marker for each source and executable check.

The verifier requires both repositories to be on `main`. A receipt cannot be
reused as evidence for a different runtime SHA or Test Lab SHA.

## Run locally on Windows

```powershell
Set-Location C:\GitRepos\evavo-game-runtime
git pull --ff-only origin main

Set-Location C:\GitRepos\godot-game-test-lab
git pull --ff-only origin main

python .\scripts\validate-evavo-game-runtime-region-content-delivery.py

.\scripts\run-evavo-game-runtime-region-content-delivery.ps1 `
    -RuntimeRepo C:\GitRepos\evavo-game-runtime `
    -GodotPath $env:GODOT_BIN `
    -RequireGodot
```

The runner prints:

```text
EVAVO_REGION_CONTENT_DELIVERY_RECEIPT=<absolute receipt path>
EVAVO_REGION_CONTENT_DELIVERY_STATUS=pass|partial|fail
```

Without `-RequireGodot`, a machine that has no local Godot executable may
produce a `partial` receipt only when both source checks pass. Executable checks
are then marked `skipped`; they are never silently counted as passing.

## Receipt interpretation

`pass` means both source validators, Godot import, delivery-session smoke and
region-driver smoke passed for the exact recorded runtime SHA and Test Lab SHA.

`partial` means source validation passed but one or more executable checks were
explicitly skipped because the required local executable was unavailable.

`fail` means at least one source or executable check failed. The corresponding
log remains in the receipt evidence root.

## Configuration and contracts

Suite configuration:

```text
config/evavo-game-runtime-region-content-delivery.v1.json
```

Receipt contract:

```text
contracts/evavo-game-runtime-region-content-delivery-receipt-v1.json
```

Receipt verifier:

```text
scripts/verify-evavo-game-runtime-region-content-delivery-receipt.py
```

All three are dependency-free and suitable for the EVAVO $0 GitHub and $0
Vercel operating model.
