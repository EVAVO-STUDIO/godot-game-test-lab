# Authority Peer-Exchange Semantic Cross-Check

This lane cross-checks two independent Test Lab interpretations of the same server-authority multiplayer evidence:

1. the authority lifecycle verifier, which proves single membership, reciprocal presence, departure revocation, reconnect restoration, privacy-safe identity projection, superseded-socket retirement, and stale-socket send rejection; and
2. the standard multiplayer peer-exchange verifier, which proves dynamic captured metadata for one shared session, unique local peer IDs, and exact reciprocal observed-peer sets.

A PASS is intentionally stronger than either interpretation alone because both views must describe the same retained evidence and agree exactly.

## Required artifact bundle

The artifact root must contain:

```text
authority-peer-exchange-lifecycle.json
profile.normalized.json
multiplayer-agent-summary.json
```

`authority-peer-exchange-lifecycle.json` must be a valid authority receipt schema `2.0`.

`profile.normalized.json` must configure `metadata_capture` for every required role using the reserved keys:

```text
evavo_peer_session_id
evavo_local_peer_id
evavo_observed_peer_ids
```

`multiplayer-agent-summary.json` must retain the corresponding actual captured values. Legacy `metadata_equals` assertions are not sufficient for the semantic cross-check.

The standard multiplayer artifact inventory must include the retained authority lifecycle receipt and normalized profile, so modifying either file after bundle creation invalidates the peer-exchange evidence before the semantic comparison even begins.

## What PASS requires

`EVAVO_AUTHORITY_PEER_EXCHANGE_CROSSCHECK=PASS roles=N` requires:

- authority lifecycle receipt schema v2;
- `authorityLifecycleProven=true`;
- `authoritySafetyProven=true`;
- standard peer exchange `configured=true` and `proven=true`;
- dynamic metadata captures for every required role;
- identical required role counts;
- identical role IDs;
- one identical shared session ID;
- identical role-to-local-peer mapping;
- identical reciprocal observed-peer sets.

The cross-check fails closed on any disagreement.

## Galactic Cycle Online

`godot-462-galactic-cycle-online` provides a canonical bundle producer:

```text
authority/scripts/emit_test_lab_peer_exchange_bundle.mjs
```

It does not implement another room simulator. It executes the game's canonical:

```text
authority/scripts/emit_peer_exchange_evidence.mjs
```

requires that emitter's exact PASS marker and v2 authority-safety receipt, then converts the verified reconnect phase into the standard Test Lab dynamic-capture artifact shape.

From the Galactic Cycle authority directory you can generate a bundle with:

```powershell
npm run peer-evidence:test-lab -- C:\Temp\galactic-peer-bundle
```

Then verify it directly from a Test Lab checkout:

```powershell
$env:PYTHONPATH = (Join-Path $PWD "src")
python -m godot_game_test_lab.authority_peer_exchange_crosscheck C:\Temp\galactic-peer-bundle
```

## Exact-SHA workstation gate

For the source-bound form, use:

```powershell
$Lab = "C:\GitRepos\godot-game-test-lab"
$Target = "C:\GitRepos\godot-462-galactic-cycle-online"
$TargetSha = (git -C $Target rev-parse HEAD).Trim()
$LabSha = (git -C $Lab rev-parse HEAD).Trim()

& "$Lab\scripts\Invoke-AuthorityPeerExchangeCrosscheck.ps1" `
  -TargetRepoRoot $Target `
  -ExpectedTargetSha $TargetSha `
  -ExpectedLabSha $LabSha
```

The runner requires both repositories to be clean `main` checkouts, verifies exact SHAs before execution, requires Node.js 20+, generates the standard bundle outside the repositories, invokes the canonical cross-check module, requires exactly one expected PASS marker, rechecks both repositories for mutation, and writes a retained `acceptance.json` containing source SHAs plus SHA-256 digests of the authority receipt, normalized profile, and multiplayer summary.

## Truth boundary

This lane remains a **server-authority semantic proof using the game's real authority implementation under in-memory Durable Object/socket fixtures**.

It does not prove:

- browser or native client transport traversal;
- a deployed Cloudflare Worker/Durable Object instance;
- WebSocket/WAN latency or packet-loss behavior;
- runtime admission across the hosted EVAVO Web Runtime;
- rendering, UX, gameplay feel, or release readiness.

For Galactic Cycle, the next stronger multiplayer certification layer is a two-browser production-path acceptance run through EVAVO runtime admission and the deployed game authority, with both clients dynamically capturing the same reserved peer-exchange metadata.
