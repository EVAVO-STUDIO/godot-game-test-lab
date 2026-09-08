# Authority Peer-Exchange Acceptance

This lane verifies privacy-safe multiplayer lifecycle evidence emitted by a game-owned server-authority implementation. It is designed for authoritative games whose real room membership is owned by a server, Durable Object, relay, or equivalent service rather than by a native Godot `MultiplayerPeer` host.

It is intentionally separate from native concurrent multiplayer QA and browser-client QA.

## What a PASS proves

`EVAVO_AUTHORITY_PEER_EXCHANGE=PASS` requires one strict four-phase receipt:

1. `single` — one participant is present and observes no remote peer.
2. `reciprocal` — at least two participants report the same session and each reports the exact set of every other participant.
3. `departure` — exactly the declared departing role is removed and every remaining participant reports the exact reduced peer set.
4. `reconnect` — the original role inventory is restored and exact reciprocal observation is restored.

The verifier also requires:

- one bounded shared session identifier;
- unique positive ephemeral peer IDs inside each phase;
- a stable role-to-peer mapping across the accepted four-phase scenario;
- bounded role inventories and observed-peer lists;
- no self-observation or duplicate observed peers;
- literal `false` privacy statements for raw player IDs, runtime-session IDs, and credentials;
- UTF-8 JSON no larger than 128 KiB;
- no unexpected receipt fields.

The room protocol may define peer slots as ephemeral and may renumber them for membership changes outside this particular acceptance scenario. The retained acceptance proof is deliberately stricter: surviving roles and the reconnected role must preserve the reciprocal mapping demonstrated earlier in the same run. This prevents an ambiguous lifecycle from being promoted into a PASS.

### Receipt v2 authority safety

Current emitters should issue receipt schema `2.0`. In addition to the lifecycle fields, v2 requires:

```json
"authoritySafety": {
  "supersededSocketRetired": true,
  "staleSocketSendRejected": true
}
```

These values must be derived from the authority implementation under test. They prove that a superseded reconnect socket lost authority and that a subsequent send from that stale socket was rejected before ordinary message processing.

Receipt v1 remains readable for historical evidence, but it does **not** set `authoritySafetyProven=true` and is not sufficient for new acceptance-v3 issuance.

## What a PASS does not prove

This lane does **not** by itself prove that a browser or native Godot client traversed the production transport path. The structured verifier therefore reports:

- `authorityLifecycleProven: true` when the lifecycle passes;
- `authoritySafetyProven: true` only for a valid v2 safety receipt;
- `transportProven: false`;
- `browserTransportProven: false`.

It does not certify WebSocket/WAN quality, packet loss behavior, latency, browser lifecycle recovery, rendering, gameplay correctness, or release readiness.

Use it alongside client-side multiplayer QA. For Web-only games, the stronger downstream lane must launch real Web clients through runtime admission and capture the same reserved peer evidence from those clients.

## Current receipt contract

A game-owned emitter writes one JSON object to stdout with this top-level shape:

```json
{
  "schemaVersion": "2.0",
  "kind": "evavo-authority-peer-exchange-lifecycle",
  "gameId": "example-game",
  "authority": "ExampleRoom",
  "protocol": "example.v1",
  "sessionId": "room-001",
  "departedRoleId": "beta",
  "phases": [
    { "id": "single", "roles": [] },
    { "id": "reciprocal", "roles": [] },
    { "id": "departure", "roles": [] },
    { "id": "reconnect", "roles": [] }
  ],
  "privacy": {
    "rawPlayerIdsTransmitted": false,
    "runtimeSessionIdsTransmitted": false,
    "credentialsTransmitted": false
  },
  "authoritySafety": {
    "supersededSocketRetired": true,
    "staleSocketSendRejected": true
  },
  "truthBoundary": "Server authority lifecycle proof only."
}
```

Each role record has exactly:

```json
{
  "id": "alpha",
  "sessionId": "room-001",
  "localPeerId": 1,
  "observedPeerIds": [2]
}
```

Do not place account IDs, email addresses, IP addresses, join tickets, reconnect tokens, authorization headers, cookies, or other credentials in this receipt.

## Direct verifier

From a Test Lab checkout:

```powershell
$env:PYTHONPATH = (Join-Path $PWD "src")
python -m godot_game_test_lab.authority_peer_exchange C:\evidence\authority-peer-exchange.json
```

Successful output ends with:

```text
EVAVO_AUTHORITY_PEER_EXCHANGE=PASS roles=2
```

## Exact-SHA local acceptance

For a clean target repository, use the PowerShell 5.1-compatible acceptance wrapper:

```powershell
$Lab = "C:\GitRepos\godot-game-test-lab"
$Target = "C:\GitRepos\godot-462-galactic-cycle-online"
$TargetSha = (git -C $Target rev-parse HEAD).Trim()
$LabSha = (git -C $Lab rev-parse HEAD).Trim()

& "$Lab\scripts\Invoke-AuthorityPeerExchangeAcceptance.ps1" `
  -TargetRepoRoot $Target `
  -ExpectedTargetSha $TargetSha `
  -ExpectedLabSha $LabSha
```

The wrapper:

- requires both target and Test Lab to be clean `main` checkouts;
- requires the target to be exactly at the requested SHA before execution;
- runs the game-owned authority emitter;
- requires exactly one `EVAVO_AUTHORITY_PEER_EXCHANGE_RECEIPT=PASS` marker;
- retains the emitter JSON outside the target repository as UTF-8;
- independently invokes the canonical Test Lab verifier;
- requires receipt schema v2, lifecycle proof, privacy safety, stable mapping, and stale-socket authority safety;
- explicitly requires `transportProven=false` and `browserTransportProven=false` so authority evidence cannot be escalated into a transport claim;
- rechecks exact target/Test Lab SHA and clean state after execution;
- records the receipt SHA-256 and byte count in `acceptance.json`;
- independently re-verifies the retained manifest before promoting it from `acceptance.pending.json`.

New runs emit acceptance manifest schema **`3.0`**. The v3 verifier binds:

- exact target and Test Lab SHAs;
- exact retained receipt digest and byte count;
- receipt schema version;
- authority lifecycle proof;
- authority safety proof;
- privacy and stable mapping claims;
- explicit non-transport truth flags.

Previously retained acceptance schema `2.0` remains readable for backward compatibility, but new issuance uses v3.

Successful wrapper output contains:

```text
EVAVO_AUTHORITY_PEER_EXCHANGE_ACCEPTANCE=PASS target_sha=<40-hex-sha> lab_sha=<40-hex-sha>
```

## Galactic Cycle Online

`godot-462-galactic-cycle-online` owns its canonical emitter at:

```text
authority/scripts/emit_peer_exchange_evidence.mjs
```

Its normal authority validation also runs that emitter:

```powershell
Set-Location C:\GitRepos\godot-462-galactic-cycle-online\authority
npm run validate
```

The Galactic Cycle emitter exercises the real `GalacticCycleRoom` presence implementation for single membership, reciprocal membership, departure revocation, reconnect de-duplication, restored reciprocity, superseded-socket retirement, and rejection of a stale socket attempting to send after replacement. The retained wire evidence deliberately excludes raw player IDs and runtime-session IDs.

## Evidence handling

Keep generated acceptance evidence outside both the target repository and Test Lab repository. Evidence is technical verification, not a publication approval. A later browser/native client acceptance receipt should be linked to the same exact target SHA when making a broader multiplayer release claim.
